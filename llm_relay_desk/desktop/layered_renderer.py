from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache
import os
from pathlib import Path
import sys
from typing import Any

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont

from llm_relay_desk.desktop.fonts import resolve_font_path


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
ULW_ALPHA = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _rgba(hex_color: str, opacity: float) -> tuple[int, int, int, int]:
    try:
        red, green, blue = ImageColor.getrgb(str(hex_color))
    except (ValueError, TypeError):
        red, green, blue = 255, 255, 255
    return red, green, blue, round(255 * _bounded_float(opacity, 1.0, 0.0, 1.0))


def _font_candidates(*, bold: bool) -> list[Path]:
    windows_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    fonts = windows_dir / "Fonts"
    names = (
        ("msyhbd.ttc", "msyh.ttc", "seguisb.ttf", "segoeui.ttf", "arialbd.ttf")
        if bold
        else ("msyh.ttc", "segoeui.ttf", "arial.ttf", "msyhbd.ttc")
    )
    candidates = [fonts / name for name in names]
    candidates.extend(
        [
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
            if bold
            else Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
            if bold
            else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]
    )
    return candidates


@lru_cache(maxsize=128)
def load_font(
    size: int,
    bold: bool = False,
    family: str = "Microsoft YaHei UI",
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    safe_size = max(8, int(size))
    selected = resolve_font_path(str(family), bold=bold)
    candidates = ([selected] if selected is not None else []) + _font_candidates(bold=bold)
    seen: set[str] = set()
    for path in candidates:
        identity = str(path).casefold()
        if identity in seen:
            continue
        seen.add(identity)
        try:
            if path.exists():
                return ImageFont.truetype(str(path), safe_size)
        except OSError:
            continue
    try:
        return ImageFont.truetype("DejaVuSans.ttf", safe_size)
    except OSError:
        return ImageFont.load_default()


def _contains_cjk(text: str) -> bool:
    return any(
        "\u3400" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
        for char in str(text)
    )


def _supports_cjk(font: ImageFont.ImageFont) -> bool:
    try:
        first = bytes(font.getmask("测"))
        second = bytes(font.getmask("试"))
    except Exception:
        return False
    return bool(first and second and first != second)


def load_text_font(
    size: int,
    *,
    family: str,
    text: str,
    bold: bool = False,
) -> ImageFont.ImageFont:
    selected = load_font(size, bold=bold, family=family)
    if _contains_cjk(text) and not _supports_cjk(selected):
        return load_font(size, bold=bold, family="Microsoft YaHei UI")
    return selected


def _fit_prefix(text: str, font: ImageFont.ImageFont, max_width: int) -> int:
    if not text:
        return 0
    if font.getlength(text) <= max_width:
        return len(text)
    low, high = 1, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if font.getlength(text[:mid]) <= max_width:
            low = mid
        else:
            high = mid - 1
    return max(1, low)


def wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    """Wrap Chinese/Latin text by measured glyph width without breaking rendering."""

    lines: list[str] = []
    for paragraph in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        remaining = paragraph
        while remaining:
            count = _fit_prefix(remaining, font, max_width)
            candidate = remaining[:count]
            # Prefer a word boundary for Latin text when it does not waste too much room.
            boundary = max(candidate.rfind(" "), candidate.rfind("\t"))
            if boundary >= max(1, int(count * 0.55)):
                candidate = candidate[:boundary]
                count = boundary + 1
            lines.append(candidate.rstrip())
            remaining = remaining[count:].lstrip(" \t")
    return lines or [""]


def _line_height(font: ImageFont.ImageFont, spacing: int) -> int:
    bbox = font.getbbox("国Ag")
    return max(1, bbox[3] - bbox[1] + spacing)


def compose_subtitle_image(
    *,
    width: int,
    height: int,
    status: str,
    body: str,
    body_kind: str | None,
    positioning: bool,
    show_close: bool,
    config: dict[str, Any],
) -> Image.Image:
    """Render a high-quality RGBA subtitle surface.

    This pure function is intentionally platform-independent so its alpha behavior
    can be regression-tested even when no Windows desktop is available.
    """

    width = max(64, int(width))
    height = max(48, int(height))
    font_size = max(12, int(config.get("font_size", 24)))
    text_opacity = _bounded_float(config.get("text_opacity"), 1.0, 0.10, 1.0)
    background_opacity = _bounded_float(
        config.get("background_opacity"), 0.88, 0.0, 1.0
    )
    transparent = background_opacity <= 0.001

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    padding_x = max(18, round(font_size * (0.80 if transparent else 0.72)))
    padding_y = max(12, round(font_size * (0.50 if transparent else 0.42)))
    radius = max(10, min(24, round(font_size * 0.72)))

    if not transparent or positioning:
        effective_background_opacity = background_opacity
        if transparent and positioning:
            # Fully transparent pixels do not participate in layered-window hit
            # testing. A faint positioning surface keeps the whole box visible and
            # draggable, then disappears as soon as positioning mode ends.
            effective_background_opacity = 0.18
        bg = _rgba(
            str(config.get("background_color", "#101318")),
            effective_background_opacity,
        )
        border_alpha = 180 if positioning else min(255, bg[3] + 42)
        border_rgb = _rgba(str(config.get("border_color", "#343a46")), 1.0)[:3]
        draw.rounded_rectangle(
            (1, 1, width - 2, height - 2),
            radius=radius,
            fill=bg,
            outline=(*border_rgb, border_alpha),
            width=1 if not positioning else 2,
        )

    font_family = str(config.get("font_family", "Microsoft YaHei UI")).strip() or "Microsoft YaHei UI"
    text_align = str(config.get("text_align", "left")).strip().lower()
    if text_align not in {"left", "center", "right"}:
        text_align = "left"
    # Do not force bold in transparent mode. Some CJK fonts become visually
    # inflated when a bold face is selected automatically; the configured shadow
    # and stroke already provide contrast against bright backgrounds.
    body_font = load_text_font(
        font_size,
        bold=False,
        family=font_family,
        text=body or "",
    )
    status_font = load_text_font(
        max(11, round(font_size * 0.48)),
        bold=False,
        family=font_family,
        text=status,
    )
    close_font = load_font(max(14, round(font_size * 0.72)), bold=False, family=font_family)

    body_color_key = {
        "reasoning": "muted_color",
        "error": "error_color",
    }.get(body_kind, "text_color")
    body_color = _rgba(str(config.get(body_color_key, "#f7f8fa")), text_opacity)
    muted_color = _rgba(
        str(config.get("muted_color", "#aeb6c2")), min(1.0, text_opacity * 0.82)
    )

    header_height = 0 if transparent and not positioning else max(24, round(font_size * 0.92))
    if header_height:
        header_text = "定位模式 · 拖动后松开保存位置" if positioning else status
        draw.text((padding_x, padding_y), header_text, font=status_font, fill=muted_color)
        if show_close:
            close_text = "×"
            close_width = draw.textlength(close_text, font=close_font)
            draw.text(
                (width - padding_x - close_width, padding_y - 2),
                close_text,
                font=close_font,
                fill=muted_color,
            )

    body_top = padding_y + header_height
    body_bottom = height - padding_y
    available_height = max(20, body_bottom - body_top)
    max_width = max(20, width - padding_x * 2)
    spacing = max(4, round(font_size * 0.24))
    line_height = _line_height(body_font, spacing)
    max_lines = max(1, available_height // line_height)
    lines = wrap_text(body or "", body_font, max_width)
    visible_lines = lines[-max_lines:]
    body_text = "\n".join(visible_lines)

    text_bbox = draw.multiline_textbbox(
        (0, 0), body_text, font=body_font, spacing=spacing, align=text_align
    )
    text_width = max(1, text_bbox[2] - text_bbox[0])
    text_height = max(1, text_bbox[3] - text_bbox[1])
    if text_align == "center":
        text_x = max(padding_x, (width - text_width) // 2)
    elif text_align == "right":
        text_x = max(padding_x, width - padding_x - text_width)
    else:
        text_x = padding_x
    if transparent:
        text_y = body_top + max(0, (available_height - text_height) // 2)
    else:
        text_y = body_top + max(0, available_height - text_height)
    align = text_align

    shadow_enabled = bool(config.get("text_shadow", True))
    shadow_offset = max(1, min(8, int(config.get("shadow_offset", 2))))
    shadow_rgba = _rgba(
        str(config.get("shadow_color", "#000000")), min(0.88, text_opacity * 0.82)
    )

    if body_text and shadow_enabled:
        shadow_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        # A soft, antialiased shadow replaces the previous hard duplicated text.
        shadow_draw.multiline_text(
            (text_x + shadow_offset, text_y + shadow_offset),
            body_text,
            font=body_font,
            fill=shadow_rgba,
            spacing=spacing,
            align=align,
            stroke_width=max(1, round(font_size / 32)) if transparent else 0,
            stroke_fill=shadow_rgba,
        )
        blur_radius = max(0.8, shadow_offset * 0.72)
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur_radius))
        image = Image.alpha_composite(image, shadow_layer)
        draw = ImageDraw.Draw(image)

    stroke_width = max(1, round(font_size / 30)) if transparent else 0
    stroke_fill = _rgba(
        str(config.get("shadow_color", "#000000")), min(0.72, text_opacity * 0.68)
    )
    draw.multiline_text(
        (text_x, text_y),
        body_text,
        font=body_font,
        fill=body_color,
        spacing=spacing,
        align=align,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )
    return image


def _premultiplied_bgra(image: Image.Image) -> bytes:
    rgba = image.convert("RGBA")
    red, green, blue, alpha = rgba.split()
    red = ImageChops.multiply(red, alpha)
    green = ImageChops.multiply(green, alpha)
    blue = ImageChops.multiply(blue, alpha)
    return Image.merge("RGBA", (blue, green, red, alpha)).tobytes()


class Win32LayeredRenderer:
    """Present Pillow RGBA images through UpdateLayeredWindow."""

    def __init__(self, hwnd_getter: Any) -> None:
        self.hwnd_getter = hwnd_getter
        self.available = sys.platform == "win32"

    def present(self, image: Image.Image, *, x: int, y: int) -> bool:
        if not self.available or sys.platform != "win32":
            return False
        hwnd = self.hwnd_getter()
        if not hwnd:
            return False

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.UpdateLayeredWindow.argtypes = [
            wintypes.HWND,
            wintypes.HDC,
            ctypes.POINTER(POINT),
            ctypes.POINTER(SIZE),
            wintypes.HDC,
            ctypes.POINTER(POINT),
            wintypes.COLORREF,
            ctypes.POINTER(BLENDFUNCTION),
            wintypes.DWORD,
        ]
        user32.UpdateLayeredWindow.restype = wintypes.BOOL
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(BITMAPINFO),
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.DeleteDC.restype = wintypes.BOOL

        screen_dc = user32.GetDC(0)
        if not screen_dc:
            return False
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        if not memory_dc:
            user32.ReleaseDC(0, screen_dc)
            return False
        bitmap = None
        old_bitmap = None
        try:
            width, height = image.size
            bitmap_info = BITMAPINFO()
            bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bitmap_info.bmiHeader.biWidth = width
            bitmap_info.bmiHeader.biHeight = -height  # top-down DIB
            bitmap_info.bmiHeader.biPlanes = 1
            bitmap_info.bmiHeader.biBitCount = 32
            bitmap_info.bmiHeader.biCompression = BI_RGB

            bits = ctypes.c_void_p()
            bitmap = gdi32.CreateDIBSection(
                screen_dc,
                ctypes.byref(bitmap_info),
                DIB_RGB_COLORS,
                ctypes.byref(bits),
                None,
                0,
            )
            if not bitmap or not bits:
                return False
            old_bitmap = gdi32.SelectObject(memory_dc, bitmap)
            payload = _premultiplied_bgra(image)
            ctypes.memmove(bits, payload, len(payload))

            destination = POINT(int(x), int(y))
            size = SIZE(width, height)
            source = POINT(0, 0)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            success = user32.UpdateLayeredWindow(
                hwnd,
                screen_dc,
                ctypes.byref(destination),
                ctypes.byref(size),
                memory_dc,
                ctypes.byref(source),
                0,
                ctypes.byref(blend),
                ULW_ALPHA,
            )
            return bool(success)
        except Exception:
            self.available = False
            return False
        finally:
            if old_bitmap:
                gdi32.SelectObject(memory_dc, old_bitmap)
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if memory_dc:
                gdi32.DeleteDC(memory_dc)
            if screen_dc:
                user32.ReleaseDC(0, screen_dc)
