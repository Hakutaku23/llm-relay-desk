from __future__ import annotations

from dataclasses import dataclass

from llm_relay_desk.desktop import NativePopupController
from llm_relay_desk.monitoring import MonitorHub
from llm_relay_desk.prompts import PromptService
from llm_relay_desk.settings import (
    CONFIG_SCHEMA_VERSION,
    DEFAULT_CONFIG,
    DEFAULT_PROMPTS,
    Settings,
)
from llm_relay_desk.storage import JsonStore


@dataclass(slots=True)
class Runtime:
    settings: Settings
    config_store: JsonStore
    prompt_store: JsonStore
    prompts: PromptService
    popup: NativePopupController
    monitor: MonitorHub

    @classmethod
    def create(cls, settings: Settings) -> "Runtime":
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        config_store = JsonStore(settings.config_path, DEFAULT_CONFIG)
        prompt_store = JsonStore(settings.prompts_path, DEFAULT_PROMPTS)

        existing_config = config_store.read()
        try:
            schema_version = int(existing_config.get("config_schema_version", 1))
        except (TypeError, ValueError):
            schema_version = 1

        merged_config = {**DEFAULT_CONFIG, **existing_config}
        if schema_version < 2:
            # 4.2.0 enabled pass-through by default and applied the native style
            # before the Tk window completed its first paint. Reset it once so
            # upgrades always recover a visible, interactive subtitle surface.
            merged_config["native_popup_click_through"] = False
        if schema_version < 4:
            # Split the old whole-window opacity into independent channels. Text
            # starts fully opaque; the old alpha becomes the background alpha.
            try:
                legacy_opacity = float(existing_config.get("native_popup_opacity", 0.88))
            except (TypeError, ValueError):
                legacy_opacity = 0.88
            legacy_opacity = max(0.0, min(1.0, legacy_opacity))
            if bool(existing_config.get("native_popup_transparent_background", False)):
                legacy_opacity = 0.0
            merged_config["native_popup_text_opacity"] = 1.0
            merged_config["native_popup_background_opacity"] = legacy_opacity
            merged_config["native_popup_transparent_background"] = legacy_opacity <= 0.001
        merged_config["config_schema_version"] = CONFIG_SCHEMA_VERSION
        if merged_config != existing_config:
            config_store.write(merged_config)

        def save_popup_position(x: int, y: int) -> None:
            config_store.update(
                {
                    "native_popup_position": "custom",
                    "native_popup_custom_x": int(x),
                    "native_popup_custom_y": int(y),
                    "native_popup_offset_x": 0,
                    "native_popup_offset_y": 0,
                }
            )

        popup = NativePopupController(on_position_saved=save_popup_position)
        monitor = MonitorHub(sinks=[popup.publish])
        return cls(
            settings=settings,
            config_store=config_store,
            prompt_store=prompt_store,
            prompts=PromptService(prompt_store),
            popup=popup,
            monitor=monitor,
        )
