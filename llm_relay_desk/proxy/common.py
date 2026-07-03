from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import HTTPException

from llm_relay_desk.runtime import Runtime


def verify_local_api_key(runtime: Runtime, authorization: str | None) -> None:
    local_api_key = str(
        runtime.config_store.read().get("local_api_key", "")
    ).strip()
    if not local_api_key:
        return
    if authorization != f"Bearer {local_api_key}":
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


def upstream_headers(config: dict[str, Any]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.get('upstream_api_key', 'ollama')}",
        "Content-Type": "application/json",
    }


def timeout_config(config: dict[str, Any]) -> httpx.Timeout:
    seconds = int(config.get("request_timeout_seconds", 600))
    return httpx.Timeout(
        connect=min(30.0, float(seconds)),
        read=float(seconds),
        write=min(120.0, float(seconds)),
        pool=30.0,
    )


def native_upstream_root(config: dict[str, Any]) -> str:
    base = str(config.get("upstream_base_url", "")).strip().rstrip("/")
    if base.lower().endswith("/v1"):
        base = base[:-3].rstrip("/")
    return base


def error_from_body(body: bytes) -> str:
    if not body:
        return "上游返回空错误响应"
    try:
        value = json.loads(body)
        if isinstance(value, dict):
            error = value.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error)[:1200]
            return str(
                value.get("message") or value.get("detail") or value
            )[:1200]
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    return body.decode("utf-8", errors="replace")[:1200]
