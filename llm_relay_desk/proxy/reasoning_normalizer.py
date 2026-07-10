from __future__ import annotations

import copy
import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


# vLLM can expose Qwen reasoning in one of three forms:
# 1. structured reasoning_content / reasoning / thinking fields;
# 2. <think>...</think> or <analysis>...</analysis> inside content;
# 3. channel special tokens when skip_special_tokens=false.
#
# Qwen templates may place the opening reasoning token in the prompt rather than
# in generated text. In that case the completion starts with reasoning and only
# contains the closing/final marker. UNKNOWN mode intentionally buffers until
# that boundary appears.
_OPEN_MARKER_RE = re.compile(
    r"""(?isx)
    (?:
        <\s*(?:think|analysis)\s*>
        |
        <\|analysis\|>
        |
        <\|channel\|>\s*analysis\s*<\|message\|>
        |
        <\|start\|>\s*assistant\s*<\|channel\|>\s*analysis\s*<\|message\|>
        |
        <\|im_start\|>\s*assistant\s*(?:\r?\n)?\s*
        <\|channel\|>\s*analysis\s*<\|message\|>
    )
    """
)

_CLOSE_MARKER_RE = re.compile(
    r"""(?isx)
    (?:
        <\s*/\s*(?:think|analysis)\s*>
        |
        <\|final\|>
        |
        <\|channel\|>\s*final\s*<\|message\|>
        |
        <\|start\|>\s*assistant\s*<\|channel\|>\s*final\s*<\|message\|>
        |
        <\|im_start\|>\s*assistant\s*(?:\r?\n)?\s*
        <\|channel\|>\s*final\s*<\|message\|>
    )
    """
)

_CONTROL_TOKEN_RE = re.compile(
    r"""(?isx)
    (?:
        <\|im_end\|>
        |
        <\|im_start\|>\s*assistant
        |
        <\|endoftext\|>
        |
        <\|end\|>
        |
        <\|message\|>
        |
        <\|start\|>\s*assistant
        |
        <\|channel\|>\s*(?:analysis|final)
        |
        <\|(?:analysis|final)\|>
    )
    """
)

_FINAL_LABEL_RE = re.compile(
    r"""(?im)
    ^\s*
    (?:
        final\s+(?:answer|response)
        |
        answer
        |
        最终答案
        |
        最终回答
        |
        正式回答
        |
        答案
    )
    \s*[:：]\s*
    """
)

_REASONING_PREFIXES = (
    "here's a thinking process:",
    "here is a thinking process:",
    "here's my thinking process:",
    "here is my thinking process:",
    "we need to answer",
    "we need answer",
    "we need to respond",
    "we need respond",
    "we need analyze",
    "let's reason",
    "let us reason",
    "我们需要分析",
    "需要先分析",
    "思考过程",
)

_REASONING_FIELD_KEYS = ("reasoning_content", "reasoning", "thinking")
_MARKER_TAIL = 64
_CONTENT_TAIL = 16
_MAX_UNDECIDED_CHARS = 2_000_000
_MAX_TRACKED_REQUESTS = 256


@dataclass(slots=True)
class SplitDelta:
    reasoning: str = ""
    content: str = ""

    def append(self, other: "SplitDelta") -> None:
        self.reasoning += other.reasoning
        self.content += other.content


def _text_from_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, dict):
                    text = text.get("value", "")
                if text is None:
                    text = item.get("content", "")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    if isinstance(value, dict):
        return _text_from_content(
            value.get("text") or value.get("value") or value.get("content")
        )
    return ""


def _existing_reasoning(container: dict[str, Any]) -> str:
    for key in _REASONING_FIELD_KEYS:
        text = _text_from_content(container.get(key))
        if text:
            return text
    return ""


def _clean_control_tokens(text: str) -> str:
    if not text:
        return ""
    text = _OPEN_MARKER_RE.sub("", text)
    text = _CLOSE_MARKER_RE.sub("", text)
    text = _CONTROL_TOKEN_RE.sub("", text)
    return text.replace("\x00", "")


def _looks_like_reasoning_prefix(text: str) -> bool:
    value = text.lstrip().lower()
    return any(value.startswith(prefix) for prefix in _REASONING_PREFIXES)


def _trailing_json_boundary(text: str) -> tuple[str, str] | None:
    """Return a trailing JSON object/array when the prefix is leaked reasoning."""

    if not _looks_like_reasoning_prefix(text):
        return None

    candidates: list[int] = []
    for index, char in enumerate(text):
        if char in "[{" and (index == 0 or text[index - 1] == "\n"):
            candidates.append(index)

    for index in reversed(candidates[-64:]):
        candidate = text[index:].strip()
        if not candidate:
            continue
        try:
            json.loads(candidate)
        except json.JSONDecodeError:
            continue
        reasoning = text[:index].rstrip()
        if len(reasoning) >= 120:
            return reasoning, candidate
    return None


def _plain_reasoning_fallback(text: str) -> tuple[str, str] | None:
    """Conservative fallback for vLLM output whose special tokens were stripped.

    This only activates for well-known leaked reasoning preambles and requires
    either an explicit final-answer label, trailing JSON, or a short final line
    after several numbered/Markdown reasoning sections.
    """

    if not _looks_like_reasoning_prefix(text):
        return None

    labels = list(_FINAL_LABEL_RE.finditer(text))
    if labels:
        marker = labels[-1]
        if marker.start() >= 100:
            reasoning = text[: marker.start()].rstrip()
            content = text[marker.end() :].strip()
            if content:
                return reasoning, content

    trailing_json = _trailing_json_boundary(text)
    if trailing_json is not None:
        return trailing_json

    nonempty = [
        (match.start(), match.group(0).strip())
        for match in re.finditer(r"(?m)^.*\S.*$", text)
    ]
    if len(nonempty) < 6:
        return None

    final_start, final_line = nonempty[-1]
    reasoning_part = text[:final_start].rstrip()
    if len(reasoning_part) < 180 or not final_line:
        return None
    if len(final_line) > 512:
        return None
    if re.match(r"^(?:[-*+]|\d+[.)])\s+", final_line):
        return None
    if final_line.startswith("#") or final_line.endswith(":"):
        return None

    numbered_steps = len(
        re.findall(r"(?m)^\s*\d+[.)]\s+|\*\*[^*\n]{2,80}:\*\*", reasoning_part)
    )
    if numbered_steps < 3:
        return None

    return reasoning_part, final_line


def split_complete_text(text: str) -> SplitDelta:
    """Split a complete assistant text into reasoning and final content."""

    if not text:
        return SplitDelta()

    working = text.replace("\x00", "")

    open_match = _OPEN_MARKER_RE.search(working)
    close_match = _CLOSE_MARKER_RE.search(working)

    if open_match and close_match and close_match.start() >= open_match.end():
        prefix = working[: open_match.start()]
        reasoning = working[open_match.end() : close_match.start()]
        content = prefix + working[close_match.end() :]
        return SplitDelta(
            reasoning=_clean_control_tokens(reasoning).strip(),
            content=_clean_control_tokens(content).strip(),
        )

    # Qwen/vLLM commonly places the opening token in the generation prompt.
    # The generated completion therefore starts with plain reasoning text and
    # contains only ``</think>`` (or a final-channel marker) before the answer.
    # A closing reasoning marker is an unambiguous boundary even when the
    # opening marker is absent.
    if close_match:
        reasoning = working[: close_match.start()]
        content = working[close_match.end() :].lstrip("\r\n")
        return SplitDelta(
            reasoning=_clean_control_tokens(reasoning).strip(),
            content=_clean_control_tokens(content).strip(),
        )

    if open_match:
        prefix = working[: open_match.start()]
        reasoning = working[open_match.end() :]
        if not prefix.strip():
            return SplitDelta(
                reasoning=_clean_control_tokens(reasoning).strip(),
                content="",
            )

    fallback = _plain_reasoning_fallback(_clean_control_tokens(working))
    if fallback is not None:
        reasoning, content = fallback
        return SplitDelta(reasoning=reasoning.strip(), content=content.strip())

    return SplitDelta(content=_clean_control_tokens(working))


class InlineReasoningSplitter:
    """Incrementally split inline reasoning markers across arbitrary chunks."""

    def __init__(self) -> None:
        self.mode = "unknown"
        self.pending = ""
        self.structured = False
        self.finished = False

    def absorb_structured(
        self,
        *,
        reasoning: str = "",
        content: str = "",
    ) -> SplitDelta:
        self.structured = True
        self.mode = "content"
        return SplitDelta(
            reasoning=_clean_control_tokens(reasoning),
            content=_clean_control_tokens(content),
        )

    def feed(self, text: str) -> SplitDelta:
        if self.finished or not text:
            return SplitDelta()
        if self.structured:
            return SplitDelta(content=_clean_control_tokens(text))

        self.pending += text
        return self._drain(final=False)

    def finish(self) -> SplitDelta:
        if self.finished:
            return SplitDelta()
        self.finished = True

        if self.structured:
            result = SplitDelta(content=_clean_control_tokens(self.pending))
            self.pending = ""
            return result

        if self.mode == "unknown":
            result = split_complete_text(self.pending)
            self.pending = ""
            return result

        if self.mode == "reasoning":
            result = SplitDelta(reasoning=_clean_control_tokens(self.pending))
            self.pending = ""
            return result

        result = SplitDelta(content=_clean_control_tokens(self.pending))
        self.pending = ""
        return result

    def _drain(self, *, final: bool) -> SplitDelta:
        result = SplitDelta()

        while True:
            if self.mode == "unknown":
                open_match = _OPEN_MARKER_RE.search(self.pending)
                close_match = _CLOSE_MARKER_RE.search(self.pending)

                if close_match and (
                    open_match is None or close_match.start() < open_match.start()
                ):
                    result.reasoning += _clean_control_tokens(
                        self.pending[: close_match.start()]
                    )
                    self.pending = self.pending[close_match.end() :].lstrip("\r\n")
                    self.mode = "content"
                    continue

                if open_match is not None:
                    prefix = self.pending[: open_match.start()]
                    if prefix.strip():
                        result.content += _clean_control_tokens(prefix)
                    self.pending = self.pending[open_match.end() :]
                    self.mode = "reasoning"
                    continue

                # Qwen/vLLM may omit the opening <think> token because it was
                # inserted by the chat template. Once a known reasoning
                # preamble is complete, switch to reasoning mode immediately
                # instead of buffering the entire trace until </think>.
                if _looks_like_reasoning_prefix(self.pending):
                    self.mode = "reasoning"
                    continue

                if len(self.pending) > _MAX_UNDECIDED_CHARS:
                    result.content += _clean_control_tokens(self.pending)
                    self.pending = ""
                    self.mode = "content"
                break

            if self.mode == "reasoning":
                close_match = _CLOSE_MARKER_RE.search(self.pending)
                if close_match is not None:
                    result.reasoning += _clean_control_tokens(
                        self.pending[: close_match.start()]
                    )
                    self.pending = self.pending[close_match.end() :].lstrip("\r\n")
                    self.mode = "content"
                    continue

                if final:
                    result.reasoning += _clean_control_tokens(self.pending)
                    self.pending = ""
                elif len(self.pending) > _MARKER_TAIL:
                    safe = self.pending[:-_MARKER_TAIL]
                    self.pending = self.pending[-_MARKER_TAIL:]
                    result.reasoning += _clean_control_tokens(safe)
                break

            if self.mode == "content":
                if final:
                    result.content += _clean_control_tokens(self.pending)
                    self.pending = ""
                elif len(self.pending) > _CONTENT_TAIL:
                    # Only retain enough text to catch a split trailing control
                    # token such as <|im_end|>. Final-answer text should otherwise
                    # be released immediately.
                    safe = self.pending[:-_CONTENT_TAIL]
                    self.pending = self.pending[-_CONTENT_TAIL:]
                    result.content += _clean_control_tokens(safe)
                break

        return result


def _set_reasoning(container: dict[str, Any], reasoning: str) -> None:
    for key in ("reasoning", "thinking"):
        container.pop(key, None)
    if reasoning:
        container["reasoning_content"] = reasoning
    else:
        container.pop("reasoning_content", None)


def normalize_openai_object(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize a complete OpenAI-compatible response object in place."""

    choices = value.get("choices")
    if not isinstance(choices, list):
        return value

    for choice in choices:
        if not isinstance(choice, dict):
            continue
        container = choice.get("message")
        if not isinstance(container, dict):
            container = choice.get("delta")
        if not isinstance(container, dict):
            continue

        reasoning = _existing_reasoning(container)
        content_value = container.get("content")
        if content_value is None:
            content_value = container.get("text")
        content = _text_from_content(content_value)

        if reasoning:
            normalized_reasoning = _clean_control_tokens(reasoning)
            normalized_content = _clean_control_tokens(content)
        else:
            split = split_complete_text(content)
            normalized_reasoning = split.reasoning
            normalized_content = split.content

        if "content" in container or content_value is not None:
            container["content"] = normalized_content
        if "text" in container:
            container["text"] = normalized_content
        _set_reasoning(container, normalized_reasoning)

    return value


class OpenAIStreamNormalizer:
    """Normalize OpenAI SSE event objects while preserving choice metadata."""

    def __init__(self) -> None:
        self.states: dict[int, InlineReasoningSplitter] = {}
        self.last_template: dict[str, Any] | None = None

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        normalized = copy.deepcopy(value)
        self.last_template = copy.deepcopy(value)

        choices = normalized.get("choices")
        if not isinstance(choices, list):
            return normalized

        for position, choice in enumerate(choices):
            if not isinstance(choice, dict):
                continue
            index = int(choice.get("index", position) or 0)
            state = self.states.setdefault(index, InlineReasoningSplitter())

            container = choice.get("delta")
            if not isinstance(container, dict):
                container = choice.get("message")
            if not isinstance(container, dict):
                continue

            existing = _existing_reasoning(container)
            content = _text_from_content(
                container.get("content")
                if "content" in container
                else container.get("text")
            )

            if existing:
                split = state.absorb_structured(
                    reasoning=existing,
                    content=content,
                )
            else:
                split = state.feed(content)

            if choice.get("finish_reason") is not None:
                split.append(state.finish())

            if "content" in container or content or split.content:
                container["content"] = split.content
            if "text" in container:
                container["text"] = split.content
            _set_reasoning(container, split.reasoning)

        return normalized

    def flush_events(self) -> list[dict[str, Any]]:
        if self.last_template is None:
            return []

        pending_choices: list[dict[str, Any]] = []
        for index, state in sorted(self.states.items()):
            split = state.finish()
            if not split.content and not split.reasoning:
                continue
            delta: dict[str, Any] = {}
            if split.content:
                delta["content"] = split.content
            if split.reasoning:
                delta["reasoning_content"] = split.reasoning
            pending_choices.append(
                {
                    "index": index,
                    "delta": delta,
                    "finish_reason": None,
                }
            )

        if not pending_choices:
            return []

        template = {
            key: copy.deepcopy(value)
            for key, value in self.last_template.items()
            if key != "choices"
        }
        template["choices"] = pending_choices
        return [template]


def normalize_native_object(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize one complete Ollama-style response object in place."""

    message = value.get("message")
    if isinstance(message, dict):
        reasoning = _existing_reasoning(message)
        content = _text_from_content(message.get("content"))
        if reasoning:
            split = SplitDelta(
                reasoning=_clean_control_tokens(reasoning),
                content=_clean_control_tokens(content),
            )
        else:
            split = split_complete_text(content)
        message["content"] = split.content
        for key in ("reasoning_content", "reasoning"):
            message.pop(key, None)
        if split.reasoning:
            message["thinking"] = split.reasoning
        else:
            message.pop("thinking", None)
        return value

    reasoning = _existing_reasoning(value)
    content = _text_from_content(value.get("response"))
    if reasoning:
        split = SplitDelta(
            reasoning=_clean_control_tokens(reasoning),
            content=_clean_control_tokens(content),
        )
    else:
        split = split_complete_text(content)
    value["response"] = split.content
    for key in ("reasoning_content", "reasoning"):
        value.pop(key, None)
    if split.reasoning:
        value["thinking"] = split.reasoning
    else:
        value.pop("thinking", None)
    return value


class NativeStreamNormalizer:
    def __init__(self) -> None:
        self.state = InlineReasoningSplitter()

    def normalize(self, value: dict[str, Any]) -> dict[str, Any]:
        normalized = copy.deepcopy(value)
        message = normalized.get("message")
        if isinstance(message, dict):
            reasoning = _existing_reasoning(message)
            content = _text_from_content(message.get("content"))
            if reasoning:
                split = self.state.absorb_structured(
                    reasoning=reasoning,
                    content=content,
                )
            else:
                split = self.state.feed(content)
            if normalized.get("done") is True:
                split.append(self.state.finish())
            message["content"] = split.content
            for key in ("reasoning_content", "reasoning"):
                message.pop(key, None)
            if split.reasoning:
                message["thinking"] = split.reasoning
            else:
                message.pop("thinking", None)
            return normalized

        reasoning = _existing_reasoning(normalized)
        content = _text_from_content(normalized.get("response"))
        if reasoning:
            split = self.state.absorb_structured(
                reasoning=reasoning,
                content=content,
            )
        else:
            split = self.state.feed(content)
        if normalized.get("done") is True:
            split.append(self.state.finish())
        normalized["response"] = split.content
        for key in ("reasoning_content", "reasoning"):
            normalized.pop(key, None)
        if split.reasoning:
            normalized["thinking"] = split.reasoning
        else:
            normalized.pop("thinking", None)
        return normalized


class OpenAISSETransformer:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.normalizer = OpenAIStreamNormalizer()

    def feed(self, chunk: bytes) -> list[bytes]:
        self.buffer.extend(chunk)
        output: list[bytes] = []
        while True:
            pos, delimiter = _find_event_delimiter(self.buffer)
            if pos < 0:
                break
            block = bytes(self.buffer[:pos])
            del self.buffer[: pos + delimiter]
            output.extend(self._transform_block(block))
        return output

    def flush(self) -> list[bytes]:
        output: list[bytes] = []
        if self.buffer:
            output.extend(self._transform_block(bytes(self.buffer)))
            self.buffer.clear()
        output.extend(
            _encode_sse_json(event)
            for event in self.normalizer.flush_events()
        )
        return output

    def _transform_block(self, block: bytes) -> list[bytes]:
        text = block.decode("utf-8", errors="replace").replace("\r\n", "\n")
        data_lines = [
            line[5:].lstrip()
            for line in text.split("\n")
            if line.startswith("data:")
        ]
        if not data_lines:
            return [block + b"\n\n"]

        data = "\n".join(data_lines).strip()
        if data == "[DONE]":
            output = [
                _encode_sse_json(event)
                for event in self.normalizer.flush_events()
            ]
            output.append(b"data: [DONE]\n\n")
            return output
        if not data:
            return [block + b"\n\n"]

        try:
            value = json.loads(data)
        except json.JSONDecodeError:
            return [block + b"\n\n"]
        if not isinstance(value, dict):
            return [block + b"\n\n"]

        return [_encode_sse_json(self.normalizer.normalize(value))]


class NativeNDJSONTransformer:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.normalizer = NativeStreamNormalizer()

    def feed(self, chunk: bytes) -> list[bytes]:
        self.buffer.extend(chunk)
        output: list[bytes] = []
        while True:
            index = self.buffer.find(b"\n")
            if index < 0:
                break
            line = bytes(self.buffer[:index]).strip()
            del self.buffer[: index + 1]
            output.extend(self._transform_line(line))
        return output

    def flush(self) -> list[bytes]:
        line = bytes(self.buffer).strip()
        self.buffer.clear()
        return self._transform_line(line)

    def _transform_line(self, line: bytes) -> list[bytes]:
        if not line:
            return []
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return [line + b"\n"]
        if not isinstance(value, dict):
            return [line + b"\n"]
        normalized = self.normalizer.normalize(value)
        return [
            json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        ]


def _find_event_delimiter(buffer: bytearray) -> tuple[int, int]:
    raw = bytes(buffer)
    lf = raw.find(b"\n\n")
    crlf = raw.find(b"\r\n\r\n")
    candidates = [(lf, 2), (crlf, 4)]
    candidates = [(pos, size) for pos, size in candidates if pos >= 0]
    return min(candidates, key=lambda item: item[0]) if candidates else (-1, 0)


def _encode_sse_json(value: dict[str, Any]) -> bytes:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return f"data: {payload}\n\n".encode("utf-8")


class RequestNormalizerRegistry:
    """Bounded request-state registry used by monitoring extraction."""

    def __init__(self, limit: int = _MAX_TRACKED_REQUESTS) -> None:
        self.limit = max(8, int(limit))
        self.openai: OrderedDict[str, OpenAIStreamNormalizer] = OrderedDict()
        self.native: OrderedDict[str, NativeStreamNormalizer] = OrderedDict()

    def openai_normalizer(self, request_id: str) -> OpenAIStreamNormalizer:
        normalizer = self.openai.get(request_id)
        if normalizer is None:
            normalizer = OpenAIStreamNormalizer()
            self.openai[request_id] = normalizer
        self.openai.move_to_end(request_id)
        self._trim(self.openai)
        return normalizer

    def native_normalizer(self, request_id: str) -> NativeStreamNormalizer:
        normalizer = self.native.get(request_id)
        if normalizer is None:
            normalizer = NativeStreamNormalizer()
            self.native[request_id] = normalizer
        self.native.move_to_end(request_id)
        self._trim(self.native)
        return normalizer

    def discard(self, request_id: str) -> None:
        self.openai.pop(request_id, None)
        self.native.pop(request_id, None)

    def _trim(self, mapping: OrderedDict[str, Any]) -> None:
        while len(mapping) > self.limit:
            mapping.popitem(last=False)
