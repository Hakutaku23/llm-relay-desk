from __future__ import annotations

import queue
from pathlib import Path
from typing import Any

from llm_relay_desk.desktop import window as popup_window
from llm_relay_desk.runtime import Runtime
from llm_relay_desk.settings import Settings


class FakeRoot:
    def __init__(self) -> None:
        self.after_calls: list[tuple[Any, ...]] = []

    def withdraw(self) -> None:
        pass

    def title(self, _: str) -> None:
        pass

    def after(self, *args: Any) -> str:
        self.after_calls.append(args)
        return f"after-{len(self.after_calls)}"

    def after_cancel(self, _: str) -> None:
        pass

    def mainloop(self) -> None:
        pass

    def destroy(self) -> None:
        pass


class FakePopup:
    instances = 0
    initial_configs: list[dict[str, Any]] = []

    def __init__(
        self,
        root: Any,
        event: dict[str, Any],
        config_getter: Any,
        on_destroy: Any,
        on_position_saved: Any,
    ) -> None:
        del root, on_destroy, on_position_saved
        type(self).instances += 1
        type(self).initial_configs.append(dict(config_getter()))
        self.request_id = str(event["request_id"])
        self.resets = [self.request_id]
        self.content: list[str] = []
        self.reasoning: list[str] = []
        self.completed = 0
        self.failed = 0
        self.finished = False
        self.positioning_modes: list[bool] = []

    def reset(self, event: dict[str, Any]) -> None:
        self.request_id = str(event["request_id"])
        self.resets.append(self.request_id)
        self.content.clear()
        self.reasoning.clear()
        self.finished = False

    def append_content(self, text: str) -> None:
        self.content.append(text)

    def append_reasoning(self, text: str) -> None:
        self.reasoning.append(text)

    def complete(self, _: dict[str, Any]) -> None:
        self.completed += 1
        self.finished = True

    def fail(self, _: dict[str, Any]) -> None:
        self.failed += 1
        self.finished = True

    def reschedule_if_finished(self) -> None:
        pass

    def set_positioning_mode(self, enabled: bool) -> None:
        self.positioning_modes.append(bool(enabled))

    def destroy(self, manual: bool = False) -> None:
        del manual


def test_popup_agent_reuses_one_window_and_ignores_superseded_stream(monkeypatch) -> None:
    FakePopup.instances = 0
    FakePopup.initial_configs = []
    monkeypatch.setattr(popup_window.tk, "Tk", FakeRoot)
    monkeypatch.setattr(popup_window, "SubtitleOverlay", FakePopup)

    agent = popup_window.PopupAgent(queue.Queue())
    agent._handle({"type": "request_start", "request_id": "r1", "model": "m1"})
    agent._handle({"type": "content_delta", "request_id": "r1", "text": "old"})
    popup = agent.popup
    assert popup is not None
    assert FakePopup.instances == 1
    assert popup.content == ["old"]

    # A new chat starts while the previous subtitle is still visible. The same
    # physical window is reset immediately rather than creating a second one.
    agent._handle({"type": "request_start", "request_id": "r2", "model": "m2"})
    assert agent.popup is popup
    assert FakePopup.instances == 1
    assert popup.resets[-1] == "r2"
    assert popup.content == []

    # Late chunks from the superseded stream are discarded.
    agent._handle({"type": "content_delta", "request_id": "r1", "text": "stale"})
    agent._handle({"type": "content_delta", "request_id": "r2", "text": "new"})
    assert popup.content == ["new"]



def test_latest_pending_request_wins_before_window_is_created(monkeypatch) -> None:
    FakePopup.instances = 0
    FakePopup.initial_configs = []
    monkeypatch.setattr(popup_window.tk, "Tk", FakeRoot)
    monkeypatch.setattr(popup_window, "SubtitleOverlay", FakePopup)

    agent = popup_window.PopupAgent(queue.Queue())
    agent._handle({"type": "request_start", "request_id": "r1", "model": "m1"})
    agent._handle({"type": "request_start", "request_id": "r2", "model": "m2"})
    agent._handle({"type": "content_delta", "request_id": "r1", "text": "stale"})
    assert agent.popup is None

    agent._handle({"type": "content_delta", "request_id": "r2", "text": "latest"})
    assert agent.popup is not None
    assert agent.active_request_id == "r2"
    assert agent.popup.content == ["latest"]



def test_positioning_mode_temporarily_overrides_click_through(monkeypatch) -> None:
    FakePopup.instances = 0
    FakePopup.initial_configs = []
    monkeypatch.setattr(popup_window.tk, "Tk", FakeRoot)
    monkeypatch.setattr(popup_window, "SubtitleOverlay", FakePopup)

    agent = popup_window.PopupAgent(queue.Queue())
    agent._handle({"type": "popup_interaction_mode", "mode": "positioning", "timeout_seconds": 60})
    agent._handle({"type": "request_start", "request_id": "preview", "model": "preview"})
    agent._handle({"type": "content_delta", "request_id": "preview", "text": "drag"})

    assert agent.positioning_mode is True
    assert agent.popup is not None
    assert FakePopup.initial_configs[-1]["click_through"] is False
    assert agent.popup.positioning_modes[-1] is True

    agent._save_position(222, 333)
    assert agent.positioning_mode is False
    assert agent.popup.positioning_modes[-1] is False
    assert agent.config["position"] == "custom"
    assert agent.config["custom_x"] == 222
    assert agent.config["custom_y"] == 333

def test_reasoning_delta_opens_subtitle_before_final_content(monkeypatch) -> None:
    FakePopup.instances = 0
    FakePopup.initial_configs = []
    monkeypatch.setattr(popup_window.tk, "Tk", FakeRoot)
    monkeypatch.setattr(popup_window, "SubtitleOverlay", FakePopup)

    agent = popup_window.PopupAgent(queue.Queue())
    agent._handle({"type": "request_start", "request_id": "r1", "model": "m1"})
    agent._handle({"type": "reasoning_delta", "request_id": "r1", "text": "thinking"})

    assert agent.popup is not None
    assert agent.active_request_id == "r1"
    assert agent.popup.reasoning == ["thinking"]


def make_settings(tmp_path: Path) -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "data"
    return Settings(
        host="127.0.0.1",
        port=11434,
        data_dir=data_dir,
        static_dir=project_root / "static",
        monitor_dir=project_root / "monitor",
        config_path=data_dir / "config.json",
        prompts_path=data_dir / "prompts.json",
    )


def test_dragged_position_callback_is_persisted(tmp_path: Path) -> None:
    runtime = Runtime.create(make_settings(tmp_path))
    callback = runtime.popup.on_position_saved
    assert callback is not None
    callback(-320, 145)
    config = runtime.config_store.read()
    assert config["native_popup_position"] == "custom"
    assert config["native_popup_custom_x"] == -320
    assert config["native_popup_custom_y"] == 145
    assert config["native_popup_offset_x"] == 0
    assert config["native_popup_offset_y"] == 0


def test_runtime_migrates_420_click_through_to_safe_default(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.config_path.write_text(
        '{"default_model":"m","upstream_base_url":"http://127.0.0.1:1/v1",'
        '"native_popup_click_through":true}',
        encoding="utf-8",
    )
    runtime = Runtime.create(settings)
    config = runtime.config_store.read()
    assert config["config_schema_version"] == 5
    assert config["native_popup_click_through"] is False


def test_popup_config_normalizes_transparent_background_settings() -> None:
    config = popup_window.normalize_popup_config(
        {
            "transparent_background": True,
            "text_opacity": 0.7,
            "text_shadow": False,
            "shadow_color": "#ABCDEF",
            "shadow_offset": 99,
        }
    )
    assert config["transparent_background"] is True
    assert config["background_opacity"] == 0.0
    assert config["text_opacity"] == 0.7
    assert config["text_shadow"] is False
    assert config["shadow_color"] == "#abcdef"
    assert config["shadow_offset"] == 8


def test_runtime_migrates_430_opacity_channels(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.config_path.write_text(
        '{"config_schema_version":3,"default_model":"m",'
        '"upstream_base_url":"http://127.0.0.1:1/v1",'
        '"native_popup_opacity":0.66,"native_popup_transparent_background":false}',
        encoding="utf-8",
    )
    runtime = Runtime.create(settings)
    config = runtime.config_store.read()
    assert config["config_schema_version"] == 5
    assert config["native_popup_text_opacity"] == 1.0
    assert config["native_popup_background_opacity"] == 0.66


def test_runtime_migrates_430_transparent_background_to_zero_alpha(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.config_path.write_text(
        '{"config_schema_version":3,"default_model":"m",'
        '"upstream_base_url":"http://127.0.0.1:1/v1",'
        '"native_popup_opacity":0.88,"native_popup_transparent_background":true}',
        encoding="utf-8",
    )
    runtime = Runtime.create(settings)
    config = runtime.config_store.read()
    assert config["native_popup_text_opacity"] == 1.0
    assert config["native_popup_background_opacity"] == 0.0
    assert config["native_popup_transparent_background"] is True
