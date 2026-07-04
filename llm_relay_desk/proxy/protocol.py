from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

UPSTREAM_PROTOCOL_VALUES = {"auto", "openai", "ollama"}


def configured_upstream_protocol(config: dict[str, Any]) -> str:
    value = str(config.get("upstream_protocol", "auto")).strip().lower()
    return value if value in UPSTREAM_PROTOCOL_VALUES else "auto"


def resolve_upstream_protocol(config: dict[str, Any]) -> str:
    """Resolve which upstream protocol should serve local `/api/*` routes.

    Explicit configuration always wins. The automatic mode intentionally keeps
    loopback/private Ollama deployments on native forwarding while treating
    public HTTPS APIs and `/v1` endpoints as OpenAI-compatible services.
    """

    configured = configured_upstream_protocol(config)
    if configured != "auto":
        return configured

    base = str(config.get("upstream_base_url", "")).strip()
    parsed = urlparse(base)
    hostname = (parsed.hostname or "").strip().lower()
    path = parsed.path.rstrip("/").lower()

    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return "ollama"

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None

    if address is not None and (address.is_loopback or address.is_private):
        if not path.endswith("/v1"):
            return "ollama"

    if path.endswith("/v1"):
        return "openai"
    if parsed.scheme.lower() == "https":
        return "openai"
    if parsed.port in {11434, 11435}:
        return "ollama"
    return "openai"
