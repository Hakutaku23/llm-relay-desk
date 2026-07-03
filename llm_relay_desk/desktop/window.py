from __future__ import annotations

import ctypes
from ctypes import wintypes
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
    "click_through": False,
    "transparent_background": False,
    "text_shadow": True,
    "shadow_color": "#000000",
    "shadow_offset": 2,
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
        "click_through": bool(source.get("click_through", False)),
        "transparent_background": bool(source.get("transparent_background", False)),
        "text_shadow": bool(source.get("text_shadow", True)),
        "shadow_color": _color_value(source.get("shadow_color"), "#000000"),
        "shadow_offset": _int_value(source.get("shadow_offset"), 2, 1, 8),
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
        self.positioning_mode = False
        self.click_through_applied = False
        self.interaction_after_id: str | None = None
        self.transparency_after_id: str | None = None
        self.transparent_background_applied = False
        self.transparent_key = "#010203"
        self.display_text = ""
        self.display_tag: str | None = None
        self.window_visible = False

        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)

        self._build()
        self.reset(event)

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

        self.interaction_label = tk.Label(
            self.header,
            text="定位模式",
            font=(FONT_FAMILY, 9, "bold"),
            padx=8,
            pady=2,
        )

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

        self.text_area = tk.Frame(self.shell, bd=0, highlightthickness=0)
        self.text_area.pack(fill="both", expand=True)

        text_options = {
            "wrap": "word",
            "relief": "flat",
            "bd": 0,
            "padx": 0,
            "pady": 0,
            "spacing1": 2,
            "spacing3": 5,
            "cursor": "fleur",
            "takefocus": False,
        }
        self.text = tk.Text(self.text_area, **text_options)
        self.text.configure(state="disabled")
        self.text.place(x=0, y=0, relwidth=1, relheight=1)

        self.canvas = tk.Canvas(
            self.text_area,
            bd=0,
            highlightthickness=0,
            cursor="fleur",
            takefocus=False,
        )
        self.canvas_shadow_item = self.canvas.create_text(
            0,
            0,
            anchor="nw",
            justify="left",
            text="",
        )
        self.canvas_text_item = self.canvas.create_text(
            0,
            0,
            anchor="nw",
            justify="left",
            text="",
        )
        self.canvas.bind("<Configure>", self._on_canvas_configure, add="+")

        for widget in (
            self.shell,
            self.header,
            self.status_label,
            self.text_area,
            self.canvas,
            self.text,
        ):
            widget.bind("<ButtonPress-1>", self._start_drag, add="+")
            widget.bind("<B1-Motion>", self._drag, add="+")
            widget.bind("<ButtonRelease-1>", self._finish_drag, add="+")

    def _popup_config(self) -> dict[str, Any]:
        return normalize_popup_config(self.config_getter())

    def reset(self, event: dict[str, Any]) -> None:
        self._cancel_auto_close()
        self._cancel_interaction_apply()
        self._cancel_transparency_apply()
        # Remove the pass-through style before repainting. Applying
        # WS_EX_TRANSPARENT while Tk is still creating or updating its child
        # controls can leave the layered window unpainted on some Windows builds.
        self._set_click_through(False)
        self.request_id = str(event.get("request_id") or "unknown")
        self.model = str(event.get("model") or "模型响应")
        self.content_length = 0
        self.reasoning_length = 0
        self.reasoning_visible = False
        self.finished = False
        self.status_label.configure(text=f"{self.model} · 正在生成")
        self._replace_text("正在等待模型输出……", tag="reasoning")
        self.apply_config(apply_interaction=False)
        self._show_without_stealing_focus()
        self.window_visible = True
        self._force_redraw()
        self._schedule_transparency_state(delay_ms=40)
        self._schedule_interaction_state(delay_ms=120)

    def apply_config(self, *, apply_interaction: bool = True) -> None:
        config = self._popup_config()
        transparent = bool(
            config["transparent_background"]
            and sys.platform == "win32"
            and self.window_visible
        )
        self._apply_visual_config(config, transparent=transparent)
        self._position_window(config)
        if self.window_visible:
            self._schedule_transparency_state()
        if apply_interaction:
            self._schedule_interaction_state(delay_ms=100)

    def _apply_visual_config(
        self,
        config: dict[str, Any],
        *,
        transparent: bool,
    ) -> None:
        bg = config["background_color"]
        text_color = config["text_color"]
        muted = config["muted_color"]
        border = config["border_color"]
        error = config["error_color"]
        paint_bg = self.transparent_key if transparent else bg

        try:
            self.window.attributes("-alpha", config["opacity"])
        except tk.TclError:
            pass

        self.window.configure(bg=paint_bg)
        self.shell.configure(
            bg=paint_bg,
            highlightbackground=paint_bg if transparent else border,
            highlightthickness=0 if transparent else 1,
            padx=8 if transparent else 18,
            pady=4 if transparent else 12,
        )
        self.header.configure(bg=paint_bg)
        self.text_area.configure(bg=paint_bg)
        self.status_label.configure(bg=paint_bg, fg=muted)
        self.close_button.configure(
            bg=paint_bg,
            fg=muted,
            activebackground=paint_bg,
            activeforeground=text_color,
        )
        self.text.configure(
            bg=paint_bg,
            fg=text_color,
            insertbackground=text_color,
            selectbackground=border,
            font=(FONT_FAMILY, config["font_size"]),
        )
        self.text.tag_configure("reasoning", foreground=muted)
        self.text.tag_configure("error", foreground=error)
        self.interaction_label.configure(bg=paint_bg, fg=text_color)

        display_color = (
            error
            if self.display_tag == "error"
            else muted
            if self.display_tag == "reasoning"
            else text_color
        )
        self.canvas.configure(bg=paint_bg)
        self.canvas.itemconfigure(
            self.canvas_text_item,
            fill=display_color,
            font=(FONT_FAMILY, config["font_size"]),
        )
        self.canvas.itemconfigure(
            self.canvas_shadow_item,
            fill=config["shadow_color"],
            font=(FONT_FAMILY, config["font_size"]),
            state="normal" if config["text_shadow"] else "hidden",
        )

        if transparent:
            self.text.place_forget()
            self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        else:
            self.canvas.place_forget()
            self.text.place(x=0, y=0, relwidth=1, relheight=1)
        self._render_canvas_text(config)

    def _on_canvas_configure(self, _: tk.Event) -> None:
        self._render_canvas_text(self._popup_config())

    def _render_canvas_text(self, config: dict[str, Any] | None = None) -> None:
        config = config or self._popup_config()
        try:
            width = max(20, int(self.canvas.winfo_width()) - 4)
            height = max(20, int(self.canvas.winfo_height()) - 4)
            self.canvas.itemconfigure(
                self.canvas_text_item,
                text=self.display_text,
                width=width,
            )
            self.canvas.itemconfigure(
                self.canvas_shadow_item,
                text=self.display_text,
                width=width,
                state="normal" if config["text_shadow"] else "hidden",
            )
            self.canvas.update_idletasks()
            bbox = self.canvas.bbox(self.canvas_text_item)
            text_height = (bbox[3] - bbox[1]) if bbox else 0
            y = min(0, height - text_height)
            offset = int(config["shadow_offset"])
            self.canvas.coords(self.canvas_text_item, 0, y)
            self.canvas.coords(self.canvas_shadow_item, offset, y + offset)
        except tk.TclError:
            pass

    def _position_window(self, config: dict[str, Any]) -> None:
        width = int(config["width"])
        height = int(config["height"])
        position = str(config["position"])
        left, top, screen_width, screen_height = _virtual_screen(self.window)

        if position == "custom":
            x = int(config["custom_x"])
            y = int(config["custom_y"])
        else:
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

        # Monitor layouts can change after a position was saved. Keep the whole
        # subtitle inside the current virtual desktop so the positioning preview
        # can always be found and dragged back into place.
        max_x = left + max(0, screen_width - width)
        max_y = top + max(0, screen_height - height)
        x = max(left, min(x, max_x))
        y = max(top, min(y, max_y))
        self.window.geometry(f"{width}x{height}{x:+d}{y:+d}")

    def _start_drag(self, event: tk.Event) -> str:
        config = self._popup_config()
        if config["click_through"] and not self.positioning_mode:
            return "break"
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

    def set_positioning_mode(self, enabled: bool) -> None:
        self.positioning_mode = bool(enabled)
        self.dragging = False
        self._cancel_interaction_apply()
        if self.positioning_mode:
            # Positioning must be interactive before the preview is painted.
            self._set_click_through(False)
            self._apply_interaction_state(self._popup_config())
            self._show_without_stealing_focus()
            self._force_redraw()
        else:
            self._schedule_interaction_state()

    def _cancel_transparency_apply(self) -> None:
        if self.transparency_after_id is None:
            return
        try:
            self.window.after_cancel(self.transparency_after_id)
        except tk.TclError:
            pass
        self.transparency_after_id = None

    def _schedule_transparency_state(self, delay_ms: int = 20) -> None:
        self._cancel_transparency_apply()
        try:
            self.transparency_after_id = self.window.after(
                max(0, int(delay_ms)),
                self._apply_scheduled_transparency_state,
            )
        except tk.TclError:
            self.transparency_after_id = None

    def _apply_scheduled_transparency_state(self) -> None:
        self.transparency_after_id = None
        config = self._popup_config()
        enabled = bool(config["transparent_background"] and sys.platform == "win32")
        if enabled:
            self._apply_visual_config(config, transparent=True)
            self._force_redraw()
            self._set_transparent_background(True)
        else:
            self._set_transparent_background(False)
            self._apply_visual_config(config, transparent=False)
        self._force_redraw()

    def _set_transparent_background(self, enabled: bool) -> None:
        """Apply a Windows color-key transparency after the first window paint."""

        if sys.platform != "win32":
            self.transparent_background_applied = False
            return
        try:
            self.window.attributes(
                "-transparentcolor",
                self.transparent_key if enabled else "",
            )
            self.transparent_background_applied = bool(enabled)
        except tk.TclError:
            # Some Tk builds do not expose -transparentcolor. Keep the normal
            # filled background rather than showing the color-key fill.
            self.transparent_background_applied = False
            self._apply_visual_config(self._popup_config(), transparent=False)

    def _cancel_interaction_apply(self) -> None:
        if self.interaction_after_id is None:
            return
        try:
            self.window.after_cancel(self.interaction_after_id)
        except tk.TclError:
            pass
        self.interaction_after_id = None

    def _schedule_interaction_state(self, delay_ms: int = 60) -> None:
        self._cancel_interaction_apply()
        try:
            self.interaction_after_id = self.window.after(
                max(0, int(delay_ms)),
                self._apply_scheduled_interaction_state,
            )
        except tk.TclError:
            self.interaction_after_id = None

    def _apply_scheduled_interaction_state(self) -> None:
        self.interaction_after_id = None
        self._apply_interaction_state(self._popup_config())
        self._force_redraw()

    def _native_hwnd(self) -> int | None:
        if sys.platform != "win32":
            return None
        try:
            user32 = ctypes.windll.user32
            get_parent = user32.GetParent
            get_parent.argtypes = [wintypes.HWND]
            get_parent.restype = wintypes.HWND
            hwnd = int(self.window.winfo_id())
            parent = int(get_parent(hwnd) or 0)
            return parent or hwnd
        except Exception:
            return None

    def _set_click_through(self, enabled: bool) -> None:
        """Toggle mouse pass-through without changing Tk's paint model.

        Only WS_EX_TRANSPARENT is changed here. Tool-window, layered and
        no-activate styles are owned by _show_without_stealing_focus(). Keeping
        those responsibilities separate avoids blank layered windows on Windows.
        """

        requested = bool(enabled)
        hwnd = self._native_hwnd()
        if hwnd is None:
            self.click_through_applied = False
            return
        try:
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            SW_SHOWNOACTIVATE = 4
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            SWP_FRAMECHANGED = 0x0020

            if hasattr(user32, "GetWindowLongPtrW"):
                get_style = user32.GetWindowLongPtrW
                set_style = user32.SetWindowLongPtrW
                get_style.restype = ctypes.c_ssize_t
                set_style.restype = ctypes.c_ssize_t
                set_value_type = ctypes.c_ssize_t
            else:
                get_style = user32.GetWindowLongW
                set_style = user32.SetWindowLongW
                get_style.restype = ctypes.c_long
                set_style.restype = ctypes.c_long
                set_value_type = ctypes.c_long
            get_style.argtypes = [wintypes.HWND, ctypes.c_int]
            set_style.argtypes = [wintypes.HWND, ctypes.c_int, set_value_type]
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            style = int(get_style(hwnd, GWL_EXSTYLE))
            new_style = (
                style | WS_EX_TRANSPARENT
                if requested
                else style & ~WS_EX_TRANSPARENT
            )
            if new_style != style:
                set_style(hwnd, GWL_EXSTYLE, new_style)
            if self.window_visible:
                user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                user32.SetWindowPos(
                    hwnd,
                    0,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOSIZE
                    | SWP_NOMOVE
                    | SWP_NOZORDER
                    | SWP_NOACTIVATE
                    | SWP_SHOWWINDOW
                    | SWP_FRAMECHANGED,
                )
            self.click_through_applied = requested
        except Exception:
            # Fail open: a visible interactive subtitle is preferable to a
            # pass-through subtitle that cannot be seen or repositioned.
            self.click_through_applied = False

    def _force_redraw(self) -> None:
        if not self.window_visible:
            return
        try:
            self.window.update_idletasks()
        except tk.TclError:
            return
        hwnd = self._native_hwnd()
        if hwnd is None:
            return
        try:
            user32 = ctypes.windll.user32
            user32.RedrawWindow.argtypes = [
                wintypes.HWND,
                ctypes.c_void_p,
                wintypes.HRGN,
                wintypes.UINT,
            ]
            user32.RedrawWindow.restype = wintypes.BOOL
            RDW_INVALIDATE = 0x0001
            RDW_UPDATENOW = 0x0100
            RDW_ALLCHILDREN = 0x0080
            RDW_FRAME = 0x0400
            user32.RedrawWindow(
                hwnd,
                None,
                None,
                RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN | RDW_FRAME,
            )
        except Exception:
            pass

    def _apply_interaction_state(self, config: dict[str, Any]) -> None:
        requested_click_through = (
            bool(config["click_through"])
            and not self.positioning_mode
            and self.window_visible
        )
        self._set_click_through(requested_click_through)
        click_through = self.click_through_applied

        cursor = "fleur" if not click_through else "arrow"
        for widget in (
            self.shell,
            self.header,
            self.status_label,
            self.text_area,
            self.canvas,
            self.text,
        ):
            try:
                widget.configure(cursor=cursor)
            except tk.TclError:
                pass

        if self.positioning_mode:
            if not self.close_button.winfo_manager():
                self.close_button.pack(side="right")
            if not self.interaction_label.winfo_manager():
                self.interaction_label.pack(side="right", before=self.close_button)
        else:
            self.interaction_label.pack_forget()
            if click_through:
                self.close_button.pack_forget()
            elif not self.close_button.winfo_manager():
                self.close_button.pack(side="right")

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
                self.window_visible = True
                return
            except Exception:
                pass
        self.window.deiconify()
        self.window_visible = True

    def _replace_text(self, text: str, tag: str | None = None) -> None:
        self.display_text = text
        self.display_tag = tag
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if tag:
            self.text.insert("end", text, tag)
        else:
            self.text.insert("end", text)
        self.text.see("end")
        self.text.configure(state="disabled")
        self._apply_visual_config(
            self._popup_config(),
            transparent=bool(
                self._popup_config()["transparent_background"]
                and sys.platform == "win32"
                and self.window_visible
            ),
        )
        self._force_redraw()

    def _append_text(self, text: str, tag: str | None = None) -> None:
        if not text:
            return
        self.display_tag = tag
        self.display_text = (self.display_text + text)[-DISPLAY_CHAR_LIMIT:]
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
        self._apply_visual_config(
            self._popup_config(),
            transparent=bool(
                self._popup_config()["transparent_background"]
                and sys.platform == "win32"
                and self.window_visible
            ),
        )
        self._force_redraw()

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
        self._cancel_interaction_apply()
        self._cancel_transparency_apply()
        self.window_visible = False
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
        self.positioning_mode = False
        self.positioning_timeout_after_id: str | None = None

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

        if event_type == "popup_interaction_mode":
            self._set_positioning_mode(
                event.get("mode") == "positioning",
                timeout_seconds=int(event.get("timeout_seconds", 60)),
            )
            return

        if event_type == "popup_config":
            self.config = normalize_popup_config(event)
            if not self.config["enabled"]:
                self._set_positioning_mode(False)
                self._close_popup()
                self.pending_starts.clear()
                self.suppressed_requests.clear()
                self.superseded_requests.clear()
            elif self.popup is not None:
                self.popup.apply_config(apply_interaction=False)
                self.popup.set_positioning_mode(self.positioning_mode)
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
                config_getter=lambda: {
                    **self.config,
                    "click_through": False,
                }
                if self.positioning_mode
                else self.config,
                on_destroy=self._remove_popup,
                on_position_saved=self._save_position,
            )
        else:
            self.popup.reset(start_event)
        self.popup.set_positioning_mode(self.positioning_mode)
        self.active_request_id = request_id
        self.pending_starts.pop(request_id, None)

    def _set_positioning_mode(
        self,
        enabled: bool,
        *,
        timeout_seconds: int = 60,
    ) -> None:
        if self.positioning_timeout_after_id is not None:
            try:
                self.root.after_cancel(self.positioning_timeout_after_id)
            except (AttributeError, tk.TclError):
                pass
            self.positioning_timeout_after_id = None

        self.positioning_mode = bool(enabled)
        if self.popup is not None:
            self.popup.set_positioning_mode(self.positioning_mode)

        if self.positioning_mode:
            timeout_ms = max(5, min(300, int(timeout_seconds))) * 1000
            try:
                self.positioning_timeout_after_id = self.root.after(
                    timeout_ms,
                    lambda: self._set_positioning_mode(False),
                )
            except tk.TclError:
                self.positioning_timeout_after_id = None

    def _save_position(self, x: int, y: int) -> None:
        self.config = {
            **self.config,
            "position": "custom",
            "custom_x": int(x),
            "custom_y": int(y),
            "offset_x": 0,
            "offset_y": 0,
        }
        if self.control_queue is not None:
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
        self._set_positioning_mode(False)

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
        self._set_positioning_mode(False)
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
