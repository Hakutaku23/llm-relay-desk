from pathlib import Path

import pytest
from fastapi import HTTPException

from llm_relay_desk.config import validate_config
from llm_relay_desk.settings import CONFIG_SCHEMA_VERSION, DEFAULT_CONFIG
from llm_relay_desk.storage import JsonStore


def test_validate_config_preserves_existing_values(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "config.json", DEFAULT_CONFIG)
    result = validate_config(
        store,
        {
            "upstream_base_url": "http://127.0.0.1:11435/v1/chat/completions",
            "native_popup_position": "top_center",
            "native_popup_close_seconds": 45,
        },
    )
    assert result["upstream_base_url"] == "http://127.0.0.1:11435/v1"
    assert result["native_popup_position"] == "top_center"
    assert result["native_popup_close_seconds"] == 45
    assert result["default_model"] == DEFAULT_CONFIG["default_model"]


def test_validate_config_rejects_invalid_popup_position(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "config.json", DEFAULT_CONFIG)
    with pytest.raises(HTTPException) as exc_info:
        validate_config(store, {"native_popup_position": "somewhere"})
    assert exc_info.value.status_code == 400


def test_validate_config_accepts_custom_position_and_colors(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "config.json", DEFAULT_CONFIG)
    result = validate_config(
        store,
        {
            "native_popup_position": "custom",
            "native_popup_custom_x": -220,
            "native_popup_custom_y": 160,
            "native_popup_background_color": "#AABBCC",
            "native_popup_text_color": "#001122",
            "native_popup_click_through": False,
            "native_popup_transparent_background": True,
            "native_popup_text_shadow": True,
            "native_popup_shadow_color": "#123456",
            "native_popup_shadow_offset": 4,
        },
    )
    assert result["native_popup_position"] == "custom"
    assert result["native_popup_custom_x"] == -220
    assert result["native_popup_background_color"] == "#aabbcc"
    assert result["native_popup_click_through"] is False
    assert result["native_popup_transparent_background"] is True
    assert result["native_popup_text_shadow"] is True
    assert result["native_popup_shadow_color"] == "#123456"
    assert result["native_popup_shadow_offset"] == 4


def test_validate_config_rejects_invalid_color(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "config.json", DEFAULT_CONFIG)
    with pytest.raises(HTTPException) as exc_info:
        validate_config(store, {"native_popup_text_color": "white"})
    assert exc_info.value.status_code == 400


def test_click_through_safe_default_is_disabled() -> None:
    assert DEFAULT_CONFIG["native_popup_click_through"] is False
    assert DEFAULT_CONFIG["config_schema_version"] == CONFIG_SCHEMA_VERSION


def test_transparent_background_defaults_are_safe() -> None:
    assert DEFAULT_CONFIG["native_popup_transparent_background"] is False
    assert DEFAULT_CONFIG["native_popup_text_shadow"] is True
    assert DEFAULT_CONFIG["native_popup_shadow_color"] == "#000000"
    assert DEFAULT_CONFIG["native_popup_shadow_offset"] == 2


def test_validate_config_rejects_invalid_shadow_offset(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "config.json", DEFAULT_CONFIG)
    with pytest.raises(HTTPException) as exc_info:
        validate_config(store, {"native_popup_shadow_offset": 9})
    assert exc_info.value.status_code == 400
