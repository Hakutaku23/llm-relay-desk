from __future__ import annotations

from fastapi import Request, WebSocket

from llm_relay_desk.runtime import Runtime


def runtime_from_request(request: Request) -> Runtime:
    return request.app.state.runtime


def runtime_from_websocket(websocket: WebSocket) -> Runtime:
    return websocket.app.state.runtime
