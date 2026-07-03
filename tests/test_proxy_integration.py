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


class StubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

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
        if self.path == "/v1/chat/completions":
            assert payload["messages"][0]["role"] == "system"
            if payload.get("stream"):
                chunks = [
                    b'data: {"choices":[{"delta":{"reasoning":"R"}}]}\n\n',
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
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def make_app(tmp_path: Path, upstream_port: int):
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
