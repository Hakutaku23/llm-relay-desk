from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .protocol import configured_upstream_protocol

_REASONING_KEYS = {"think", "thinking", "reasoning_effort"}
_REASONING_EFFORTS = {"low", "medium", "high", "max", "xhigh"}


def caller_has_reasoning_preference(payload: dict[str, Any] | None) -> bool:
    """Return whether the caller explicitly selected or disabled reasoning.

    Presence matters more than truthiness: ``think: false`` and
    ``reasoning_effort: none`` are explicit choices and must not be overridden.
    Some OpenAI clients place provider-specific fields under ``extra_body``;
    inspect that object as well.
    """

    if not isinstance(payload, dict):
        return False
    if any(key in payload for key in _REASONING_KEYS):
        return True
    extra_body = payload.get("extra_body")
    return isinstance(extra_body, dict) and any(
        key in extra_body for key in _REASONING_KEYS
    )


def configured_reasoning_effort(config: dict[str, Any]) -> str:
    value = str(config.get("default_reasoning_effort", "")).strip().lower()
    if value in _REASONING_EFFORTS:
        return value
    return ""


def force_reasoning_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("force_reasoning_enabled", False))


def _is_deepseek_upstream(config: dict[str, Any]) -> bool:
    base = str(config.get("upstream_base_url", "")).strip()
    hostname = (urlparse(base).hostname or "").lower()
    return "deepseek" in hostname


def _apply_vllm_decode_controls(
    payload: dict[str, Any],
    config: dict[str, Any],
) -> None:
    """Keep Qwen reasoning boundary tokens available to the local normalizer.

    vLLM normally strips special tokens before returning ``content``. Qwen chat
    templates may place the opening thinking token in the prompt, so without
    the generated closing/final token the proxy cannot reliably recover the
    boundary. These fields are vLLM-specific and are only sent when the user
    explicitly selected the vLLM protocol.
    """

    if configured_upstream_protocol(config) != "vllm":
        return
    payload["skip_special_tokens"] = False
    payload.setdefault("spaces_between_special_tokens", False)


def apply_openai_reasoning_default(
    payload: dict[str, Any],
    config: dict[str, Any],
    *,
    caller_payload: dict[str, Any] | None = None,
) -> bool:
    """Inject an OpenAI-compatible reasoning request when the caller omitted it.

    DeepSeek-style endpoints receive ``thinking: {type: enabled}``; generic
    OpenAI-compatible endpoints receive ``reasoning_effort``. When an effort is
    selected for DeepSeek, it is sent alongside ``thinking`` because recent
    compatible servers may use it to tune the reasoning budget.
    """

    _apply_vllm_decode_controls(payload, config)

    source = caller_payload if caller_payload is not None else payload
    if not force_reasoning_enabled(config) or caller_has_reasoning_preference(source):
        return False

    effort = configured_reasoning_effort(config)
    if _is_deepseek_upstream(config):
        payload["thinking"] = {"type": "enabled"}
        if effort:
            payload["reasoning_effort"] = effort
    else:
        payload["reasoning_effort"] = effort or "medium"
    return True


def apply_ollama_reasoning_default(
    payload: dict[str, Any],
    config: dict[str, Any],
) -> bool:
    """Normalize explicit reasoning controls or inject Ollama's ``think`` option.

    ``/api/chat`` callers normally use ``think``. For clients that send the
    OpenAI-style fields anyway, translate them instead of forwarding unknown
    keys to Ollama. Explicit disable remains authoritative.
    """

    if "think" in payload:
        return False

    if "reasoning_effort" in payload:
        raw_effort = str(payload.pop("reasoning_effort") or "").strip().lower()
        payload.pop("thinking", None)
        payload["think"] = False if raw_effort in {"", "none", "disabled"} else raw_effort
        return True

    if "thinking" in payload:
        thinking = payload.pop("thinking")
        if isinstance(thinking, dict):
            mode = str(thinking.get("type", "enabled")).strip().lower()
            payload["think"] = mode not in {"disabled", "none", "false"}
        else:
            payload["think"] = bool(thinking)
        return True

    if not force_reasoning_enabled(config):
        return False
    effort = configured_reasoning_effort(config)
    payload["think"] = effort or True
    return True
