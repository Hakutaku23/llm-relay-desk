from pathlib import Path

import pytest
from fastapi import HTTPException

from llm_relay_desk.config import validate_config
from llm_relay_desk.settings import DEFAULT_CONFIG
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
