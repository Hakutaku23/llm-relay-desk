from __future__ import annotations

from typing import Any

from llm_relay_desk.storage import JsonStore

from .controller import NativePopupController
from .subtitle_events import SubtitleEventRouter


# The desktop renderer keeps at most 50,000 characters. Reserve room for the
# answer so a very long reasoning trace cannot push the final content out.
_REASONING_DISPLAY_LIMIT = 40_000
_REASONING_ANSWER_SEPARATOR = "\n\n—— 最终回答 ——\n\n"


class ReasoningPreservingSubtitleEventRouter(SubtitleEventRouter):
    """Keep visible reasoning when the first final-content chunk arrives.

    The existing subtitle window intentionally clears its text on the first
    ``content_delta``. That behavior is correct when reasoning display is
    disabled, but it also erases the reasoning trace when
    ``native_popup_show_reasoning`` is enabled.

    This router preserves the existing live reasoning stream and, immediately
    before the first visible content chunk, prepends the buffered reasoning to
    that chunk. The renderer can still clear its temporary reasoning view, but
    the replacement text now contains both reasoning and the final answer.
    """

    def __init__(
        self,
        popup: NativePopupController,
        config_store: JsonStore,
    ) -> None:
        super().__init__(popup, config_store)
        self._reasoning_buffers: dict[str, str] = {}
        self._content_started: set[str] = set()

    def publish(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        request_id = str(event.get("request_id") or "")

        if event_type == "request_start" and request_id:
            self._reasoning_buffers[request_id] = ""
            self._content_started.discard(request_id)
            super().publish(event)
            return

        if not request_id:
            return

        if event_type == "reasoning_delta":
            text = str(event.get("text") or "")
            if text:
                previous = self._reasoning_buffers.get(request_id, "")
                combined = previous + text
                if len(combined) > _REASONING_DISPLAY_LIMIT:
                    combined = combined[-_REASONING_DISPLAY_LIMIT:]
                self._reasoning_buffers[request_id] = combined

            # Keep the original behavior: while the model is thinking, stream
            # reasoning live when the setting is enabled.
            super().publish(event)
            return

        if event_type == "content_delta":
            self._publish_content(event, request_id)
            return

        if event_type in {
            "request_done",
            "request_error",
            "request_cancelled",
        }:
            try:
                super().publish(event)
            finally:
                self._reasoning_buffers.pop(request_id, None)
                self._content_started.discard(request_id)
            return

        super().publish(event)

    def _publish_content(
        self,
        event: dict[str, Any],
        request_id: str,
    ) -> None:
        state = self.requests.get(request_id)
        if state is None:
            return

        raw_text = str(event.get("text") or "")
        text = (
            raw_text
            if state.mode == "all"
            else state.extractor.feed(raw_text)
        )
        if not text:
            return

        config = self.config_store.read()
        show_reasoning = bool(
            config.get("native_popup_show_reasoning", False)
        )
        first_content = request_id not in self._content_started

        if first_content:
            self._content_started.add(request_id)

        if first_content and show_reasoning:
            reasoning = self._reasoning_buffers.get(request_id, "").strip()
            if reasoning:
                text = (
                    reasoning
                    + _REASONING_ANSWER_SEPARATOR
                    + text.lstrip()
                )

        self._ensure_started(state)
        self.popup.publish(
            {
                "type": "content_delta",
                "request_id": request_id,
                "text": text,
            }
        )
