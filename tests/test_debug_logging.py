from __future__ import annotations

import os
from pathlib import Path

from llm_relay_desk.debug_logging import DebugLogManager, _complete_response_body
from llm_relay_desk.settings import DEFAULT_CONFIG
from llm_relay_desk.storage import JsonStore


def test_debug_log_cleanup_keeps_newest_files_and_supports_legacy_jsonl(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    store = JsonStore(data_dir / "config.json", DEFAULT_CONFIG)
    config = store.read()
    config.update(
        {
            "debug_logging_enabled": True,
            "debug_log_directory": "debug_logs",
            "debug_log_retention_files": 2,
        }
    )
    store.write(config)
    manager = DebugLogManager(store, data_dir)
    directory = manager.resolve_directory()
    directory.mkdir(parents=True)
    names = ["0.jsonl", "1.json", "2.jsonl", "3.json"]
    for index, name in enumerate(names):
        path = directory / name
        path.write_text("{}\n", encoding="utf-8")
        os.utime(path, (index + 1, index + 1))

    manager.cleanup()

    assert sorted(path.name for path in directory.iterdir()) == [
        "2.jsonl",
        "3.json",
    ]


def test_debug_status_uses_complete_response_json_format(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = JsonStore(data_dir / "config.json", DEFAULT_CONFIG)
    manager = DebugLogManager(store, data_dir)
    status = manager.status()
    assert status["enabled"] is False
    assert Path(status["directory"]) == (data_dir / "debug_logs").resolve()
    assert status["format"] == "json-per-request-complete-response"
    assert status["response_mode"] == "complete"
    assert status["sensitive_headers_redacted"] is True


def test_openai_sse_is_aggregated_into_one_complete_response() -> None:
    body = (
        b'data: {"id":"chat-1","object":"chat.completion.chunk","model":"m",'
        b'"choices":[{"index":0,"delta":{"role":"assistant",'
        b'"reasoning_content":"R"},"finish_reason":null}]}\n\n'
        b'data: {"id":"chat-1","object":"chat.completion.chunk","model":"m",'
        b'"choices":[{"index":0,"delta":{"content":"A"},'
        b'"finish_reason":"stop"}]}\n\n'
        b'data: [DONE]\n\n'
    )

    response, response_format, event_count, done_seen = _complete_response_body(
        body,
        "text/event-stream",
    )

    assert response_format == "openai-sse"
    assert event_count == 2
    assert done_seen is True
    assert response["object"] == "chat.completion"
    message = response["choices"][0]["message"]
    assert message["reasoning_content"] == "R"
    assert message["content"] == "A"
    assert response["choices"][0]["finish_reason"] == "stop"


def test_ollama_ndjson_is_aggregated_into_one_complete_response() -> None:
    body = (
        b'{"model":"m","message":{"role":"assistant","thinking":"R",'
        b'"content":"A"},"done":false}\n'
        b'{"model":"m","message":{"content":"B"},"done":true,'
        b'"done_reason":"stop"}\n'
    )

    response, response_format, event_count, done_seen = _complete_response_body(
        body,
        "application/x-ndjson",
    )

    assert response_format == "ollama-ndjson"
    assert event_count == 2
    assert done_seen is False
    assert response["done"] is True
    assert response["done_reason"] == "stop"
    assert response["message"]["thinking"] == "R"
    assert response["message"]["content"] == "AB"


def test_openai_tool_call_and_usage_are_preserved_when_aggregated() -> None:
    body = (
        b'data: {"id":"chat-2","object":"chat.completion.chunk","model":"m",'
        b'"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,'
        b'"id":"call_1","type":"function","function":{"name":"weather",'
        b'"arguments":"{\\\"city\\\":"}}]},"finish_reason":null}]}\n\n'
        b'data: {"id":"chat-2","object":"chat.completion.chunk","model":"m",'
        b'"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,'
        b'"function":{"arguments":"\\\"Tokyo\\\"}"}}]},'
        b'"finish_reason":"tool_calls"}],"usage":{"completion_tokens":2}}\n\n'
        b'data: [DONE]\n\n'
    )

    response, _, _, _ = _complete_response_body(body, "text/event-stream")

    assert response["usage"] == {"completion_tokens": 2}
    choice = response["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    tool_call = choice["message"]["tool_calls"][0]
    assert tool_call["id"] == "call_1"
    assert tool_call["function"]["name"] == "weather"
    assert tool_call["function"]["arguments"] == '{"city":"Tokyo"}'
