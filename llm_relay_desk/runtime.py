from __future__ import annotations

from dataclasses import dataclass

from llm_relay_desk.desktop import NativePopupController
from llm_relay_desk.monitoring import MonitorHub
from llm_relay_desk.prompts import PromptService
from llm_relay_desk.settings import DEFAULT_CONFIG, DEFAULT_PROMPTS, Settings
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
        if any(key not in existing_config for key in DEFAULT_CONFIG):
            config_store.write({**DEFAULT_CONFIG, **existing_config})

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
