from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from llm_relay_desk.api.dependencies import runtime_from_websocket
from llm_relay_desk.monitoring import utc_now_iso

router = APIRouter()


@router.websocket("/ws/monitor")
async def monitor_websocket(websocket: WebSocket) -> None:
    runtime = runtime_from_websocket(websocket)
    await websocket.accept()
    event_queue = runtime.monitor.subscribe()
    try:
        await websocket.send_json(
            {"type": "snapshot", "requests": runtime.monitor.snapshot()}
        )
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=20.0)
            except asyncio.TimeoutError:
                event = {"type": "heartbeat", "at": utc_now_iso()}
            await websocket.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        runtime.monitor.unsubscribe(event_queue)
