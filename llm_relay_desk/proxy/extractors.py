from __future__ import annotations

from typing import Any

from llm_relay_desk.monitoring import MonitorHub

from .reasoning_normalizer import (
    RequestNormalizerRegistry,
    normalize_native_object,
    normalize_openai_object,
)

_NORMALIZERS = RequestNormalizerRegistry()


def text_from_content(value: Any) -> str:
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
        text = value.get("text") or value.get("value") or value.get("content")
        return text_from_content(text)
    return ""


def extract_reasoning(container: dict[str, Any]) -> str:
    for key in ("reasoning_content", "reasoning", "thinking"):
        text = text_from_content(container.get(key))
        if text:
            return text
    return ""


def _publish_openai_normalized(
    hub: MonitorHub,
    request_id: str,
    value: dict[str, Any],
) -> None:
    choices = value.get("choices")
    if not isinstance(choices, list):
        return
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        container = choice.get("delta")
        if not isinstance(container, dict):
            container = choice.get("message")
        if not isinstance(container, dict):
            container = choice
        reasoning = extract_reasoning(container)
        content = text_from_content(container.get("content"))
        if not content:
            content = text_from_content(container.get("text"))
        if reasoning:
            hub.publish(
                {
                    "type": "reasoning_delta",
                    "request_id": request_id,
                    "text": reasoning,
                }
            )
        if content:
            hub.publish(
                {
                    "type": "content_delta",
                    "request_id": request_id,
                    "text": content,
                }
            )


def publish_openai_object(
    hub: MonitorHub,
    request_id: str,
    value: dict[str, Any],
) -> None:
    # Complete responses can be normalized immediately. Stream chunks require
    # request-scoped state because Qwen markers may be split across SSE events.
    choices = value.get("choices")
    is_complete = False
    if isinstance(choices, list):
        is_complete = any(
            isinstance(choice, dict) and isinstance(choice.get("message"), dict)
            for choice in choices
        )

    if is_complete:
        normalized = normalize_openai_object(value)
        _publish_openai_normalized(hub, request_id, normalized)
        _NORMALIZERS.discard(request_id)
        return

    normalizer = _NORMALIZERS.openai_normalizer(request_id)
    normalized = normalizer.normalize(value)
    _publish_openai_normalized(hub, request_id, normalized)

    if isinstance(choices, list) and any(
        isinstance(choice, dict) and choice.get("finish_reason") is not None
        for choice in choices
    ):
        for pending in normalizer.flush_events():
            _publish_openai_normalized(hub, request_id, pending)
        _NORMALIZERS.discard(request_id)


def _publish_native_normalized(
    hub: MonitorHub,
    request_id: str,
    value: dict[str, Any],
) -> None:
    message = value.get("message")
    if isinstance(message, dict):
        reasoning = extract_reasoning(message)
        content = text_from_content(message.get("content"))
    else:
        reasoning = extract_reasoning(value)
        content = text_from_content(value.get("response"))

    if reasoning:
        hub.publish(
            {
                "type": "reasoning_delta",
                "request_id": request_id,
                "text": reasoning,
            }
        )
    if content:
        hub.publish(
            {
                "type": "content_delta",
                "request_id": request_id,
                "text": content,
            }
        )


def publish_native_object(
    hub: MonitorHub,
    request_id: str,
    value: dict[str, Any],
) -> None:
    if value.get("done") is True:
        normalizer = _NORMALIZERS.native_normalizer(request_id)
        normalized = normalizer.normalize(value)
        _publish_native_normalized(hub, request_id, normalized)
        _NORMALIZERS.discard(request_id)
        return

    # A non-stream Ollama response may omit done in some compatible providers.
    message = value.get("message")
    has_structured_reasoning = (
        isinstance(message, dict) and bool(extract_reasoning(message))
    ) or bool(extract_reasoning(value))

    if has_structured_reasoning:
        normalized = normalize_native_object(value)
        _publish_native_normalized(hub, request_id, normalized)
        return

    normalizer = _NORMALIZERS.native_normalizer(request_id)
    normalized = normalizer.normalize(value)
    _publish_native_normalized(hub, request_id, normalized)
