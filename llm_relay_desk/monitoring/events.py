from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import Request

from .hub import MonitorHub
from .time_utils import utc_now_iso


def request_source(request: Request) -> tuple[str, str]:
    source = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "").strip()[:300]
    return source, user_agent


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:16]}"


def publish_start(
    hub: MonitorHub,
    *,
    request_id: str,
    request: Request,
    api: str,
    route: str,
    model: str,
    stream: bool,
) -> float:
    source, user_agent = request_source(request)
    hub.publish(
        {
            "type": "request_start",
            "request_id": request_id,
            "api": api,
            "route": route,
            "model": model,
            "source": source,
            "user_agent": user_agent,
            "stream": stream,
            "started_at": utc_now_iso(),
        }
    )
    return time.perf_counter()


def publish_done(
    hub: MonitorHub,
    request_id: str,
    started: float,
    status_code: int,
) -> None:
    hub.publish(
        {
            "type": "request_done",
            "request_id": request_id,
            "finished_at": utc_now_iso(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "status_code": status_code,
        }
    )


def publish_error(
    hub: MonitorHub,
    request_id: str,
    started: float,
    error: str,
    status_code: int | None = None,
) -> None:
    hub.publish(
        {
            "type": "request_error",
            "request_id": request_id,
            "finished_at": utc_now_iso(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "status_code": status_code,
            "error": error,
        }
    )


def publish_cancelled(
    hub: MonitorHub,
    request_id: str,
    started: float,
    status_code: int | None,
) -> None:
    hub.publish(
        {
            "type": "request_cancelled",
            "request_id": request_id,
            "finished_at": utc_now_iso(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "status_code": status_code,
            "error": "调用方已断开连接",
        }
    )
