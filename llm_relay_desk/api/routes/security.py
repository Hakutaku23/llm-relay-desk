from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response

from llm_relay_desk.api.dependencies import runtime_from_request
from llm_relay_desk.config import validate_config
from llm_relay_desk.prompts import bind_relay_request_context
from llm_relay_desk.proxy.openai import chat_completions
from llm_relay_desk.security import SecretStoreError

router = APIRouter(prefix="/admin", tags=["admin-security"])
_ALLOWED_SECRET_NAMES = {"upstream_api_key", "local_api_key"}


def _store(request: Request):
    store = runtime_from_request(request).config_store
    required = ("public_view", "secret_status", "clear_secret", "reveal_secret")
    if not all(hasattr(store, name) for name in required):
        raise HTTPException(status_code=500, detail="安全配置存储未初始化")
    return store


def _is_loopback(request: Request) -> bool:
    if request.client is None:
        return False
    host = str(request.client.host or "").strip()
    if host in {"localhost", "testclient"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@router.get("/config")
async def get_secure_config(request: Request) -> dict[str, Any]:
    return _store(request).public_view()


@router.put("/config")
async def put_secure_config(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    store = _store(request)
    try:
        updated = validate_config(store, payload)
        store.write(updated)
    except SecretStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    effective = store.read()
    runtime.popup.configure(effective)
    return {"ok": True, "config": store.public_view()}


@router.get("/secrets/status")
async def secret_status(request: Request) -> dict[str, Any]:
    return _store(request).secret_status()


@router.delete("/secrets/{secret_name}")
async def clear_secret(request: Request, secret_name: str) -> dict[str, Any]:
    if secret_name not in _ALLOWED_SECRET_NAMES:
        raise HTTPException(status_code=404, detail="未知密钥名称")
    store = _store(request)
    try:
        store.clear_secret(secret_name)
    except SecretStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "status": store.secret_status()}


@router.post("/secrets/local_api_key/reveal")
async def reveal_local_api_key(request: Request) -> dict[str, Any]:
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="仅允许在本机管理界面显示本地 API Key")
    value = _store(request).reveal_secret("local_api_key")
    if not value:
        raise HTTPException(status_code=404, detail="本地 API Key 尚未配置")
    return {"value": value}


@router.post("/test-chat")
async def admin_test_chat(request: Request) -> Response:
    runtime = runtime_from_request(request)
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    body = payload if isinstance(payload, dict) else None
    with bind_relay_request_context(
        payload=body,
        headers=request.headers,
        endpoint="/v1/chat/completions",
    ):
        return await chat_completions(runtime, request)
