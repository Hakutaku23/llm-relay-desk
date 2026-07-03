from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable

_STYLE_WORDS = re.compile(
    r"\b(?:thin|extralight|ultralight|light|regular|book|medium|semibold|demibold|"
    r"bold|extrabold|ultrabold|black|heavy|italic|oblique)\b",
    flags=re.IGNORECASE,
)
_TYPE_SUFFIX = re.compile(r"\s*\((?:TrueType|OpenType|All res)\)\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class FontFace:
    family: str
    path: Path
    style_text: str


def _clean_family_name(value: str) -> str:
    cleaned = _TYPE_SUFFIX.sub("", str(value)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _base_family(value: str) -> str:
    cleaned = _STYLE_WORDS.sub("", _clean_family_name(value))
    return re.sub(r"\s+", " ", cleaned).strip(" -_")


def _candidate_aliases(value_name: str) -> set[str]:
    cleaned = _clean_family_name(value_name)
    aliases: set[str] = set()
    for part in re.split(r"\s*&\s*", cleaned):
        part = part.strip()
        if not part:
            continue
        aliases.add(part)
        base = _base_family(part)
        if base:
            aliases.add(base)
    return aliases


def _resolve_windows_font_path(value: str) -> Path:
    expanded = os.path.expandvars(str(value))
    path = Path(expanded)
    if path.is_absolute():
        return path
    windows_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    return windows_dir / "Fonts" / path


def _windows_faces() -> list[FontFace]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    locations = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    )
    faces: list[FontFace] = []
    seen: set[tuple[str, str]] = set()
    for root, key_name in locations:
        try:
            key = winreg.OpenKey(root, key_name)
        except OSError:
            continue
        try:
            index = 0
            while True:
                try:
                    value_name, value_data, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                if not isinstance(value_data, str):
                    continue
                path = _resolve_windows_font_path(value_data)
                if path.suffix.lower() not in {".ttf", ".ttc", ".otf", ".otc"}:
                    continue
                for alias in _candidate_aliases(value_name):
                    identity = (alias.casefold(), str(path).casefold())
                    if identity in seen:
                        continue
                    seen.add(identity)
                    faces.append(FontFace(alias, path, _clean_family_name(value_name)))
        finally:
            winreg.CloseKey(key)
    return faces


def _fontconfig_faces() -> list[FontFace]:
    if sys.platform == "win32":
        return []
    try:
        result = subprocess.run(
            ["fc-list", "--format", "%{family}\t%{style}\t%{file}\n"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    faces: list[FontFace] = []
    seen: set[tuple[str, str]] = set()
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        family_text, style, path_text = parts
        path = Path(path_text.strip())
        for family in family_text.split(","):
            family = family.strip()
            if not family:
                continue
            identity = (family.casefold(), str(path))
            if identity in seen:
                continue
            seen.add(identity)
            faces.append(FontFace(family, path, style.strip()))
    return faces


def _fallback_faces() -> list[FontFace]:
    candidates = [
        ("Microsoft YaHei UI", Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyh.ttc"),
        ("Microsoft YaHei", Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyh.ttc"),
        ("Segoe UI", Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf"),
        ("Arial", Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf"),
        ("Noto Sans CJK SC", Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")),
        ("DejaVu Sans", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")),
    ]
    return [FontFace(name, path, "Regular") for name, path in candidates if path.exists()]


@lru_cache(maxsize=1)
def installed_font_faces() -> tuple[FontFace, ...]:
    faces = _windows_faces() or _fontconfig_faces()
    known = {(face.family.casefold(), str(face.path).casefold()) for face in faces}
    for face in _fallback_faces():
        identity = (face.family.casefold(), str(face.path).casefold())
        if identity not in known:
            faces.append(face)
            known.add(identity)
    return tuple(faces)


@lru_cache(maxsize=1)
def list_installed_font_families() -> tuple[str, ...]:
    names = {face.family.strip() for face in installed_font_faces() if face.family.strip()}
    preferred = ["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Arial"]
    ordered = [name for name in preferred if name in names]
    ordered.extend(sorted(names - set(ordered), key=str.casefold))
    return tuple(ordered)


def _style_score(face: FontFace, *, bold: bool) -> tuple[int, int, str]:
    text = f"{face.style_text} {face.path.stem}".casefold()
    bold_markers = ("bold", "semibold", "demibold", "heavy", "black", "bd")
    italic_markers = ("italic", "oblique")
    has_bold = any(marker in text for marker in bold_markers)
    has_italic = any(marker in text for marker in italic_markers)
    primary = 0 if has_bold == bold else 1
    return primary, 1 if has_italic else 0, str(face.path).casefold()


def resolve_font_path(family: str, *, bold: bool = False) -> Path | None:
    requested = _clean_family_name(family or "Microsoft YaHei UI")
    requested_folded = requested.casefold()
    faces = [face for face in installed_font_faces() if face.family.casefold() == requested_folded]
    if not faces:
        requested_base = _base_family(requested).casefold()
        faces = [face for face in installed_font_faces() if _base_family(face.family).casefold() == requested_base]
    existing = [face for face in faces if face.path.exists()]
    if existing:
        return min(existing, key=lambda face: _style_score(face, bold=bold)).path
    return None


def font_catalog_payload() -> dict[str, object]:
    fonts = list(list_installed_font_families())
    return {
        "fonts": fonts,
        "default": "Microsoft YaHei UI",
        "count": len(fonts),
        "source": "windows_registry" if sys.platform == "win32" else "fontconfig",
    }
