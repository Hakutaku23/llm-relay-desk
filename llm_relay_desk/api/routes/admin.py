from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from llm_relay_desk.api.dependencies import runtime_from_request
from llm_relay_desk.config import validate_config
from llm_relay_desk.monitoring import utc_now_iso
from llm_relay_desk.proxy.common import timeout_config, upstream_headers

router = APIRouter(prefix="/admin", tags=["admin"])

SUBTITLE_CONFIG_KEYS = {
    "native_popup_enabled",
    "native_popup_close_seconds",
    "native_popup_position",
    "native_popup_offset_x",
    "native_popup_offset_y",
    "native_popup_custom_x",
    "native_popup_custom_y",
    "native_popup_width",
    "native_popup_height",
    "native_popup_font_size",
    "native_popup_opacity",
    "native_popup_show_reasoning",
    "native_popup_background_color",
    "native_popup_text_color",
    "native_popup_muted_color",
    "native_popup_border_color",
    "native_popup_error_color",
}


def _subtitle_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: config.get(key) for key in SUBTITLE_CONFIG_KEYS}


@router.delete("/monitor/history")
async def clear_monitor_history(request: Request) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    runtime.monitor.clear()
    return {"ok": True}


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    return runtime_from_request(request).config_store.read()


@router.put("/config")
async def put_config(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    updated = validate_config(runtime.config_store, payload)
    runtime.config_store.write(updated)
    runtime.popup.configure(updated)
    return {"ok": True, "config": updated}


@router.get("/subtitle-config")
async def get_subtitle_config(request: Request) -> dict[str, Any]:
    return _subtitle_config(runtime_from_request(request).config_store.read())


@router.put("/subtitle-config")
async def put_subtitle_config(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    filtered = {
        key: value
        for key, value in payload.items()
        if key in SUBTITLE_CONFIG_KEYS
    }
    updated = validate_config(runtime.config_store, filtered)
    runtime.config_store.write(updated)
    runtime.popup.configure(updated)
    return {"ok": True, "config": _subtitle_config(updated)}


@router.post("/native-popup/preview")
async def preview_native_popup(request: Request) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    config = runtime.config_store.read()
    runtime.popup.configure(config)
    if not config.get("native_popup_enabled", True):
        raise HTTPException(
            status_code=409,
            detail="请先开启原生字幕浮层并保存配置",
        )

    request_id = f"preview_{uuid.uuid4().hex[:12]}"

    async def emit_preview() -> None:
        runtime.popup.publish(
            {
                "type": "request_start",
                "request_id": request_id,
                "api": "preview",
                "route": "/admin/native-popup/preview",
                "model": "字幕位置预览",
                "source": "管理界面",
                "user_agent": "LLM Relay Desk",
                "stream": True,
                "started_at": utc_now_iso(),
            }
        )
        for text in ("这是一个", "固定位置的", "流式字幕预览。"):
            await asyncio.sleep(0.18)
            runtime.popup.publish(
                {
                    "type": "content_delta",
                    "request_id": request_id,
                    "text": text,
                }
            )
        runtime.popup.publish(
            {
                "type": "request_done",
                "request_id": request_id,
                "finished_at": utc_now_iso(),
                "elapsed_ms": 540,
                "status_code": 200,
            }
        )

    asyncio.create_task(emit_preview())
    return {"ok": True, "request_id": request_id}


@router.get("/prompts")
async def get_prompts(request: Request) -> dict[str, Any]:
    return runtime_from_request(request).prompts.list_profiles()


@router.put("/prompts/{profile_name}")
async def save_prompt(
    request: Request,
    profile_name: str,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    return runtime_from_request(request).prompts.save(
        profile_name,
        str(payload.get("content", "")),
    )


@router.post("/prompts/{profile_name}/activate")
async def activate_prompt(request: Request, profile_name: str) -> dict[str, Any]:
    return runtime_from_request(request).prompts.activate(profile_name)


@router.delete("/prompts/{profile_name}")
async def delete_prompt(request: Request, profile_name: str) -> dict[str, Any]:
    return runtime_from_request(request).prompts.delete(profile_name)


@router.post("/test-upstream")
async def test_upstream(request: Request) -> JSONResponse:
    runtime = runtime_from_request(request)
    config = runtime.config_store.read()
    url = f"{config['upstream_base_url']}/models"
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=timeout_config(config),
            trust_env=False,
        ) as client:
            response = await client.get(url, headers=upstream_headers(config))
    except httpx.RequestError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "ok": False,
                "message": str(exc),
                "upstream": url,
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            },
        )

    try:
        upstream_body: Any = response.json()
    except ValueError:
        upstream_body = response.text[:500]

    return JSONResponse(
        status_code=200 if response.is_success else 502,
        content={
            "ok": response.is_success,
            "upstream": url,
            "upstream_status": response.status_code,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "response": upstream_body,
        },
    )
