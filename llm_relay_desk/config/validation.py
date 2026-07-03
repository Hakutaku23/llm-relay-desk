from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from llm_relay_desk.storage import JsonStore

POPUP_POSITIONS = {
    "top_left",
    "top_center",
    "top_right",
    "center_left",
    "center",
    "center_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
    "custom",
}


def normalize_upstream_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    for suffix in ("/chat/completions", "/models"):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        raise HTTPException(
            status_code=400,
            detail="上游地址必须以 http:// 或 https:// 开头",
        )
    return url


def _bounded_int(
    updated: dict[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    try:
        value = int(updated.get(key, default))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{label}必须为整数") from exc
    if value < minimum or value > maximum:
        raise HTTPException(
            status_code=400,
            detail=f"{label}范围为 {minimum}～{maximum}",
        )
    return value


def _hex_color(updated: dict[str, Any], key: str, default: str, label: str) -> str:
    value = str(updated.get(key, default)).strip().lower()
    if not re.fullmatch(r"#[0-9a-f]{6}", value):
        raise HTTPException(status_code=400, detail=f"{label}必须为 #RRGGBB 格式")
    return value


def validate_config(store: JsonStore, payload: dict[str, Any]) -> dict[str, Any]:
    current = store.read()
    updated = {**current, **payload}

    updated["upstream_base_url"] = normalize_upstream_base_url(
        str(updated.get("upstream_base_url", ""))
    )
    updated["upstream_api_key"] = str(
        updated.get("upstream_api_key", "ollama")
    ).strip()
    updated["local_api_key"] = str(updated.get("local_api_key", "")).strip()
    updated["default_model"] = str(updated.get("default_model", "")).strip()

    reasoning = str(updated.get("default_reasoning_effort", "")).strip().lower()
    if reasoning not in {"", "none", "low", "medium", "high", "max"}:
        raise HTTPException(
            status_code=400,
            detail="默认思考强度必须为 none/low/medium/high/max 或留空",
        )
    updated["default_reasoning_effort"] = reasoning

    updated["request_timeout_seconds"] = _bounded_int(
        updated,
        "request_timeout_seconds",
        600,
        30,
        7200,
        "超时时间",
    )
    updated["prompt_enabled"] = bool(updated.get("prompt_enabled", True))
    updated["native_popup_enabled"] = bool(
        updated.get("native_popup_enabled", True)
    )
    updated["native_popup_close_seconds"] = _bounded_int(
        updated,
        "native_popup_close_seconds",
        30,
        1,
        3600,
        "弹窗自动关闭时间",
    )

    position = str(
        updated.get("native_popup_position", "bottom_center")
    ).strip()
    if position not in POPUP_POSITIONS:
        raise HTTPException(status_code=400, detail="字幕位置参数无效")
    updated["native_popup_position"] = position

    updated["native_popup_offset_x"] = _bounded_int(
        updated, "native_popup_offset_x", 0, -10000, 10000, "字幕水平偏移"
    )
    updated["native_popup_offset_y"] = _bounded_int(
        updated, "native_popup_offset_y", 0, -10000, 10000, "字幕垂直偏移"
    )
    updated["native_popup_custom_x"] = _bounded_int(
        updated, "native_popup_custom_x", 120, -10000, 10000, "字幕自定义 X 坐标"
    )
    updated["native_popup_custom_y"] = _bounded_int(
        updated, "native_popup_custom_y", 120, -10000, 10000, "字幕自定义 Y 坐标"
    )
    updated["native_popup_width"] = _bounded_int(
        updated, "native_popup_width", 960, 320, 2400, "字幕宽度"
    )
    updated["native_popup_height"] = _bounded_int(
        updated, "native_popup_height", 220, 100, 900, "字幕高度"
    )
    updated["native_popup_font_size"] = _bounded_int(
        updated, "native_popup_font_size", 24, 12, 72, "字幕字号"
    )

    try:
        opacity = float(updated.get("native_popup_opacity", 0.88))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="字幕透明度必须为数字") from exc
    if opacity < 0.30 or opacity > 1.0:
        raise HTTPException(status_code=400, detail="字幕透明度范围为 0.30～1.00")
    updated["native_popup_opacity"] = round(opacity, 2)
    updated["native_popup_show_reasoning"] = bool(
        updated.get("native_popup_show_reasoning", False)
    )
    updated["native_popup_click_through"] = bool(
        updated.get("native_popup_click_through", False)
    )
    updated["native_popup_transparent_background"] = bool(
        updated.get("native_popup_transparent_background", False)
    )
    updated["native_popup_text_shadow"] = bool(
        updated.get("native_popup_text_shadow", True)
    )
    updated["native_popup_shadow_offset"] = _bounded_int(
        updated, "native_popup_shadow_offset", 2, 1, 8, "字幕阴影偏移"
    )
    updated["native_popup_shadow_color"] = _hex_color(
        updated, "native_popup_shadow_color", "#000000", "字幕阴影颜色"
    )
    updated["native_popup_background_color"] = _hex_color(
        updated, "native_popup_background_color", "#101318", "字幕背景颜色"
    )
    updated["native_popup_text_color"] = _hex_color(
        updated, "native_popup_text_color", "#f7f8fa", "字幕正文颜色"
    )
    updated["native_popup_muted_color"] = _hex_color(
        updated, "native_popup_muted_color", "#aeb6c2", "字幕辅助文字颜色"
    )
    updated["native_popup_border_color"] = _hex_color(
        updated, "native_popup_border_color", "#343a46", "字幕边框颜色"
    )
    updated["native_popup_error_color"] = _hex_color(
        updated, "native_popup_error_color", "#ff8f9b", "字幕错误颜色"
    )

    if not updated["default_model"]:
        raise HTTPException(status_code=400, detail="默认模型不能为空")

    return updated
