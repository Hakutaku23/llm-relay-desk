from __future__ import annotations

import ctypes
import queue
import sys
import tkinter as tk
from multiprocessing.queues import Queue
from typing import Any, Callable


BG = "#eef1f5"
PANEL = "#ffffff"
TEXT = "#172033"
MUTED = "#6b7280"
BORDER = "#d9e0e9"
PRIMARY = "#315efb"
SUCCESS = "#16845b"
DANGER = "#c53b4a"
CODE_BG = "#111827"
CODE_FG = "#e3eaf4"
FONT_UI = ("Microsoft YaHei UI", 10)
FONT_UI_SMALL = ("Microsoft YaHei UI", 9)
FONT_UI_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 12, "bold")
FONT_MONO = ("Microsoft YaHei UI", 10)


class ResponsePopup:
    def __init__(
        self,
        root: tk.Tk,
        event: dict[str, Any],
        close_seconds_getter: Callable[[], int],
        on_destroy: Callable[[str, bool], None],
        position_index: int,
    ) -> None:
        self.root = root
        self.request_id = str(event.get("request_id", "unknown"))
        self.close_seconds_getter = close_seconds_getter
        self.on_destroy = on_destroy
        self.content_length = 0
        self.reasoning_length = 0
        self.close_after_id: str | None = None
        self.countdown_after_id: str | None = None
        self.remaining_seconds = 0
        self.finished = False

        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.title(f"LLM 实时响应 · {event.get('model') or '未知模型'}")
        self.window.configure(bg=BG)
        self.window.minsize(480, 320)
        self.window.protocol("WM_DELETE_WINDOW", lambda: self.destroy(manual=True))

        width, height = 620, 500
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        offset = (position_index % 5) * 26
        x = max(12, screen_width - width - 28 - offset)
        y = max(12, screen_height - height - 76 - offset)
        self.window.geometry(f"{width}x{height}+{x}+{y}")

        self._build(event)
        self._show_without_stealing_focus()

    def _build(self, event: dict[str, Any]) -> None:
        outer = tk.Frame(self.window, bg=BG, padx=14, pady=14)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        header.pack(fill="x")

        title_row = tk.Frame(header, bg=PANEL, padx=14, pady=11)
        title_row.pack(fill="x")

        tk.Label(
            title_row,
            text=str(event.get("model") or "模型响应"),
            bg=PANEL,
            fg=TEXT,
            font=FONT_TITLE,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        self.status_label = tk.Label(
            title_row,
            text="正在生成",
            bg="#eef3ff",
            fg=PRIMARY,
            font=FONT_UI_BOLD,
            padx=10,
            pady=4,
        )
        self.status_label.pack(side="right")

        meta = (
            f"{event.get('api', '').upper() or 'API'}  ·  "
            f"{event.get('source') or '本机'}  ·  "
            f"{self.request_id}"
        )
        tk.Label(
            header,
            text=meta,
            bg=PANEL,
            fg=MUTED,
            font=FONT_UI_SMALL,
            anchor="w",
            padx=14,
            pady=0,
        ).pack(fill="x")

        self.close_hint = tk.Label(
            header,
            text="窗口将在响应完成后自动关闭",
            bg=PANEL,
            fg=MUTED,
            font=FONT_UI_SMALL,
            anchor="w",
            padx=14,
            pady=9,
        )
        self.close_hint.pack(fill="x")

        notebook_shell = tk.Frame(
            outer,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        notebook_shell.pack(fill="both", expand=True, pady=(12, 0))

        tab_bar = tk.Frame(notebook_shell, bg="#f7f9fc")
        tab_bar.pack(fill="x")
        self.answer_tab = tk.Button(
            tab_bar,
            text="最终回答",
            command=lambda: self._select_tab("answer"),
            relief="flat",
            bd=0,
            bg=PANEL,
            fg=PRIMARY,
            activebackground=PANEL,
            activeforeground=PRIMARY,
            font=FONT_UI_BOLD,
            padx=16,
            pady=9,
            cursor="hand2",
        )
        self.answer_tab.pack(side="left")
        self.reasoning_tab = tk.Button(
            tab_bar,
            text="推理内容",
            command=lambda: self._select_tab("reasoning"),
            relief="flat",
            bd=0,
            bg="#f7f9fc",
            fg=MUTED,
            activebackground=PANEL,
            activeforeground=PRIMARY,
            font=FONT_UI,
            padx=16,
            pady=9,
            cursor="hand2",
        )
        self.reasoning_tab.pack(side="left")

        body = tk.Frame(notebook_shell, bg=CODE_BG)
        body.pack(fill="both", expand=True)

        self.answer_frame, self.answer_text = self._create_text_panel(body)
        self.reasoning_frame, self.reasoning_text = self._create_text_panel(body)
        self.answer_frame.pack(fill="both", expand=True)
        self.reasoning_frame.pack_forget()

        self.answer_text.configure(state="normal")
        self.answer_text.insert("end", "正在等待模型输出……")
        self.answer_text.configure(state="disabled")

    def _create_text_panel(self, parent: tk.Widget) -> tuple[tk.Frame, tk.Text]:
        frame = tk.Frame(parent, bg=CODE_BG)
        scrollbar = tk.Scrollbar(frame, orient="vertical")
        text = tk.Text(
            frame,
            wrap="word",
            bg=CODE_BG,
            fg=CODE_FG,
            insertbackground=CODE_FG,
            selectbackground="#375a9e",
            relief="flat",
            bd=0,
            padx=16,
            pady=14,
            font=FONT_MONO,
            spacing1=2,
            spacing3=5,
            yscrollcommand=scrollbar.set,
        )
        scrollbar.configure(command=text.yview)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.configure(state="disabled")
        return frame, text

    def _show_without_stealing_focus(self) -> None:
        self.window.update_idletasks()
        if sys.platform == "win32":
            try:
                user32 = ctypes.windll.user32
                hwnd = self.window.winfo_id()
                parent = user32.GetParent(hwnd)
                if parent:
                    hwnd = parent
                SW_SHOWNOACTIVATE = 4
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOACTIVATE = 0x0010
                SWP_SHOWWINDOW = 0x0040
                user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                user32.SetWindowPos(
                    hwnd,
                    0,
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

    def _select_tab(self, tab: str) -> None:
        if tab == "reasoning":
            self.answer_frame.pack_forget()
            self.reasoning_frame.pack(fill="both", expand=True)
            self.answer_tab.configure(bg="#f7f9fc", fg=MUTED, font=FONT_UI)
            self.reasoning_tab.configure(bg=PANEL, fg=PRIMARY, font=FONT_UI_BOLD)
        else:
            self.reasoning_frame.pack_forget()
            self.answer_frame.pack(fill="both", expand=True)
            self.reasoning_tab.configure(bg="#f7f9fc", fg=MUTED, font=FONT_UI)
            self.answer_tab.configure(bg=PANEL, fg=PRIMARY, font=FONT_UI_BOLD)

    @staticmethod
    def _append(widget: tk.Text, text: str, clear_placeholder: bool = False) -> None:
        if not text:
            return
        widget.configure(state="normal")
        if clear_placeholder:
            widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.see("end")
        widget.configure(state="disabled")

    def append_content(self, text: str) -> None:
        self._cancel_auto_close()
        self.finished = False
        self.status_label.configure(text="正在生成", bg="#eef3ff", fg=PRIMARY)
        self._append(self.answer_text, text, clear_placeholder=self.content_length == 0)
        self.content_length += len(text)

    def append_reasoning(self, text: str) -> None:
        self._cancel_auto_close()
        self.finished = False
        self.status_label.configure(text="正在推理", bg="#fff7e8", fg="#9a6500")
        self._append(self.reasoning_text, text)
        self.reasoning_length += len(text)
        self.reasoning_tab.configure(text="推理内容 ●")

    def complete(self, event: dict[str, Any]) -> None:
        self.finished = True
        elapsed = event.get("elapsed_ms")
        elapsed_text = f" · {float(elapsed) / 1000:.1f}s" if isinstance(elapsed, (int, float)) else ""
        self.status_label.configure(text=f"已完成{elapsed_text}", bg="#eaf7f1", fg=SUCCESS)
        if self.content_length == 0 and self.reasoning_length > 0:
            self._select_tab("reasoning")
        elif self.content_length == 0:
            message = "响应已完成，但没有可显示的正文内容。"
            self._append(self.answer_text, message, clear_placeholder=True)
            self.content_length = len(message)
        self._schedule_auto_close()

    def fail(self, event: dict[str, Any]) -> None:
        self.finished = True
        error = str(event.get("error") or "请求失败")
        self.status_label.configure(text="请求失败", bg="#fff0f1", fg=DANGER)
        if self.content_length == 0:
            self._append(self.answer_text, f"请求失败：{error}", clear_placeholder=True)
            self.content_length = len(error)
        self._schedule_auto_close()

    def reschedule_if_finished(self) -> None:
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
        self.remaining_seconds = max(1, int(self.close_seconds_getter()))
        self._update_countdown()
        self.close_after_id = self.window.after(
            self.remaining_seconds * 1000,
            lambda: self.destroy(manual=False),
        )

    def _update_countdown(self) -> None:
        if not self.finished:
            return
        self.close_hint.configure(text=f"{self.remaining_seconds} 秒后自动关闭 · 可手动关闭窗口")
        if self.remaining_seconds <= 1:
            return
        self.remaining_seconds -= 1
        self.countdown_after_id = self.window.after(1000, self._update_countdown)

    def destroy(self, manual: bool = False) -> None:
        self._cancel_auto_close()
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        self.on_destroy(self.request_id, manual)


class PopupAgent:
    def __init__(self, event_queue: Queue) -> None:
        self.event_queue = event_queue
        self.enabled = True
        self.close_seconds = 30
        self.windows: dict[str, ResponsePopup] = {}
        self.pending_starts: dict[str, dict[str, Any]] = {}
        self.suppressed_requests: set[str] = set()
        self.position_counter = 0

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("LLM Relay Desk Popup Agent")
        self.root.after(30, self._poll)

    def run(self) -> None:
        self.root.mainloop()

    def _poll(self) -> None:
        handled = 0
        while handled < 300:
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
            self.root.after(30, self._poll)
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
            self.enabled = bool(event.get("enabled", True))
            try:
                self.close_seconds = max(1, min(3600, int(event.get("close_seconds", 30))))
            except (TypeError, ValueError):
                self.close_seconds = 30
            if not self.enabled:
                self._close_all()
                self.pending_starts.clear()
                self.suppressed_requests.clear()
            else:
                for popup in tuple(self.windows.values()):
                    popup.reschedule_if_finished()
            return

        if not self.enabled:
            return

        request_id = str(event.get("request_id") or "")
        if not request_id:
            return

        if request_id in self.suppressed_requests:
            if event_type in {"request_done", "request_error", "request_cancelled"}:
                self.suppressed_requests.discard(request_id)
                self.pending_starts.pop(request_id, None)
            return

        popup = self.windows.get(request_id)
        if event_type == "request_start":
            self.pending_starts[request_id] = dict(event)
            while len(self.pending_starts) > 200:
                oldest = next(iter(self.pending_starts))
                self.pending_starts.pop(oldest, None)
            return

        if popup is None and event_type in {
            "content_delta",
            "reasoning_delta",
            "request_done",
            "request_error",
            "request_cancelled",
        }:
            start_event = self.pending_starts.get(request_id) or {
                "request_id": request_id,
                "model": event.get("model", "模型响应"),
                "api": "api",
                "source": "本机",
            }
            popup = self._create_popup(start_event)

        if popup is None:
            return

        if event_type == "content_delta":
            popup.append_content(str(event.get("text", "")))
        elif event_type == "reasoning_delta":
            popup.append_reasoning(str(event.get("text", "")))
        elif event_type == "request_done":
            popup.complete(event)
        elif event_type in {"request_error", "request_cancelled"}:
            popup.fail(event)

    def _create_popup(self, event: dict[str, Any]) -> ResponsePopup:
        request_id = str(event.get("request_id"))
        existing = self.windows.get(request_id)
        if existing:
            return existing
        popup = ResponsePopup(
            self.root,
            event,
            close_seconds_getter=lambda: self.close_seconds,
            on_destroy=self._remove_popup,
            position_index=self.position_counter,
        )
        self.position_counter += 1
        self.windows[request_id] = popup
        self.pending_starts.pop(request_id, None)
        return popup

    def _remove_popup(self, request_id: str, manual: bool) -> None:
        self.windows.pop(request_id, None)
        self.pending_starts.pop(request_id, None)
        if manual:
            self.suppressed_requests.add(request_id)

    def _close_all(self) -> None:
        for popup in tuple(self.windows.values()):
            popup.destroy(manual=False)
        self.windows.clear()

    def _shutdown(self) -> None:
        self._close_all()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def run_popup_worker(event_queue: Queue) -> None:
    try:
        PopupAgent(event_queue).run()
    except tk.TclError as exc:
        # Headless Linux, Windows service sessions, and Python builds without Tk
        # cannot create desktop windows. The API server remains unaffected.
        print(f"[native-popup] 无法创建桌面窗口：{exc}", file=sys.stderr, flush=True)
    except Exception as exc:
        print(f"[native-popup] 弹窗进程异常退出：{exc}", file=sys.stderr, flush=True)
