from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

APP_VERSION = "4.4.0"
APP_TITLE = "LLM Relay Desk"
APP_DESCRIPTION = "本地 LLM API 转发、提示词管理、Web 监视器与原生字幕浮层"

CONFIG_SCHEMA_VERSION = 4

DEFAULT_CONFIG: dict[str, Any] = {
    "config_schema_version": CONFIG_SCHEMA_VERSION,
    "upstream_base_url": "http://127.0.0.1:11435/v1",
    "upstream_api_key": "ollama",
    "local_api_key": "sk-local-ollama-change-me",
    "default_model": "qwen3.6:35b",
    "default_reasoning_effort": "",
    "request_timeout_seconds": 600,
    "prompt_enabled": True,
    "native_popup_enabled": True,
    "native_popup_close_seconds": 30,
    "native_popup_position": "bottom_center",
    "native_popup_offset_x": 0,
    "native_popup_offset_y": 0,
    "native_popup_custom_x": 120,
    "native_popup_custom_y": 120,
    "native_popup_width": 960,
    "native_popup_height": 220,
    "native_popup_font_size": 24,
    "native_popup_opacity": 0.88,  # legacy combined opacity
    "native_popup_text_opacity": 1.0,
    "native_popup_background_opacity": 0.88,
    "native_popup_show_reasoning": False,
    "native_popup_click_through": False,
    "native_popup_transparent_background": False,
    "native_popup_text_shadow": True,
    "native_popup_shadow_color": "#000000",
    "native_popup_shadow_offset": 2,
    "native_popup_background_color": "#101318",
    "native_popup_text_color": "#f7f8fa",
    "native_popup_muted_color": "#aeb6c2",
    "native_popup_border_color": "#343a46",
    "native_popup_error_color": "#ff8f9b",
}

DEFAULT_PROMPTS: dict[str, Any] = {
    "active": "默认中文助手",
    "profiles": {
        "默认中文助手": (
            "你是一个本地部署的中文助手。\n\n"
            "要求：\n"
            "1. 优先准确回答问题，不编造事实。\n"
            "2. 对不确定的信息明确说明不确定性。\n"
            "3. 默认使用简体中文。\n"
            "4. 输出结构清晰，避免无关展开。\n"
            "5. 涉及命令、配置或代码时，给出可直接执行的完整示例。"
        ),
        "提示词测试": (
            "当用户询问“提示词测试码是什么”时，"
            "只回复：prompt_test_001"
        ),
    },
}


@dataclass(frozen=True, slots=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    static_dir: Path
    monitor_dir: Path
    config_path: Path
    prompts_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(
            os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))
        ).expanduser().resolve()
        return cls(
            host=os.getenv("APP_HOST", "127.0.0.1"),
            port=int(os.getenv("APP_PORT", "11434")),
            data_dir=data_dir,
            static_dir=PROJECT_ROOT / "static",
            monitor_dir=PROJECT_ROOT / "monitor",
            config_path=data_dir / "config.json",
            prompts_path=data_dir / "prompts.json",
        )
