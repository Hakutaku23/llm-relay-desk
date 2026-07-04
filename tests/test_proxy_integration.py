from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

from fastapi.testclient import TestClient

from llm_relay_desk.application import create_app
from llm_relay_desk.settings import Settings
from llm_relay_desk.proxy.protocol import resolve_upstream_protocol


class StubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    received_payloads: list[tuple[str, dict[str, object]]] = []

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/v1/models":
            self._json({"object": "list", "data": [{"id": "stub-model"}]})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        type(self).received_payloads.append((self.path, payload))
        if self.path == "/v1/chat/completions":
            assert payload["messages"][0]["role"] == "system"
            if payload.get("stream"):
                chunks = [
                    b'data: {"choices":[{"delta":{"reasoning_content":"R"}}]}\n\n',
                    b'data: {"choices":[{"delta":{"content":"A"}}]}\n\n',
                    b'data: [DONE]\n\n',
                ]
                self._stream("text/event-stream", chunks)
            else:
                self._json(
                    {
                        "choices": [
                            {"message": {"role": "assistant", "content": "A"}}
                        ]
                    }
                )
            return
        if self.path == "/api/chat":
            assert payload["messages"][0]["role"] == "system"
            self._stream(
                "application/x-ndjson",
                [
                    b'{"message":{"thinking":"R","content":"A"},"done":false}\n',
                    b'{"message":{"content":"B"},"done":true}\n',
                ],
            )
            return
        self.send_error(404)

    def _json(self, value: object) -> None:
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, content_type: str, chunks: list[bytes]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(chunk)
            self.wfile.flush()
        self.close_connection = True


@contextmanager
def stub_server() -> Iterator[ThreadingHTTPServer]:
    StubHandler.received_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def make_app(tmp_path: Path, upstream_port: int, upstream_protocol: str = "auto"):
    project_root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "data"
    settings = Settings(
        host="127.0.0.1",
        port=11434,
        data_dir=data_dir,
        static_dir=project_root / "static",
        monitor_dir=project_root / "monitor",
        config_path=data_dir / "config.json",
        prompts_path=data_dir / "prompts.json",
    )
    app = create_app(settings)
    config = app.state.runtime.config_store.read()
    config.update(
        {
            "upstream_base_url": f"http://127.0.0.1:{upstream_port}/v1",
            "upstream_protocol": upstream_protocol,
            "local_api_key": "test-key",
            "native_popup_enabled": False,
        }
    )
    app.state.runtime.config_store.write(config)
    return app


def test_openai_and_ollama_streaming_are_preserved(tmp_path: Path) -> None:
    with stub_server() as upstream:
        app = make_app(tmp_path, upstream.server_address[1])
        with TestClient(app) as client:
            openai_response = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer test-key"},
                json={
                    "model": "stub-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )
            assert openai_response.status_code == 200
            assert openai_response.content.endswith(b"data: [DONE]\n\n")
            openai_id = openai_response.headers["x-relay-request-id"]
            assert app.state.runtime.monitor.records[openai_id]["reasoning"] == "R"
            assert app.state.runtime.monitor.records[openai_id]["content"] == "A"

            native_response = client.post(
                "/api/chat",
                json={
                    "model": "stub-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )
            assert native_response.status_code == 200
            assert native_response.content.endswith(b'"done":true}\n')
            native_id = native_response.headers["x-relay-request-id"]
            assert app.state.runtime.monitor.records[native_id]["reasoning"] == "R"
            assert app.state.runtime.monitor.records[native_id]["content"] == "AB"


def test_ollama_routes_adapt_to_openai_upstream(tmp_path: Path) -> None:
    with stub_server() as upstream:
        app = make_app(tmp_path, upstream.server_address[1], upstream_protocol="openai")
        with TestClient(app) as client:
            tags = client.get("/api/tags")
            assert tags.status_code == 200
            assert tags.json()["models"][0]["name"] == "stub-model"

            version = client.get("/api/version")
            assert version.status_code == 200
            assert "openai-adapter" in version.json()["version"]

            chat = client.post(
                "/api/chat",
                json={
                    "model": "stub-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )
            assert chat.status_code == 200
            lines = [json.loads(line) for line in chat.text.splitlines() if line.strip()]
            assert any(item.get("message", {}).get("thinking") == "R" for item in lines)
            assert any(item.get("message", {}).get("content") == "A" for item in lines)
            assert lines[-1]["done"] is True
            request_id = chat.headers["x-relay-request-id"]
            assert app.state.runtime.monitor.records[request_id]["reasoning"] == "R"
            assert app.state.runtime.monitor.records[request_id]["content"] == "A"

            generated = client.post(
                "/api/generate",
                json={"model": "stub-model", "prompt": "hello", "stream": False},
            )
            assert generated.status_code == 200
            assert generated.json()["response"] == "A"
            assert generated.json()["done"] is True


def test_native_ollama_nonstream_client_is_streamed_upstream_and_aggregated(tmp_path: Path) -> None:
    with stub_server() as upstream:
        app = make_app(tmp_path, upstream.server_address[1], upstream_protocol="ollama")
        with TestClient(app) as client:
            config = app.state.runtime.config_store.read()
            config["native_popup_enabled"] = True
            app.state.runtime.config_store.write(config)
            response = client.post(
                "/api/chat",
                json={
                    "model": "stub-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": False,
                },
            )
            assert response.status_code == 200
            assert response.json()["message"]["content"] == "AB"
            assert response.json()["message"]["thinking"] == "R"
            request_id = response.headers["x-relay-request-id"]
            assert app.state.runtime.monitor.records[request_id]["content"] == "AB"
            assert app.state.runtime.monitor.records[request_id]["reasoning"] == "R"


def test_nonstream_clients_receive_aggregated_responses_while_monitor_streams(tmp_path: Path) -> None:
    with stub_server() as upstream:
        app = make_app(tmp_path, upstream.server_address[1], upstream_protocol="openai")
        with TestClient(app) as client:
            config = app.state.runtime.config_store.read()
            config["native_popup_enabled"] = True
            app.state.runtime.config_store.write(config)
            openai_response = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer test-key"},
                json={
                    "model": "stub-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": False,
                },
            )
            assert openai_response.status_code == 200
            assert openai_response.json()["choices"][0]["message"]["content"] == "A"
            assert openai_response.json()["choices"][0]["message"]["reasoning_content"] == "R"
            openai_id = openai_response.headers["x-relay-request-id"]
            assert app.state.runtime.monitor.records[openai_id]["content"] == "A"
            assert app.state.runtime.monitor.records[openai_id]["reasoning"] == "R"

            native_response = client.post(
                "/api/chat",
                json={
                    "model": "stub-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": False,
                },
            )
            assert native_response.status_code == 200
            assert native_response.json()["message"]["content"] == "A"
            assert native_response.json()["message"]["thinking"] == "R"
            native_id = native_response.headers["x-relay-request-id"]
            assert app.state.runtime.monitor.records[native_id]["content"] == "A"
            assert app.state.runtime.monitor.records[native_id]["reasoning"] == "R"


def test_auto_protocol_resolution() -> None:
    assert resolve_upstream_protocol({"upstream_protocol": "auto", "upstream_base_url": "http://127.0.0.1:11435/v1"}) == "ollama"
    assert resolve_upstream_protocol({"upstream_protocol": "auto", "upstream_base_url": "https://api.deepseek.com"}) == "openai"
    assert resolve_upstream_protocol({"upstream_protocol": "openai", "upstream_base_url": "http://127.0.0.1:11434"}) == "openai"


def test_force_reasoning_is_injected_across_proxy_paths(tmp_path: Path) -> None:
    with stub_server() as upstream:
        app = make_app(tmp_path, upstream.server_address[1], upstream_protocol="openai")
        config = app.state.runtime.config_store.read()
        config.update(
            {
                "force_reasoning_enabled": True,
                "default_reasoning_effort": "high",
                "native_popup_enabled": False,
            }
        )
        app.state.runtime.config_store.write(config)

        with TestClient(app) as client:
            direct = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer test-key"},
                json={
                    "model": "stub-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": False,
                },
            )
            assert direct.status_code == 200
            direct_payload = StubHandler.received_payloads[-1][1]
            assert direct_payload["reasoning_effort"] == "high"

            adapted = client.post(
                "/api/chat",
                json={
                    "model": "stub-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )
            assert adapted.status_code == 200
            adapted_payload = StubHandler.received_payloads[-1][1]
            assert adapted_payload["reasoning_effort"] == "high"

            explicit = client.post(
                "/api/chat",
                json={
                    "model": "stub-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                    "think": False,
                },
            )
            assert explicit.status_code == 200
            explicit_payload = StubHandler.received_payloads[-1][1]
            assert explicit_payload["thinking"] == {"type": "disabled"}
            assert "reasoning_effort" not in explicit_payload


def test_force_reasoning_is_injected_for_native_ollama(tmp_path: Path) -> None:
    with stub_server() as upstream:
        app = make_app(tmp_path, upstream.server_address[1], upstream_protocol="ollama")
        config = app.state.runtime.config_store.read()
        config.update(
            {
                "force_reasoning_enabled": True,
                "default_reasoning_effort": "medium",
                "native_popup_enabled": False,
            }
        )
        app.state.runtime.config_store.write(config)

        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "model": "stub-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )
            assert response.status_code == 200
            native_payload = StubHandler.received_payloads[-1][1]
            assert native_payload["think"] == "medium"

            response = client.post(
                "/api/chat",
                json={
                    "model": "stub-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                    "think": False,
                },
            )
            assert response.status_code == 200
            native_payload = StubHandler.received_payloads[-1][1]
            assert native_payload["think"] is False


def test_debug_logging_records_outbound_request_and_complete_stream(tmp_path: Path) -> None:
    with stub_server() as upstream:
        app = make_app(tmp_path, upstream.server_address[1], upstream_protocol="openai")
        config = app.state.runtime.config_store.read()
        config.update(
            {
                "debug_logging_enabled": True,
                "debug_log_directory": "debug_logs",
                "debug_log_retention_files": 10,
                "upstream_api_key": "upstream-secret",
                "native_popup_enabled": False,
            }
        )
        app.state.runtime.config_store.write(config)

        with TestClient(app) as client:
            response = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer test-key"},
                json={
                    "model": "stub-model",
                    "messages": [{"role": "user", "content": "debug me"}],
                    "stream": True,
                },
            )
            assert response.status_code == 200
            status = client.get("/admin/debug-logs").json()
            assert status["enabled"] is True
            assert status["file_count"] == 1

        files = list((tmp_path / "data" / "debug_logs").glob("*.json"))
        assert len(files) == 1
        document = json.loads(files[0].read_text(encoding="utf-8"))
        assert document["format_version"] == 2
        assert document["client_request"]["headers"]["authorization"] == "<redacted>"
        assert document["upstream_request"]["headers"]["Authorization"] == "<redacted>"
        assert document["client_request"]["body"]["messages"][0]["content"] == "debug me"
        assert document["upstream_request"]["body"]["messages"][0]["role"] == "system"
        upstream_response = document["upstream_response"]
        assert upstream_response["format"] == "openai-sse"
        assert upstream_response["stream_events"] == 2
        assert upstream_response["stream_done_marker"] is True
        message = upstream_response["body"]["choices"][0]["message"]
        assert message["reasoning_content"] == "R"
        assert message["content"] == "A"
        assert upstream_response["outcome"] == "completed"
        assert upstream_response["response_bytes"] > 0


def test_debug_logs_can_be_cleared(tmp_path: Path) -> None:
    app = make_app(tmp_path, 1, upstream_protocol="openai")
    config = app.state.runtime.config_store.read()
    config.update({"debug_logging_enabled": True, "debug_log_directory": "debug_logs"})
    app.state.runtime.config_store.write(config)
    directory = tmp_path / "data" / "debug_logs"
    directory.mkdir(parents=True)
    (directory / "one.json").write_text("{}\n", encoding="utf-8")
    with TestClient(app) as client:
        result = client.delete("/admin/debug-logs")
        assert result.status_code == 200
        assert result.json()["removed"] == 1
        assert result.json()["status"]["file_count"] == 0
