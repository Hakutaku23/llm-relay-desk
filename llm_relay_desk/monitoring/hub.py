from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from .time_utils import utc_now_iso

EventSink = Callable[[dict[str, Any]], None]


class MonitorHub:
    """In-memory, best-effort side channel for monitoring UIs."""

    def __init__(
        self,
        *,
        history_limit: int = 60,
        queue_size: int = 2048,
        capture_char_limit: int = 1_000_000,
        sinks: list[EventSink] | None = None,
    ) -> None:
        self.history_limit = history_limit
        self.queue_size = queue_size
        self.capture_char_limit = capture_char_limit
        self.records: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.sinks = list(sinks or [])

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self.queue_size
        )
        self.subscribers.add(event_queue)
        return event_queue

    def unsubscribe(self, event_queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(event_queue)

    def snapshot(self) -> list[dict[str, Any]]:
        return [dict(record) for record in self.records.values()]

    def clear(self) -> None:
        self.records.clear()
        self.publish({"type": "monitor_cleared", "at": utc_now_iso()})

    def publish(self, event: dict[str, Any]) -> None:
        self._update_record(event)
        for sink in tuple(self.sinks):
            try:
                sink(event)
            except Exception:
                # Observers are isolated from the forwarding path.
                pass

        if not self.subscribers:
            return

        for event_queue in tuple(self.subscribers):
            try:
                event_queue.put_nowait(event)
            except asyncio.QueueFull:
                self._replace_with_snapshot(event_queue)

    def _replace_with_snapshot(
        self,
        event_queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        try:
            while True:
                event_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            event_queue.put_nowait(
                {
                    "type": "snapshot",
                    "requests": self.snapshot(),
                    "resync": True,
                }
            )
        except asyncio.QueueFull:
            pass

    def _append_text(
        self,
        record: dict[str, Any],
        field: str,
        text: str,
    ) -> None:
        if not text:
            return
        combined = str(record.get(field, "")) + text
        if len(combined) > self.capture_char_limit:
            combined = combined[-self.capture_char_limit :]
            record[f"{field}_truncated"] = True
        record[field] = combined

    def _update_record(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        request_id = event.get("request_id")
        if not request_id:
            return

        if event_type == "request_start":
            self.records[request_id] = {
                "request_id": request_id,
                "api": event.get("api", ""),
                "route": event.get("route", ""),
                "model": event.get("model", ""),
                "source": event.get("source", ""),
                "user_agent": event.get("user_agent", ""),
                "stream": bool(event.get("stream")),
                "started_at": event.get("started_at", utc_now_iso()),
                "finished_at": None,
                "elapsed_ms": None,
                "status_code": None,
                "status": "streaming",
                "content": "",
                "reasoning": "",
                "error": "",
            }
            self.records.move_to_end(request_id)
            while len(self.records) > self.history_limit:
                self.records.popitem(last=False)
            return

        record = self.records.get(request_id)
        if record is None:
            return

        if event_type == "content_delta":
            self._append_text(record, "content", str(event.get("text", "")))
        elif event_type == "reasoning_delta":
            self._append_text(record, "reasoning", str(event.get("text", "")))
        elif event_type == "request_done":
            self._finish_record(record, event, "complete")
        elif event_type == "request_error":
            self._finish_record(record, event, "error")
            record["error"] = str(event.get("error", "未知错误"))
        elif event_type == "request_cancelled":
            self._finish_record(record, event, "cancelled")
            record["error"] = str(event.get("error", "调用方已断开连接"))

    @staticmethod
    def _finish_record(
        record: dict[str, Any],
        event: dict[str, Any],
        status: str,
    ) -> None:
        record["status"] = status
        record["finished_at"] = event.get("finished_at", utc_now_iso())
        record["elapsed_ms"] = event.get("elapsed_ms")
        record["status_code"] = event.get("status_code")
