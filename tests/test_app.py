from pathlib import Path

from fastapi.testclient import TestClient

from llm_relay_desk.application import create_app
from llm_relay_desk.settings import Settings


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


def test_health_and_static_routes(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    config = app.state.runtime.config_store.read()
    config["native_popup_enabled"] = False
    app.state.runtime.config_store.write(config)

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["version"] == "4.3.0"
        ui = client.get("/ui/")
        assert ui.status_code == 200
        assert "data-tab=\"subtitle\"" in ui.text
        assert "nativePopupBackgroundColor" in ui.text
        assert "nativePopupClickThrough" in ui.text
        assert "nativePopupTransparentBackground" in ui.text
        assert "nativePopupTextShadow" in ui.text
        config_section = ui.text.split('id="tab-config"', 1)[1].split('id="tab-subtitle"', 1)[0]
        assert "nativePopupEnabled" not in config_section
        assert client.get("/monitor/").status_code == 200


def test_route_contract_is_preserved(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    route_keys = {
        (route.path, method)
        for route in app.routes
        for method in (getattr(route, "methods", None) or {"WEBSOCKET"})
    }
    expected = {
        ("/health", "GET"),
        ("/ws/monitor", "WEBSOCKET"),
        ("/admin/config", "GET"),
        ("/admin/config", "PUT"),
        ("/admin/subtitle-config", "GET"),
        ("/admin/subtitle-config", "PUT"),
        ("/admin/subtitle-positioning/start", "POST"),
        ("/admin/subtitle-positioning/finish", "POST"),
        ("/admin/prompts", "GET"),
        ("/api/chat", "POST"),
        ("/api/generate", "POST"),
        ("/v1/models", "GET"),
        ("/v1/chat/completions", "POST"),
    }
    assert expected <= route_keys


def test_subtitle_config_endpoint(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    config = app.state.runtime.config_store.read()
    config["native_popup_enabled"] = False
    app.state.runtime.config_store.write(config)

    with TestClient(app) as client:
        response = client.put(
            "/admin/subtitle-config",
            json={
                "native_popup_enabled": False,
                "native_popup_position": "custom",
                "native_popup_custom_x": 321,
                "native_popup_custom_y": -45,
                "native_popup_background_color": "#112233",
                "native_popup_text_color": "#abcdef",
                "native_popup_click_through": True,
                "native_popup_transparent_background": True,
                "native_popup_text_shadow": True,
                "native_popup_shadow_color": "#010101",
                "native_popup_shadow_offset": 3,
            },
        )
        assert response.status_code == 200
        subtitle = client.get("/admin/subtitle-config").json()
        assert subtitle["native_popup_position"] == "custom"
        assert subtitle["native_popup_custom_x"] == 321
        assert subtitle["native_popup_custom_y"] == -45
        assert subtitle["native_popup_background_color"] == "#112233"
        assert subtitle["native_popup_text_color"] == "#abcdef"
        assert subtitle["native_popup_click_through"] is True
        assert subtitle["native_popup_transparent_background"] is True
        assert subtitle["native_popup_text_shadow"] is True
        assert subtitle["native_popup_shadow_color"] == "#010101"
        assert subtitle["native_popup_shadow_offset"] == 3
        assert "upstream_api_key" not in subtitle
