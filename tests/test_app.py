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
        assert health.json()["version"] == "4.0.0"
        assert client.get("/ui/").status_code == 200
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
        ("/admin/prompts", "GET"),
        ("/api/chat", "POST"),
        ("/api/generate", "POST"),
        ("/v1/models", "GET"),
        ("/v1/chat/completions", "POST"),
    }
    assert expected <= route_keys
