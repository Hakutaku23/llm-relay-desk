from __future__ import annotations

import ctypes
import queue
import re
import sys
import tkinter as tk
from multiprocessing.queues import Queue
from typing import Any, Callable


DEFAULT_POPUP_CONFIG: dict[str, Any] = {
    "enabled": True,
    "close_seconds": 30,
    "position": "bottom_center",
    "offset_x": 0,
    "offset_y": 0,
    "custom_x": 120,
    "custom_y": 120,
    "width": 960,
    "height": 220,
    "font_size": 24,
    "opacity": 0.88,
    "show_reasoning": False,
    "background_color": "#101318",
    "text_color": "#f7f8fa",
    "muted_color": "#aeb6c2",
    "border_color": "#343a46",
    "error_color": "#ff8f9b",
}

POSITION_VALUES = {
    "top_left",
    "top_center",
    "top_right",
    "center_left",
    "center",
    "center_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
    "custom",
}

FONT_FAMILY = "Microsoft YaHei UI"
DISPLAY_CHAR_LIMIT = 50_000
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _int_value(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _float_value(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _color_value(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text.lower() if HEX_COLOR_RE.fullmatch(text) else default


def normalize_popup_config(value: dict[str, Any] | None) -> dict[str, Any]:
    source = value or {}
    position = str(source.get("position", DEFAULT_POPUP_CONFIG["position"]))
    if position not in POSITION_VALUES:
        position = str(DEFAULT_POPUP_CONFIG["position"])
    return {
        "enabled": bool(source.get("enabled", True)),
        "close_seconds": _int_value(source.get("close_seconds"), 30, 1, 3600),
        "position": position,
        "offset_x": _int_value(source.get("offset_x"), 0, -10000, 10000),
        "offset_y": _int_value(source.get("offset_y"), 0, -10000, 10000),
        "custom_x": _int_value(source.get("custom_x"), 120, -10000, 10000),
        "custom_y": _int_value(source.get("custom_y"), 120, -10000, 10000),
        "width": _int_value(source.get("width"), 960, 320, 2400),
        "height": _int_value(source.get("height"), 220, 100, 900),
        "font_size": _int_value(source.get("font_size"), 24, 12, 72),
        "opacity": _float_value(source.get("opacity"), 0.88, 0.30, 1.0),
        "show_reasoning": bool(source.get("show_reasoning", False)),
        "background_color": _color_value(source.get("background_color"), "#101318"),
        "text_color": _color_value(source.get("text_color"), "#f7f8fa"),
        "muted_color": _color_value(source.get("muted_color"), "#aeb6c2"),
        "border_color": _color_value(source.get("border_color"), "#343a46"),
        "error_color": _color_value(source.get("error_color"), "#ff8f9b"),
    }


def _virtual_screen(window: tk.Toplevel) -> tuple[int, int, int, int]:
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            return (
                int(user32.GetSystemMetrics(76)),
                int(user32.GetSystemMetrics(77)),
                int(user32.GetSystemMetrics(78)),
                int(user32.GetSystemMetrics(79)),
            )
        except Exception:
            pass
    return 0, 0, int(window.winfo_screenwidth()), int(window.winfo_screenheight())


class SubtitleOverlay:
    """Single reusable subtitle window for the latest active request."""

    def __init__(
        self,
        root: tk.Tk,
        event: dict[str, Any],
        config_getter: Callable[[], dict[str, Any]],
        on_destroy: Callable[[str, bool], None],
        on_position_saved: Callable[[int, int], None],
    ) -> None:
        self.root = root
        self.config_getter = config_getter
        self.on_destroy = on_destroy
        self.on_position_saved = on_position_saved
        self.request_id = ""
        self.model = "模型响应"
        self.content_length = 0
        self.reasoning_length = 0
        self.reasoning_visible = False
        self.finished = False
        self.close_after_id: str | None = None
        self.countdown_after_id: str | None = None
        self.remaining_seconds = 0
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.dragging = False

        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)

        self._build()
        self.reset(event)
        self._show_without_stealing_focus()

    def _build(self) -> None:
        self.shell = tk.Frame(self.window, padx=18, pady=12)
        self.shell.pack(fill="both", expand=True)

        self.header = tk.Frame(self.shell)
        self.header.pack(fill="x", pady=(0, 6))

        self.status_label = tk.Label(
            self.header,
            text="模型响应 · 正在生成",
            font=(FONT_FAMILY, 9),
            anchor="w",
            cursor="fleur",
        )
        self.status_label.pack(side="left", fill="x", expand=True)

        self.close_button = tk.Button(
            self.header,
            text="×",
            command=lambda: self.destroy(manual=True),
            relief="flat",
            bd=0,
            font=(FONT_FAMILY, 12),
            padx=4,
            pady=0,
            cursor="hand2",
            takefocus=False,
        )
        self.close_button.pack(side="right")

        self.text = tk.Text(
            self.shell,
            wrap="word",
            relief="flat",
            bd=0,
            padx=0,
            pady=0,
            spacing1=2,
            spacing3=5,
            cursor="fleur",
            takefocus=False,
        )
        self.text.pack(fill="both", expand=True)
        self.text.configure(state="disabled")

        for widget in (self.shell, self.header, self.status_label, self.text):
            widget.bind("<ButtonPress-1>", self._start_drag, add="+")
            widget.bind("<B1-Motion>", self._drag, add="+")
            widget.bind("<ButtonRelease-1>", self._finish_drag, add="+")

    def _popup_config(self) -> dict[str, Any]:
        return normalize_popup_config(self.config_getter())

    def reset(self, event: dict[str, Any]) -> None:
        self._cancel_auto_close()
        self.request_id = str(event.get("request_id") or "unknown")
        self.model = str(event.get("model") or "模型响应")
        self.content_length = 0
        self.reasoning_length = 0
        self.reasoning_visible = False
        self.finished = False
        self.status_label.configure(text=f"{self.model} · 正在生成")
        self._replace_text("正在等待模型输出……", tag="reasoning")
        self.apply_config()
        self._show_without_stealing_focus()

    def apply_config(self) -> None:
        config = self._popup_config()
        bg = config["background_color"]
        text_color = config["text_color"]
        muted = config["muted_color"]
        border = config["border_color"]
        error = config["error_color"]

        try:
            self.window.attributes("-alpha", config["opacity"])
        except tk.TclError:
            pass
        self.window.configure(bg=bg)
        self.shell.configure(bg=bg, highlightbackground=border, highlightthickness=1)
        self.header.configure(bg=bg)
        self.status_label.configure(bg=bg, fg=muted)
        self.close_button.configure(
            bg=bg,
            fg=muted,
            activebackground=bg,
            activeforeground=text_color,
        )
        self.text.configure(
            bg=bg,
            fg=text_color,
            insertbackground=text_color,
            selectbackground=border,
            font=(FONT_FAMILY, config["font_size"]),
        )
        self.text.tag_configure("reasoning", foreground=muted)
        self.text.tag_configure("error", foreground=error)
        self._position_window(config)

    def _position_window(self, config: dict[str, Any]) -> None:
        width = int(config["width"])
        height = int(config["height"])
        position = str(config["position"])

        if position == "custom":
            x = int(config["custom_x"])
            y = int(config["custom_y"])
        else:
            left, top, screen_width, screen_height = _virtual_screen(self.window)
            margin = 36
            if position.endswith("_left"):
                x = left + margin
            elif position.endswith("_right"):
                x = left + screen_width - width - margin
            else:
                x = left + (screen_width - width) // 2

            if position.startswith("top_"):
                y = top + margin
            elif position.startswith("bottom_"):
                y = top + screen_height - height - margin
            else:
                y = top + (screen_height - height) // 2

            x += int(config["offset_x"])
            y += int(config["offset_y"])

        self.window.geometry(f"{width}x{height}{x:+d}{y:+d}")

    def _start_drag(self, event: tk.Event) -> str:
        self.dragging = True
        self.drag_offset_x = int(event.x_root) - int(self.window.winfo_x())
        self.drag_offset_y = int(event.y_root) - int(self.window.winfo_y())
        return "break"

    def _drag(self, event: tk.Event) -> str:
        if not self.dragging:
            return "break"
        x = int(event.x_root) - self.drag_offset_x
        y = int(event.y_root) - self.drag_offset_y
        self.window.geometry(f"{x:+d}{y:+d}")
        return "break"

    def _finish_drag(self, _: tk.Event) -> str:
        if not self.dragging:
            return "break"
        self.dragging = False
        self.on_position_saved(int(self.window.winfo_x()), int(self.window.winfo_y()))
        return "break"

    def _show_without_stealing_focus(self) -> None:
        self.window.update_idletasks()
        if sys.platform == "win32":
            try:
                user32 = ctypes.windll.user32
                hwnd = int(self.window.winfo_id())
                parent = int(user32.GetParent(hwnd))
                if parent:
                    hwnd = parent

                GWL_EXSTYLE = -20
                WS_EX_TOOLWINDOW = 0x00000080
                WS_EX_NOACTIVATE = 0x08000000
                WS_EX_LAYERED = 0x00080000
                SW_SHOWNOACTIVATE = 4
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOACTIVATE = 0x0010
                SWP_SHOWWINDOW = 0x0040
                HWND_TOPMOST = -1

                get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
                set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
                style = int(get_style(hwnd, GWL_EXSTYLE))
                set_style(
                    hwnd,
                    GWL_EXSTYLE,
                    style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED,
                )
                user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                user32.SetWindowPos(
                    hwnd,
                    HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
                return
            except Exception:
                pass
        self.window.deiconify()

    def _replace_text(self, text: str, tag: str | None = None) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if tag:
            self.text.insert("end", text, tag)
        else:
            self.text.insert("end", text)
        self.text.see("end")
        self.text.configure(state="disabled")

    def _append_text(self, text: str, tag: str | None = None) -> None:
        if not text:
            return
        self.text.configure(state="normal")
        if tag:
            self.text.insert("end", text, tag)
        else:
            self.text.insert("end", text)
        current_chars = int(self.text.count("1.0", "end-1c", "chars")[0])
        if current_chars > DISPLAY_CHAR_LIMIT:
            remove_chars = current_chars - DISPLAY_CHAR_LIMIT
            self.text.delete("1.0", f"1.0+{remove_chars}c")
        self.text.see("end")
        self.text.configure(state="disabled")

    def append_content(self, text: str) -> None:
        if not text:
            return
        self._cancel_auto_close()
        self.finished = False
        if self.content_length == 0:
            self._replace_text("")
            self.reasoning_visible = False
        self.status_label.configure(text=f"{self.model} · 正在生成")
        self._append_text(text)
        self.content_length += len(text)

    def append_reasoning(self, text: str) -> None:
        if not text:
            return
        self._cancel_auto_close()
        self.finished = False
        self.reasoning_length += len(text)
        self.status_label.configure(text=f"{self.model} · 正在思考")
        config = self._popup_config()
        if not config["show_reasoning"] or self.content_length > 0:
            if self.content_length == 0 and not self.reasoning_visible:
                self._replace_text("模型正在思考……", tag="reasoning")
                self.reasoning_visible = True
            return
        if not self.reasoning_visible:
            self._replace_text("")
            self.reasoning_visible = True
        self._append_text(text, tag="reasoning")

    def complete(self, event: dict[str, Any]) -> None:
        self.finished = True
        if self.content_length == 0:
            if self.reasoning_length > 0:
                self._replace_text("推理已结束，但模型没有返回正文内容。", tag="reasoning")
            else:
                self._replace_text("响应已完成，但没有可显示的正文内容。", tag="reasoning")
        elapsed = event.get("elapsed_ms")
        suffix = f" · {float(elapsed) / 1000:.1f}s" if isinstance(elapsed, (int, float)) else ""
        self.status_label.configure(text=f"{self.model} · 已完成{suffix}")
        self._schedule_auto_close()

    def fail(self, event: dict[str, Any]) -> None:
        self.finished = True
        error = str(event.get("error") or "请求失败")
        if self.content_length == 0:
            self._replace_text(f"请求失败：{error}", tag="error")
        self.status_label.configure(text=f"{self.model} · 请求失败")
        self._schedule_auto_close()

    def reschedule_if_finished(self) -> None:
        self.apply_config()
        if self.finished:
            self._schedule_auto_close()

    def _cancel_auto_close(self) -> None:
        if self.close_after_id:
            try:
                self.window.after_cancel(self.close_after_id)
            except tk.TclError:
                pass
            self.close_after_id = None
        if self.countdown_after_id:
            try:
                self.window.after_cancel(self.countdown_after_id)
            except tk.TclError:
                pass
            self.countdown_after_id = None

    def _schedule_auto_close(self) -> None:
        self._cancel_auto_close()
        self.remaining_seconds = int(self._popup_config()["close_seconds"])
        self._update_countdown()
        self.close_after_id = self.window.after(
            self.remaining_seconds * 1000,
            lambda: self.destroy(manual=False),
        )

    def _update_countdown(self) -> None:
        if not self.finished:
            return
        base = self.status_label.cget("text").split(" · 关闭倒计时")[0]
        self.status_label.configure(text=f"{base} · 关闭倒计时 {self.remaining_seconds}s")
        if self.remaining_seconds <= 1:
            return
        self.remaining_seconds -= 1
        self.countdown_after_id = self.window.after(1000, self._update_countdown)

    def destroy(self, manual: bool = False) -> None:
        request_id = self.request_id
        self._cancel_auto_close()
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        self.on_destroy(request_id, manual)


class PopupAgent:
    def __init__(self, event_queue: Queue, control_queue: Queue | None = None) -> None:
        self.event_queue = event_queue
        self.control_queue = control_queue
        self.config = normalize_popup_config(DEFAULT_POPUP_CONFIG)
        self.popup: SubtitleOverlay | None = None
        self.active_request_id: str | None = None
        self.pending_starts: dict[str, dict[str, Any]] = {}
        self.suppressed_requests: set[str] = set()
        self.superseded_requests: set[str] = set()

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("LLM Relay Desk Subtitle Agent")
        self.root.after(20, self._poll)

    def run(self) -> None:
        self.root.mainloop()

    def _poll(self) -> None:
        handled = 0
        while handled < 500:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            except (EOFError, OSError):
                self._shutdown()
                return
            handled += 1
            self._handle(event)
        try:
            self.root.after(20, self._poll)
        except tk.TclError:
            pass

    def _handle(self, event: Any) -> None:
        if not isinstance(event, dict):
            return
        event_type = event.get("type")

        if event_type == "popup_shutdown":
            self._shutdown()
            return

        if event_type == "popup_config":
            self.config = normalize_popup_config(event)
            if not self.config["enabled"]:
                self._close_popup()
                self.pending_starts.clear()
                self.suppressed_requests.clear()
                self.superseded_requests.clear()
            elif self.popup is not None:
                self.popup.reschedule_if_finished()
            return

        if not self.config["enabled"]:
            return

        request_id = str(event.get("request_id") or "")
        if not request_id:
            return

        if request_id in self.superseded_requests:
            if event_type in {"request_done", "request_error", "request_cancelled"}:
                self.superseded_requests.discard(request_id)
                self.pending_starts.pop(request_id, None)
            return

        if request_id in self.suppressed_requests:
            if event_type in {"request_done", "request_error", "request_cancelled"}:
                self.suppressed_requests.discard(request_id)
                self.pending_starts.pop(request_id, None)
            return

        if event_type == "request_start":
            # A single subtitle surface always follows the most recently started
            # chat. Older pending requests are suppressed before their first chunk.
            for pending_id in tuple(self.pending_starts):
                if pending_id != request_id:
                    self.pending_starts.pop(pending_id, None)
                    self.superseded_requests.add(pending_id)
            self.pending_starts[request_id] = dict(event)
            # When a previous subtitle is still visible, reuse it immediately so
            # the old answer disappears as soon as the next chat starts. A first
            # request still waits for its first response event before opening.
            if self.popup is not None and self.active_request_id != request_id:
                self._activate_request(request_id, event)
            return

        if event_type not in {
            "content_delta",
            "reasoning_delta",
            "request_done",
            "request_error",
            "request_cancelled",
        }:
            return

        if self.active_request_id != request_id:
            self._activate_request(request_id, event)

        if self.popup is None or self.active_request_id != request_id:
            return

        if event_type == "content_delta":
            self.popup.append_content(str(event.get("text", "")))
        elif event_type == "reasoning_delta":
            self.popup.append_reasoning(str(event.get("text", "")))
        elif event_type == "request_done":
            self.popup.complete(event)
        elif event_type in {"request_error", "request_cancelled"}:
            self.popup.fail(event)

    def _activate_request(self, request_id: str, event: dict[str, Any]) -> None:
        previous = self.active_request_id
        if (
            previous
            and previous != request_id
            and self.popup is not None
            and not self.popup.finished
        ):
            self.superseded_requests.add(previous)

        start_event = self.pending_starts.get(request_id) or {
            "request_id": request_id,
            "model": event.get("model", "模型响应"),
            "api": "api",
            "source": "本机",
        }
        if self.popup is None:
            self.popup = SubtitleOverlay(
                self.root,
                start_event,
                config_getter=lambda: self.config,
                on_destroy=self._remove_popup,
                on_position_saved=self._save_position,
            )
        else:
            self.popup.reset(start_event)
        self.active_request_id = request_id
        self.pending_starts.pop(request_id, None)

    def _save_position(self, x: int, y: int) -> None:
        self.config = {
            **self.config,
            "position": "custom",
            "custom_x": int(x),
            "custom_y": int(y),
            "offset_x": 0,
            "offset_y": 0,
        }
        if self.control_queue is None:
            return
        try:
            self.control_queue.put_nowait(
                {
                    "type": "popup_position_saved",
                    "x": int(x),
                    "y": int(y),
                }
            )
        except (queue.Full, BrokenPipeError, EOFError, OSError):
            pass

    def _remove_popup(self, request_id: str, manual: bool) -> None:
        self.popup = None
        if self.active_request_id == request_id:
            self.active_request_id = None
        self.pending_starts.pop(request_id, None)
        if manual:
            self.suppressed_requests.add(request_id)

    def _close_popup(self) -> None:
        popup = self.popup
        self.popup = None
        self.active_request_id = None
        if popup is not None:
            popup.destroy(manual=False)

    def _shutdown(self) -> None:
        self._close_popup()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def run_popup_worker(event_queue: Queue, control_queue: Queue | None = None) -> None:
    try:
        PopupAgent(event_queue, control_queue).run()
    except tk.TclError as exc:
        print(f"[native-popup] 无法创建桌面字幕窗口：{exc}", file=sys.stderr, flush=True)
    except Exception as exc:
        print(f"[native-popup] 字幕进程异常退出：{exc}", file=sys.stderr, flush=True)
