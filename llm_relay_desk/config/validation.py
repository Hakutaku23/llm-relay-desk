from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from llm_relay_desk.storage import JsonStore


TEXT_ALIGN_VALUES = {"left", "center", "right"}
FONT_FAMILY_MAX_LENGTH = 120
UPSTREAM_PROTOCOL_VALUES = {"auto", "openai", "ollama"}
SUBTITLE_CONTENT_MODE_VALUES = {"dialogue", "all"}
DIALOGUE_FIELD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")

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




def _bounded_float(
    updated: dict[str, Any],
    key: str,
    default: float,
    minimum: float,
    maximum: float,
    label: str,
) -> float:
    try:
        value = float(updated.get(key, default))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{label}必须为数字") from exc
    if value < minimum or value > maximum:
        raise HTTPException(
            status_code=400,
            detail=f"{label}范围为 {minimum:.2f}～{maximum:.2f}",
        )
    return round(value, 2)

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
    protocol = str(updated.get("upstream_protocol", "auto")).strip().lower()
    if protocol not in UPSTREAM_PROTOCOL_VALUES:
        raise HTTPException(status_code=400, detail="上游协议必须为 auto/openai/ollama")
    updated["upstream_protocol"] = protocol

    updated["upstream_api_key"] = str(
        updated.get("upstream_api_key", "ollama")
    ).strip()
    updated["local_api_key"] = str(updated.get("local_api_key", "")).strip()
    updated["default_model"] = str(updated.get("default_model", "")).strip()
    updated["force_reasoning_enabled"] = bool(
        updated.get("force_reasoning_enabled", False)
    )

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

    font_family = str(
        updated.get("native_popup_font_family", "Microsoft YaHei UI")
    ).strip()
    if not font_family:
        font_family = "Microsoft YaHei UI"
    if len(font_family) > FONT_FAMILY_MAX_LENGTH or any(
        ord(char) < 32 for char in font_family
    ):
        raise HTTPException(status_code=400, detail="字幕字体名称无效")
    updated["native_popup_font_family"] = font_family

    text_align = str(updated.get("native_popup_text_align", "left")).strip().lower()
    if text_align not in TEXT_ALIGN_VALUES:
        raise HTTPException(status_code=400, detail="字幕文字对齐方式无效")
    updated["native_popup_text_align"] = text_align

    legacy_opacity = _bounded_float(
        updated,
        "native_popup_opacity",
        0.88,
        0.0,
        1.0,
        "旧版字幕透明度",
    )
    updated["native_popup_text_opacity"] = _bounded_float(
        updated,
        "native_popup_text_opacity",
        1.0,
        0.10,
        1.0,
        "文字透明度",
    )
    if "native_popup_background_opacity" in payload:
        background_opacity = _bounded_float(
            updated,
            "native_popup_background_opacity",
            legacy_opacity,
            0.0,
            1.0,
            "背景透明度",
        )
    elif payload.get("native_popup_transparent_background") is True:
        background_opacity = 0.0
    else:
        background_opacity = _bounded_float(
            updated,
            "native_popup_background_opacity",
            0.0
            if bool(updated.get("native_popup_transparent_background", False))
            else legacy_opacity,
            0.0,
            1.0,
            "背景透明度",
        )
    updated["native_popup_background_opacity"] = background_opacity
    # Keep the legacy keys synchronized for older clients.
    updated["native_popup_opacity"] = background_opacity
    updated["native_popup_transparent_background"] = background_opacity <= 0.001
    content_mode = str(
        updated.get("native_popup_content_mode", "dialogue")
    ).strip().lower()
    if content_mode not in SUBTITLE_CONTENT_MODE_VALUES:
        raise HTTPException(status_code=400, detail="字幕内容模式必须为 dialogue/all")
    updated["native_popup_content_mode"] = content_mode

    fields_value = updated.get(
        "native_popup_dialogue_fields",
        ["response", "statement", "dialogue", "speech"],
    )
    if isinstance(fields_value, str):
        raw_fields = fields_value.split(",")
    elif isinstance(fields_value, list):
        raw_fields = fields_value
    else:
        raise HTTPException(status_code=400, detail="字幕对话字段必须为列表或逗号分隔文本")
    dialogue_fields: list[str] = []
    for item in raw_fields:
        field_name = str(item).strip()
        if not field_name:
            continue
        if not DIALOGUE_FIELD_PATTERN.fullmatch(field_name):
            raise HTTPException(status_code=400, detail=f"字幕对话字段无效：{field_name}")
        if field_name not in dialogue_fields:
            dialogue_fields.append(field_name)
    if not dialogue_fields or len(dialogue_fields) > 16:
        raise HTTPException(status_code=400, detail="字幕对话字段数量范围为 1～16")
    updated["native_popup_dialogue_fields"] = dialogue_fields
    updated["native_popup_plain_text_fallback"] = bool(
        updated.get("native_popup_plain_text_fallback", True)
    )
    updated["native_popup_force_upstream_stream"] = bool(
        updated.get("native_popup_force_upstream_stream", True)
    )

    updated["native_popup_show_reasoning"] = bool(
        updated.get("native_popup_show_reasoning", False)
    )
    updated["native_popup_click_through"] = bool(
        updated.get("native_popup_click_through", False)
    )
    updated["native_popup_text_shadow"] = bool(
        updated.get("native_popup_text_shadow", True)
    )
    updated["native_popup_shadow_offset"] = _bounded_int(
        updated, "native_popup_shadow_offset", 2, 1, 8, "字幕阴影偏移"
    )
    updated["native_popup_text_outline"] = bool(
        updated.get("native_popup_text_outline", False)
    )
    updated["native_popup_outline_width"] = _bounded_int(
        updated, "native_popup_outline_width", 0, 0, 8, "字幕描边宽度"
    )
    updated["native_popup_outline_color"] = _hex_color(
        updated, "native_popup_outline_color", "#000000", "字幕描边颜色"
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
