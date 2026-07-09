from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

UPSTREAM_PROTOCOL_VALUES = {"auto", "openai", "ollama", "vllm"}


def configured_upstream_protocol(config: dict[str, Any]) -> str:
    value = str(config.get("upstream_protocol", "auto")).strip().lower()
    return value if value in UPSTREAM_PROTOCOL_VALUES else "auto"


def resolve_upstream_protocol(config: dict[str, Any]) -> str:
    """Resolve the transport used by local ``/api/*`` compatibility routes.

    vLLM exposes OpenAI-compatible endpoints.  The explicit ``vllm`` setting is
    therefore routed through the existing OpenAI adapter while remaining a
    distinct saved configuration value in the management UI.
    """

    configured = configured_upstream_protocol(config)
    if configured == "vllm":
        return "openai"
    if configured != "auto":
        return configured

    base = str(config.get("upstream_base_url", "")).strip()
    parsed = urlparse(base)
    hostname = (parsed.hostname or "").strip().lower()
    path = parsed.path.rstrip("/").lower()

    # A /v1 base is an explicit OpenAI-compatible signal, including local vLLM
    # servers such as http://127.0.0.1:8000/v1.
    if path.endswith("/v1"):
        return "openai"

    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return "ollama"

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None

    if address is not None and (address.is_loopback or address.is_private):
        return "ollama"

    if parsed.scheme.lower() == "https":
        return "openai"
    if parsed.port in {11434, 11435}:
        return "ollama"
    return "openai"
