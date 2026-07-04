from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from llm_relay_desk.storage import JsonStore

from .controller import NativePopupController


DEFAULT_DIALOGUE_FIELDS = ("response", "statement", "dialogue", "speech")


def _configured_fields(config: dict[str, Any]) -> tuple[str, ...]:
    value = config.get("native_popup_dialogue_fields", DEFAULT_DIALOGUE_FIELDS)
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = value
    else:
        items = DEFAULT_DIALOGUE_FIELDS
    normalized: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in normalized:
            normalized.append(text)
    return tuple(normalized or DEFAULT_DIALOGUE_FIELDS)


def _strip_json_fence(text: str) -> str:
    stripped = text.lstrip("\ufeff \t\r\n")
    if not stripped.startswith("```"):
        return stripped
    newline = stripped.find("\n")
    if newline < 0:
        return ""
    stripped = stripped[newline + 1 :]
    if stripped.rstrip().endswith("```"):
        stripped = stripped.rstrip()[:-3]
    return stripped.lstrip()


def _decode_partial_json_string(text: str, start: int) -> tuple[str, bool]:
    output: list[str] = []
    index = start
    while index < len(text):
        char = text[index]
        if char == '"':
            return "".join(output), True
        if char != "\\":
            output.append(char)
            index += 1
            continue
        index += 1
        if index >= len(text):
            break
        escaped = text[index]
        simple = {
            '"': '"',
            "\\": "\\",
            "/": "/",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }
        if escaped in simple:
            output.append(simple[escaped])
            index += 1
            continue
        if escaped == "u":
            digits = text[index + 1 : index + 5]
            if len(digits) < 4:
                break
            try:
                output.append(chr(int(digits, 16)))
            except ValueError:
                output.append("\\u" + digits)
            index += 5
            continue
        output.append(escaped)
        index += 1
    return "".join(output), False


def _find_top_level_string_value(text: str, fields: tuple[str, ...]) -> int | None:
    depth = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in "{[":
            depth += 1
            index += 1
            continue
        if char in "}]":
            depth = max(0, depth - 1)
            index += 1
            continue
        if char != '"':
            index += 1
            continue

        start = index + 1
        key, complete = _decode_partial_json_string(text, start)
        if not complete:
            return None

        # Locate the closing quote while respecting escapes.
        cursor = start
        escaped = False
        while cursor < length:
            current = text[cursor]
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == '"':
                break
            cursor += 1
        if cursor >= length:
            return None

        if depth == 1 and key in fields:
            after = cursor + 1
            while after < length and text[after].isspace():
                after += 1
            if after < length and text[after] == ":":
                after += 1
                while after < length and text[after].isspace():
                    after += 1
                if after < length and text[after] == '"':
                    return after + 1

        index = cursor + 1
    return None


class DialogueTextStream:
    """Extract one top-level dialogue field from a streamed JSON message.

    Plain text is passed through unchanged. JSON control payloads without a
    configured dialogue field produce no subtitle text.
    """

    def __init__(
        self,
        fields: tuple[str, ...],
        *,
        plain_text_fallback: bool = True,
        capture_limit: int = 1_000_000,
    ) -> None:
        self.fields = fields
        self.plain_text_fallback = plain_text_fallback
        self.capture_limit = capture_limit
        self.buffer = ""
        self.mode = "undecided"
        self.value_start: int | None = None
        self.emitted_length = 0

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self.buffer += text
        if len(self.buffer) > self.capture_limit:
            removed = len(self.buffer) - self.capture_limit
            self.buffer = self.buffer[-self.capture_limit :]
            if self.value_start is not None:
                self.value_start = max(0, self.value_start - removed)
            self.emitted_length = max(0, self.emitted_length - removed)

        normalized = _strip_json_fence(self.buffer)
        if self.mode == "undecided":
            if not normalized:
                return ""
            first = normalized[0]
            if first in "{[":
                self.mode = "json"
            elif first == "`" and len(normalized) < 8:
                return ""
            else:
                self.mode = "plain"

        if self.mode == "plain":
            if not self.plain_text_fallback:
                return ""
            output = self.buffer[self.emitted_length :]
            self.emitted_length = len(self.buffer)
            return output

        normalized = _strip_json_fence(self.buffer)
        if self.value_start is None:
            self.value_start = _find_top_level_string_value(normalized, self.fields)
            if self.value_start is None:
                return ""
        decoded, _ = _decode_partial_json_string(normalized, self.value_start)
        output = decoded[self.emitted_length :]
        self.emitted_length = len(decoded)
        return output

    def finish(self) -> str:
        output = self.feed("")
        if output:
            return output
        if self.mode == "plain":
            return ""
        normalized = _strip_json_fence(self.buffer).strip()
        if not normalized:
            return ""
        try:
            value = json.loads(normalized)
        except json.JSONDecodeError:
            return ""
        if not isinstance(value, dict):
            return ""
        for field_name in self.fields:
            candidate = value.get(field_name)
            if isinstance(candidate, str):
                suffix = candidate[self.emitted_length :]
                self.emitted_length = len(candidate)
                return suffix
        return ""


@dataclass(slots=True)
class _RequestSubtitleState:
    start_event: dict[str, Any]
    mode: str
    extractor: DialogueTextStream
    started: bool = False


class SubtitleEventRouter:
    """Route monitor events to the native subtitle after semantic filtering."""

    def __init__(
        self,
        popup: NativePopupController,
        config_store: JsonStore,
    ) -> None:
        self.popup = popup
        self.config_store = config_store
        self.requests: dict[str, _RequestSubtitleState] = {}

    def publish(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        request_id = str(event.get("request_id") or "")
        if not request_id:
            return

        if event_type == "request_start":
            config = self.config_store.read()
            mode = str(config.get("native_popup_content_mode", "dialogue")).strip().lower()
            if mode not in {"dialogue", "all"}:
                mode = "dialogue"
            self.requests[request_id] = _RequestSubtitleState(
                start_event=dict(event),
                mode=mode,
                extractor=DialogueTextStream(
                    _configured_fields(config),
                    plain_text_fallback=bool(
                        config.get("native_popup_plain_text_fallback", True)
                    ),
                ),
            )
            return

        state = self.requests.get(request_id)
        if state is None:
            return

        if event_type == "content_delta":
            raw_text = str(event.get("text") or "")
            text = raw_text if state.mode == "all" else state.extractor.feed(raw_text)
            if text:
                self._ensure_started(state)
                self.popup.publish(
                    {"type": "content_delta", "request_id": request_id, "text": text}
                )
            return

        if event_type == "reasoning_delta":
            config = self.config_store.read()
            show_reasoning = bool(
                config.get("native_popup_show_reasoning", False)
            )
            if state.mode == "all" or show_reasoning:
                # When the user explicitly enables reasoning, do not wait for a
                # dialogue field to be discovered. Some models emit all thinking
                # tokens before a single final content chunk; delaying startup
                # would discard the entire visible stream.
                self._ensure_started(state)
                self.popup.publish(dict(event))
            return

        if event_type in {"request_done", "request_error", "request_cancelled"}:
            if event_type == "request_done" and state.mode == "dialogue":
                remaining = state.extractor.finish()
                if remaining:
                    self._ensure_started(state)
                    self.popup.publish(
                        {
                            "type": "content_delta",
                            "request_id": request_id,
                            "text": remaining,
                        }
                    )
            if state.started:
                self.popup.publish(dict(event))
            self.requests.pop(request_id, None)

    def _ensure_started(self, state: _RequestSubtitleState) -> None:
        if state.started:
            return
        self.popup.publish(dict(state.start_event))
        state.started = True
