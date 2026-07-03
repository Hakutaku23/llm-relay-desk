"""Backward-compatible import shim for v3.x integrations."""

from llm_relay_desk.desktop.window import (
    DEFAULT_POPUP_CONFIG,
    PopupAgent,
    SubtitleOverlay,
    normalize_popup_config,
    run_popup_worker,
)

__all__ = [
    "DEFAULT_POPUP_CONFIG",
    "PopupAgent",
    "SubtitleOverlay",
    "normalize_popup_config",
    "run_popup_worker",
]
