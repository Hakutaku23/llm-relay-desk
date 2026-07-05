from __future__ import annotations

from typing import Any

from llm_relay_desk.debug_logging import DebugLogManager

from .context import current_injection_decision


class TaskAwareDebugLogManager(DebugLogManager):
    """Adds the current task-classification decision to debug logs.

    It preserves the public DebugLogManager API, so the existing proxy modules
    do not need to be replaced. Logging remains best effort and cannot affect
    request forwarding.
    """

    def start(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        session = super().start(*args, **kwargs)
        decision = current_injection_decision()
        if decision is None or not getattr(session, "enabled", False):
            return session

        try:
            document = getattr(session, "_request_document", None)
            if isinstance(document, dict):
                document["format_version"] = max(
                    3,
                    int(document.get("format_version", 2)),
                )
                document["relay"] = decision.to_dict()
        except Exception:
            # Debug information is observational only.
            pass
        return session
