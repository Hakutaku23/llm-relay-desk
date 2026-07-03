from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from llm_relay_desk.api.dependencies import runtime_from_request
from llm_relay_desk.settings import APP_TITLE, APP_VERSION

router = APIRouter()


@router.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    config = runtime.config_store.read()
    active, prompt = runtime.prompts.get_active()
    settings = runtime.settings
    return {
        "service": APP_TITLE,
        "version": APP_VERSION,
        "status": "ok",
        "listen": f"http://{settings.host}:{settings.port}",
        "openai_base_url": f"http://{settings.host}:{settings.port}/v1",
        "monitor_url": f"http://{settings.host}:{settings.port}/monitor/",
        "upstream": config.get("upstream_base_url"),
        "model": config.get("default_model"),
        "prompt_enabled": config.get("prompt_enabled"),
        "active_prompt": active,
        "active_prompt_length": len(prompt),
        "monitor_history_count": len(runtime.monitor.records),
        "monitor_clients": len(runtime.monitor.subscribers),
        "native_popup_enabled": config.get("native_popup_enabled", True),
        "native_popup_close_seconds": config.get(
            "native_popup_close_seconds", 30
        ),
        "native_popup_position": config.get(
            "native_popup_position", "bottom_center"
        ),
        "native_popup_offset_x": config.get("native_popup_offset_x", 0),
        "native_popup_offset_y": config.get("native_popup_offset_y", 0),
        "native_popup_custom_x": config.get("native_popup_custom_x", 120),
        "native_popup_custom_y": config.get("native_popup_custom_y", 120),
        "native_popup_font_family": config.get("native_popup_font_family", "Microsoft YaHei UI"),
        "native_popup_text_align": config.get("native_popup_text_align", "left"),
        "native_popup_click_through": config.get(
            "native_popup_click_through", False
        ),
        "native_popup_text_opacity": config.get("native_popup_text_opacity", 1.0),
        "native_popup_background_opacity": config.get(
            "native_popup_background_opacity",
            0.0 if config.get("native_popup_transparent_background", False) else 0.88,
        ),
        "native_popup_transparent_background": config.get(
            "native_popup_background_opacity",
            0.0 if config.get("native_popup_transparent_background", False) else 0.88,
        ) <= 0.001,
        "native_popup_worker_alive": runtime.popup.is_alive(),
    }
