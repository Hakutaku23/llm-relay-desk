from __future__ import annotations

from typing import Any

_REASONING_ANSWER_SEPARATOR = "\n\n—— 最终回答 ——\n\n"
_original_run_popup_worker: Any = None


def _append_content_preserving_reasoning(self: Any, text: str) -> None:
    """Append final content without clearing an already streamed reasoning trace."""

    if not text:
        return

    self._cancel_auto_close()
    self.finished = False
    config = self._popup_config()

    if self.content_length == 0:
        preserve_reasoning = (
            bool(config.get("show_reasoning", False))
            and self.reasoning_length > 0
            and self.reasoning_visible
            and bool(str(getattr(self, "display_text", "")).strip())
        )

        if preserve_reasoning:
            current = str(getattr(self, "display_text", ""))
            if not current.endswith(_REASONING_ANSWER_SEPARATOR):
                self._append_text(
                    _REASONING_ANSWER_SEPARATOR,
                    tag="reasoning",
                )
        else:
            self._replace_text("")

        self.reasoning_visible = False

    self.status_label.configure(text=f"{self.model} · 正在生成")
    self._append_text(text)
    self.content_length += len(text)


def _install_overlay_method(window_module: Any) -> None:
    overlay = window_module.SubtitleOverlay
    if getattr(
        overlay.append_content,
        "_llm_relay_true_streaming_reasoning",
        False,
    ):
        return

    _append_content_preserving_reasoning._llm_relay_true_streaming_reasoning = True
    overlay.append_content = _append_content_preserving_reasoning


def run_popup_worker_with_reasoning_stream(
    event_queue: Any,
    control_queue: Any = None,
) -> None:
    """Spawn target that reapplies the method patch inside the child process."""

    global _original_run_popup_worker

    from . import window

    if _original_run_popup_worker is None:
        _original_run_popup_worker = window.run_popup_worker

    _install_overlay_method(window)
    _original_run_popup_worker(event_queue, control_queue)


run_popup_worker_with_reasoning_stream._llm_relay_reasoning_stream_wrapper = True


def install_reasoning_stream_patch() -> None:
    """Install the popup patch before NativePopupController spawns its worker."""

    global _original_run_popup_worker

    from . import window

    _install_overlay_method(window)

    current_worker = window.run_popup_worker
    if getattr(
        current_worker,
        "_llm_relay_reasoning_stream_wrapper",
        False,
    ):
        return

    _original_run_popup_worker = current_worker
    window.run_popup_worker = run_popup_worker_with_reasoning_stream
