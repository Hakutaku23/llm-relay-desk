from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_relay_desk.desktop.subtitle_events import DialogueTextStream, SubtitleEventRouter
from llm_relay_desk.settings import DEFAULT_CONFIG
from llm_relay_desk.storage import JsonStore


class FakePopup:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))


def _router(tmp_path: Path) -> tuple[SubtitleEventRouter, FakePopup]:
    store = JsonStore(tmp_path / "config.json", DEFAULT_CONFIG)
    popup = FakePopup()
    return SubtitleEventRouter(popup, store), popup  # type: ignore[arg-type]


def _emit(router: SubtitleEventRouter, request_id: str, text: str) -> None:
    router.publish(
        {
            "type": "request_start",
            "request_id": request_id,
            "model": "m",
            "api": "ollama",
            "route": "/api/chat",
        }
    )
    for index in range(0, len(text), 7):
        router.publish(
            {
                "type": "content_delta",
                "request_id": request_id,
                "text": text[index : index + 7],
            }
        )
    router.publish({"type": "request_done", "request_id": request_id})


def _subtitle_text(events: list[dict[str, Any]]) -> str:
    return "".join(
        str(event.get("text") or "")
        for event in events
        if event.get("type") == "content_delta"
    )


def test_dialogue_stream_extracts_statement_and_response() -> None:
    statement = DialogueTextStream(("response", "statement"))
    source = '{"statement":"账册已充盈，愿商队蹄声不绝。","action":"accept"}'
    output = "".join(statement.feed(source[i : i + 4]) for i in range(0, len(source), 4))
    assert output == "账册已充盈，愿商队蹄声不绝。"

    response = DialogueTextStream(("response", "statement"))
    source = '{"response":"\\"干得漂亮。\\"","actions":[]}'
    output = "".join(response.feed(source[i : i + 3]) for i in range(0, len(source), 3))
    assert output == '"干得漂亮。"'


def test_dialogue_router_suppresses_non_dialogue_control_json(tmp_path: Path) -> None:
    router, popup = _router(tmp_path)
    _emit(
        router,
        "r1",
        '{"kingdom_engagement":{"battania":65},"events":[{"type":"political"}]}',
    )
    assert popup.events == []


def test_dialogue_router_only_forwards_selected_field(tmp_path: Path) -> None:
    router, popup = _router(tmp_path)
    _emit(
        router,
        "r1",
        '{"statement":"只显示这句话","action":"accept_trade","reason":"不要显示"}',
    )
    assert popup.events[0]["type"] == "request_start"
    assert _subtitle_text(popup.events) == "只显示这句话"
    assert popup.events[-1]["type"] == "request_done"


def test_plain_text_fallback_remains_streamed(tmp_path: Path) -> None:
    router, popup = _router(tmp_path)
    _emit(router, "r1", "这是普通自然语言回复。")
    assert _subtitle_text(popup.events) == "这是普通自然语言回复。"


def test_dialogue_mode_streams_reasoning_immediately_when_enabled(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "config.json", DEFAULT_CONFIG)
    store.update({"native_popup_show_reasoning": True})
    popup = FakePopup()
    router = SubtitleEventRouter(popup, store)  # type: ignore[arg-type]

    router.publish({
        "type": "request_start",
        "request_id": "r1",
        "model": "m",
        "api": "openai",
        "route": "/v1/chat/completions",
    })
    router.publish({
        "type": "reasoning_delta",
        "request_id": "r1",
        "text": "step one",
    })
    router.publish({
        "type": "reasoning_delta",
        "request_id": "r1",
        "text": " step two",
    })
    router.publish({
        "type": "content_delta",
        "request_id": "r1",
        "text": "prompt_test_001",
    })
    router.publish({"type": "request_done", "request_id": "r1"})

    assert popup.events[0]["type"] == "request_start"
    reasoning = [event["text"] for event in popup.events if event["type"] == "reasoning_delta"]
    assert reasoning == ["step one", " step two"]
    assert _subtitle_text(popup.events) == "prompt_test_001"
    assert popup.events[-1]["type"] == "request_done"


def test_dialogue_mode_keeps_reasoning_suppressed_when_disabled(tmp_path: Path) -> None:
    router, popup = _router(tmp_path)
    router.publish({
        "type": "request_start",
        "request_id": "r1",
        "model": "m",
        "api": "openai",
        "route": "/v1/chat/completions",
    })
    router.publish({
        "type": "reasoning_delta",
        "request_id": "r1",
        "text": "hidden",
    })
    router.publish({"type": "request_done", "request_id": "r1"})
    assert popup.events == []
