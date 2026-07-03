from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from collections.abc import Callable
from typing import Any


class NativePopupController:
    """Best-effort bridge from the API process to the desktop subtitle worker."""

    def __init__(
        self,
        *,
        queue_size: int = 4096,
        on_position_saved: Callable[[int, int], None] | None = None,
    ) -> None:
        self.queue_size = queue_size
        self.on_position_saved = on_position_saved
        self.enabled = False
        self.close_seconds = 30
        self.popup_config: dict[str, Any] = {}
        self.event_queue: Any = None
        self.control_queue: Any = None
        self.process: multiprocessing.Process | None = None
        self.control_thread: threading.Thread | None = None
        self.control_stop: threading.Event | None = None
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
            "custom_x": int(config.get("native_popup_custom_x", 120)),
            "custom_y": int(config.get("native_popup_custom_y", 120)),
            "width": int(config.get("native_popup_width", 960)),
            "height": int(config.get("native_popup_height", 220)),
            "font_size": int(config.get("native_popup_font_size", 24)),
            "font_family": str(config.get("native_popup_font_family", "Microsoft YaHei UI")),
            "text_align": str(config.get("native_popup_text_align", "left")),
            "opacity": float(config.get("native_popup_opacity", 0.88)),
            "text_opacity": float(config.get("native_popup_text_opacity", 1.0)),
            "background_opacity": float(
                config.get(
                    "native_popup_background_opacity",
                    0.0
                    if config.get("native_popup_transparent_background", False)
                    else config.get("native_popup_opacity", 0.88),
                )
            ),
            "show_reasoning": bool(config.get("native_popup_show_reasoning", False)),
            "click_through": bool(config.get("native_popup_click_through", False)),
            "transparent_background": bool(
                config.get("native_popup_transparent_background", False)
            ),
            "text_shadow": bool(config.get("native_popup_text_shadow", True)),
            "shadow_color": str(config.get("native_popup_shadow_color", "#000000")),
            "shadow_offset": int(config.get("native_popup_shadow_offset", 2)),
            "background_color": str(
                config.get("native_popup_background_color", "#101318")
            ),
            "text_color": str(config.get("native_popup_text_color", "#f7f8fa")),
            "muted_color": str(config.get("native_popup_muted_color", "#aeb6c2")),
            "border_color": str(config.get("native_popup_border_color", "#343a46")),
            "error_color": str(config.get("native_popup_error_color", "#ff8f9b")),
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

    def set_positioning_mode(
        self,
        enabled: bool,
        *,
        timeout_seconds: int = 60,
    ) -> None:
        """Temporarily disable click-through so the subtitle can be dragged."""

        if not self.enabled:
            return
        timeout_seconds = max(5, min(300, int(timeout_seconds)))
        with self.lock:
            self._ensure_process_locked()
            if self.event_queue is not None:
                self._put_locked(
                    {
                        "type": "popup_interaction_mode",
                        "mode": "positioning" if enabled else "configured",
                        "timeout_seconds": timeout_seconds,
                    }
                )

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
        thread = self._dispose()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _ensure_process_locked(self) -> None:
        if self.process and self.process.is_alive():
            return

        now = time.monotonic()
        if now - self.last_start_attempt < 5.0:
            return
        self.last_start_attempt = now
        old_thread = self._dispose_locked()
        if old_thread and old_thread is not threading.current_thread():
            old_thread.join(timeout=0.3)

        try:
            from llm_relay_desk.desktop.window import run_popup_worker

            context = multiprocessing.get_context("spawn")
            event_queue = context.Queue(maxsize=self.queue_size)
            control_queue = context.Queue(maxsize=64)
            process = context.Process(
                target=run_popup_worker,
                args=(event_queue, control_queue),
                name="llm-relay-native-popup",
                daemon=True,
            )
            process.start()
            self.event_queue = event_queue
            self.control_queue = control_queue
            self.process = process
            self._start_control_listener_locked(control_queue)
            if self.popup_config:
                self._put_locked(dict(self.popup_config))
        except Exception as exc:
            print(f"[native-popup] 启动失败：{exc}", flush=True)
            self._dispose_locked()

    def _start_control_listener_locked(self, control_queue: Any) -> None:
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._control_loop,
            args=(control_queue, stop_event),
            name="llm-relay-popup-control",
            daemon=True,
        )
        self.control_stop = stop_event
        self.control_thread = thread
        thread.start()

    def _control_loop(self, control_queue: Any, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                event = control_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            except (EOFError, OSError, ValueError):
                return
            if not isinstance(event, dict):
                continue
            if event.get("type") != "popup_position_saved":
                continue
            x = int(event.get("x", 0))
            y = int(event.get("y", 0))
            with self.lock:
                if self.popup_config:
                    self.popup_config.update(
                        {
                            "position": "custom",
                            "custom_x": x,
                            "custom_y": y,
                            "offset_x": 0,
                            "offset_y": 0,
                        }
                    )
            callback = self.on_position_saved
            if callback is None:
                continue
            try:
                callback(x, y)
            except Exception as exc:
                print(f"[native-popup] 保存字幕位置失败：{exc}", flush=True)

    def _put_locked(self, event: dict[str, Any]) -> None:
        if self.event_queue is None:
            return
        try:
            self.event_queue.put_nowait(event)
        except queue.Full:
            pass
        except (BrokenPipeError, EOFError, OSError):
            self._dispose_locked()

    def _dispose(self) -> threading.Thread | None:
        with self.lock:
            return self._dispose_locked()

    def _dispose_locked(self) -> threading.Thread | None:
        event_queue = self.event_queue
        control_queue = self.control_queue
        process = self.process
        control_thread = self.control_thread
        control_stop = self.control_stop
        self.event_queue = None
        self.control_queue = None
        self.process = None
        self.control_thread = None
        self.control_stop = None

        if control_stop is not None:
            control_stop.set()
        if process is not None and not process.is_alive():
            try:
                process.join(timeout=0.2)
            except (AssertionError, OSError, ValueError):
                pass
        for item in (event_queue, control_queue):
            if item is None:
                continue
            try:
                item.close()
            except (AttributeError, OSError, ValueError):
                pass
            try:
                item.join_thread()
            except (AttributeError, OSError, ValueError):
                pass
        return control_thread
