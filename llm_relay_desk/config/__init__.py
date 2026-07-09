from __future__ import annotations

from typing import Any

from .validation import (
    POPUP_POSITIONS,
    normalize_upstream_base_url,
    validate_config as _validate_config,
)

VLLM_PROTOCOL = "vllm"


def normalize_vllm_base_url(value: str) -> str:
    """Normalize a vLLM OpenAI-compatible base URL to end in ``/v1``."""

    normalized = normalize_upstream_base_url(value)
    if not normalized.lower().endswith("/v1"):
        normalized = f"{normalized.rstrip('/')}/v1"
    return normalized


def validate_config(store: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Extend the legacy validator with an explicit ``vllm`` protocol.

    The existing validation module only accepts auto/openai/ollama.  vLLM uses
    OpenAI-compatible HTTP routes, so validation is delegated as ``openai`` and
    the explicit ``vllm`` value is restored afterwards.  This wrapper also runs
    when unrelated settings are saved while the current protocol is vLLM.
    """

    current = store.read()
    requested_protocol = str(
        payload.get("upstream_protocol", current.get("upstream_protocol", "auto"))
    ).strip().lower()

    if requested_protocol != VLLM_PROTOCOL:
        return _validate_config(store, payload)

    adapted = dict(payload)
    adapted["upstream_protocol"] = "openai"
    adapted["upstream_base_url"] = normalize_vllm_base_url(
        str(
            payload.get(
                "upstream_base_url",
                current.get("upstream_base_url", "http://127.0.0.1:8000/v1"),
            )
        )
    )
    updated = _validate_config(store, adapted)
    updated["upstream_protocol"] = VLLM_PROTOCOL
    return updated


__all__ = [
    "POPUP_POSITIONS",
    "VLLM_PROTOCOL",
    "normalize_upstream_base_url",
    "normalize_vllm_base_url",
    "validate_config",
]
