from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from typing import Any


class NativePopupController:
    """Best-effort bridge from the API process to native subtitle windows.

    The desktop worker runs in a separate process. Queue overflow, missing
    desktop sessions and popup crashes are intentionally isolated from API
    forwarding.
    """

    def __init__(self, *, queue_size: int = 4096) -> None:
        self.queue_size = queue_size
        self.enabled = False
        self.close_seconds = 30
        self.popup_config: dict[str, Any] = {}
        self.event_queue: Any = None
        self.process: multiprocessing.Process | None = None
        self.lock = threading.RLock()
        self.last_start_attempt = 0.0

    def configure(self, config: dict[str, Any]) -> None:
        enabled = bool(config.get("native_popup_enabled", True))
        try:
            close_seconds = int(config.get("native_popup_close_seconds", 30))
        except (TypeError, ValueError):
            close_seconds = 30
        close_seconds = max(1, min(3600, close_seconds))

        popup_config = {
            "type": "popup_config",
            "enabled": enabled,
            "close_seconds": close_seconds,
            "position": str(config.get("native_popup_position", "bottom_center")),
            "offset_x": int(config.get("native_popup_offset_x", 0)),
            "offset_y": int(config.get("native_popup_offset_y", 0)),
            "width": int(config.get("native_popup_width", 960)),
            "height": int(config.get("native_popup_height", 220)),
            "font_size": int(config.get("native_popup_font_size", 24)),
            "opacity": float(config.get("native_popup_opacity", 0.88)),
            "show_reasoning": bool(
                config.get("native_popup_show_reasoning", False)
            ),
        }

        with self.lock:
            self.enabled = enabled
            self.close_seconds = close_seconds
            self.popup_config = popup_config
            if enabled:
                self._ensure_process_locked()
            if self.event_queue is not None:
                self._put_locked(dict(popup_config))

    def publish(self, event: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self.lock:
            self._ensure_process_locked()
            if self.event_queue is not None:
                self._put_locked(dict(event))

    def is_alive(self) -> bool:
        with self.lock:
            return bool(self.process and self.process.is_alive())

    def stop(self) -> None:
        with self.lock:
            if self.event_queue is not None:
                self._put_locked({"type": "popup_shutdown"})
            process = self.process
        if process and process.is_alive():
            process.join(timeout=1.5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
        with self.lock:
            self._dispose_locked()

    def _ensure_process_locked(self) -> None:
        if self.process and self.process.is_alive():
            return

        now = time.monotonic()
        if now - self.last_start_attempt < 5.0:
            return
        self.last_start_attempt = now
        self._dispose_locked()

        try:
            from llm_relay_desk.desktop.window import run_popup_worker

            context = multiprocessing.get_context("spawn")
            event_queue = context.Queue(maxsize=self.queue_size)
            process = context.Process(
                target=run_popup_worker,
                args=(event_queue,),
                name="llm-relay-native-popup",
                daemon=True,
            )
            process.start()
            self.event_queue = event_queue
            self.process = process
            if self.popup_config:
                self._put_locked(dict(self.popup_config))
        except Exception as exc:
            print(f"[native-popup] 启动失败：{exc}", flush=True)
            self._dispose_locked()

    def _put_locked(self, event: dict[str, Any]) -> None:
        if self.event_queue is None:
            return
        try:
            self.event_queue.put_nowait(event)
        except queue.Full:
            pass
        except (BrokenPipeError, EOFError, OSError):
            self._dispose_locked()

    def _dispose_locked(self) -> None:
        event_queue = self.event_queue
        process = self.process
        self.event_queue = None
        self.process = None
        if process is not None and not process.is_alive():
            try:
                process.join(timeout=0.2)
            except (AssertionError, OSError, ValueError):
                pass
        if event_queue is not None:
            try:
                event_queue.close()
            except (AttributeError, OSError, ValueError):
                pass
            try:
                event_queue.join_thread()
            except (AttributeError, OSError, ValueError):
                pass
