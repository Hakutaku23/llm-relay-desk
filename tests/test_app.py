from pathlib import Path

from fastapi.testclient import TestClient

from llm_relay_desk.application import create_app
from llm_relay_desk.settings import Settings


def make_settings(tmp_path: Path, *, with_frontend: bool = True) -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "data"
    frontend_dist_dir = tmp_path / "frontend-dist"
    if with_frontend:
        assets_dir = frontend_dist_dir / "assets"
        assets_dir.mkdir(parents=True)
        (frontend_dist_dir / "index.html").write_text(
            '<!doctype html><html><body><div id="app"></div>'
            '<script type="module" src="/ui/assets/app.js"></script></body></html>',
            encoding="utf-8",
        )
        (assets_dir / "app.js").write_text("console.log('vue-test-build')", encoding="utf-8")
    return Settings(
        host="127.0.0.1",
        port=11434,
        data_dir=data_dir,
        static_dir=project_root / "static",
        monitor_dir=project_root / "monitor",
        frontend_dist_dir=frontend_dist_dir,
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
        assert health.json()["status"] == "ok"
        ui = client.get("/ui/")
        assert ui.status_code == 200
        assert '<div id="app"></div>' in ui.text
        assert "game-mode-controls.js" not in ui.text
        assert client.get("/ui/dashboard").status_code == 200
        asset = client.get("/ui/assets/app.js")
        assert asset.status_code == 200
        assert "vue-test-build" in asset.text
        assert client.get("/ui/assets/missing.js").status_code == 404

        legacy = client.get("/ui-legacy/")
        assert legacy.status_code == 200
        assert "data-tab=\"subtitle\"" in legacy.text
        assert "/ui-legacy/game-mode-controls.js" in legacy.text
        assert "/ui-legacy/security-controls.js" in legacy.text
        assert 'href="/ui-legacy/styles.css' in legacy.text
        assert 'src="/ui-legacy/app.js' in legacy.text
        task_isolation = client.get("/ui-legacy/task-isolation.html")
        assert task_isolation.status_code == 200
        assert 'href="/ui-legacy/task-isolation.css' in task_isolation.text
        assert 'src="/ui-legacy/task-isolation.js' in task_isolation.text
        assert 'href="/ui-legacy/"' in task_isolation.text
        assert client.get("/ui-legacy/task-isolation.js").status_code == 200
        assert client.get("/ui-legacy/task-isolation.css").status_code == 200
        ui = legacy
        assert "upstreamProtocol" in ui.text
        assert "forceReasoningEnabled" in ui.text
        assert "defaultReasoningEffort" in ui.text
        assert "debugLoggingEnabled" in ui.text
        assert "debugLogDirectory" in ui.text
        assert "debugLogRetentionFiles" in ui.text
        assert "clearDebugLogsBtn" in ui.text
        assert "nativePopupBackgroundColor" in ui.text
        assert "nativePopupClickThrough" in ui.text
        assert "nativePopupTextOpacity" in ui.text
        assert "nativePopupBackgroundOpacity" in ui.text
        assert "nativePopupTextShadow" in ui.text
        assert "nativePopupFontFamily" in ui.text
        assert "nativePopupTextAlign" in ui.text
        assert "nativePopupContentMode" in ui.text
        assert "nativePopupDialogueFields" in ui.text
        assert "nativePopupPlainTextFallback" in ui.text
        assert "nativePopupForceUpstreamStream" in ui.text
        assert "nativePopupTextOutline" in ui.text
        assert "nativePopupOutlineColor" in ui.text
        assert "nativePopupOutlineWidth" in ui.text
        assert "subtitleRenderedPreview" in ui.text
        config_section = ui.text.split('id="tab-config"', 1)[1].split('id="tab-subtitle"', 1)[0]
        assert "nativePopupEnabled" not in config_section
        assert client.get("/monitor/").status_code == 200
        fonts = client.get("/admin/subtitle-fonts")
        assert fonts.status_code == 200
        assert isinstance(fonts.json()["fonts"], list)


def test_spa_fallback_does_not_swallow_api_routes(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    config = app.state.runtime.config_store.read()
    config["native_popup_enabled"] = False
    app.state.runtime.config_store.write(config)

    with TestClient(app) as client:
        assert client.get("/health").headers["content-type"].startswith("application/json")
        assert client.get("/admin/config").headers["content-type"].startswith("application/json")
        assert client.get("/admin/not-a-route").status_code == 404
        assert client.get("/api/not-a-route").status_code == 404
        assert client.get("/v1/not-a-route").status_code == 404
        assert client.get("/ws/not-a-route").status_code == 404
        monitor = client.get("/monitor/")
        assert monitor.status_code == 200
        assert "requestList" in monitor.text
        assert '<div id="app"></div>' not in monitor.text


def test_missing_frontend_build_is_diagnostic_and_backend_remains_available(
    tmp_path: Path,
) -> None:
    app = create_app(make_settings(tmp_path, with_frontend=False))
    config = app.state.runtime.config_store.read()
    config["native_popup_enabled"] = False
    app.state.runtime.config_store.write(config)

    with TestClient(app) as client:
        ui = client.get("/ui/")
        assert ui.status_code == 503
        assert ui.json() == {"detail": "Vue UI build is unavailable"}
        assert client.get("/ui/nested-route").status_code == 503
        assert client.get("/ui/assets/missing.js").status_code == 404
        assert client.get("/health").status_code == 200
        assert client.get("/ui-legacy/").status_code == 200
        assert client.get("/monitor/").status_code == 200


def test_route_contract_is_preserved(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    def route_keys(routes) -> set[tuple[str, str]]:
        keys: set[tuple[str, str]] = set()
        for route in routes:
            if hasattr(route, "path"):
                keys.update(
                    (route.path, method)
                    for method in (getattr(route, "methods", None) or {"WEBSOCKET"})
                )
            nested = getattr(route, "routes", None)
            if nested:
                keys.update(route_keys(nested))
            original_router = getattr(route, "original_router", None)
            if original_router is not None:
                keys.update(route_keys(original_router.routes))
        return keys

    actual = route_keys(app.routes)
    expected = {
        ("/health", "GET"),
        ("/ws/monitor", "WEBSOCKET"),
        ("/admin/config", "GET"),
        ("/admin/config", "PUT"),
        ("/admin/subtitle-config", "GET"),
        ("/admin/debug-logs", "GET"),
        ("/admin/debug-logs", "DELETE"),
        ("/admin/subtitle-config", "PUT"),
        ("/admin/subtitle-fonts", "GET"),
        ("/admin/subtitle-preview.png", "POST"),
        ("/admin/subtitle-positioning/start", "POST"),
        ("/admin/subtitle-positioning/finish", "POST"),
        ("/admin/prompts", "GET"),
        ("/api/chat", "POST"),
        ("/api/generate", "POST"),
        ("/v1/models", "GET"),
        ("/v1/chat/completions", "POST"),
    }
    assert expected <= actual


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
                "native_popup_font_family": "Noto Sans CJK SC",
                "native_popup_text_align": "right",
                "native_popup_text_opacity": 0.75,
                "native_popup_background_opacity": 0.0,
                "native_popup_text_shadow": True,
                "native_popup_shadow_color": "#010101",
                "native_popup_shadow_offset": 3,
                "native_popup_text_outline": True,
                "native_popup_outline_color": "#020202",
                "native_popup_outline_width": 2,
                "native_popup_content_mode": "dialogue",
                "native_popup_dialogue_fields": ["response", "statement"],
                "native_popup_plain_text_fallback": True,
                "native_popup_force_upstream_stream": True,
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
        assert subtitle["native_popup_font_family"] == "Noto Sans CJK SC"
        assert subtitle["native_popup_content_mode"] == "dialogue"
        assert subtitle["native_popup_dialogue_fields"] == ["response", "statement"]
        assert subtitle["native_popup_force_upstream_stream"] is True
        assert subtitle["native_popup_text_align"] == "right"
        assert subtitle["native_popup_text_opacity"] == 0.75
        assert subtitle["native_popup_background_opacity"] == 0.0
        assert subtitle["native_popup_transparent_background"] is True
        assert subtitle["native_popup_text_shadow"] is True
        assert subtitle["native_popup_shadow_color"] == "#010101"
        assert subtitle["native_popup_shadow_offset"] == 3
        assert subtitle["native_popup_text_outline"] is True
        assert subtitle["native_popup_outline_color"] == "#020202"
        assert subtitle["native_popup_outline_width"] == 2
        assert "upstream_api_key" not in subtitle


def test_high_fidelity_subtitle_preview_uses_png_renderer(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    config = app.state.runtime.config_store.read()
    config["native_popup_enabled"] = False
    app.state.runtime.config_store.write(config)

    with TestClient(app) as client:
        response = client.post(
            "/admin/subtitle-preview.png",
            json={
                "native_popup_width": 640,
                "native_popup_height": 160,
                "native_popup_background_opacity": 0.0,
                "native_popup_text_color": "#ff0000",
                "native_popup_text_shadow": False,
                "native_popup_text_outline": False,
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/png")
        assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
        # Rendering a preview must not persist unsaved form settings.
        stored = client.get("/admin/subtitle-config").json()
        assert stored["native_popup_text_color"] != "#ff0000"


def test_debug_log_list_detail_and_single_delete_are_path_safe(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    manager = app.state.runtime.debug_logs
    directory = manager.resolve_directory()
    directory.mkdir(parents=True, exist_ok=True)
    name = "20260101_request.json"
    (directory / name).write_text(
        '{"format_version":2,"timestamp":"2026-01-01T00:00:00Z",'
        '"request_id":"req","client_request":{"headers":{"Authorization":"<redacted>"}},'
        '"upstream_request":{},"upstream_response":{"status_code":200,"outcome":"completed"}}',
        encoding="utf-8",
    )
    with TestClient(app) as client:
        listed = client.get("/admin/debug-logs")
        assert listed.status_code == 200
        assert listed.json()["logs"][0]["id"] == name
        detail = client.get(f"/admin/debug-logs/{name}")
        assert detail.json()["client_request"]["headers"]["Authorization"] == "<redacted>"
        assert client.get("/admin/debug-logs/..%2Fconfig.json").status_code == 404
        assert client.delete(f"/admin/debug-logs/{name}").json()["ok"] is True
        assert not (directory / name).exists()
