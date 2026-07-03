from llm_relay_desk.monitoring import MonitorHub
from llm_relay_desk.proxy.parsers import NativeNDJSONParser, OpenAISSEParser


def _started_hub(request_id: str) -> MonitorHub:
    hub = MonitorHub(sinks=[])
    hub.publish(
        {
            "type": "request_start",
            "request_id": request_id,
            "model": "test",
            "stream": True,
        }
    )
    return hub


def test_openai_sse_parser_handles_split_chunks() -> None:
    hub = _started_hub("req_openai")
    parser = OpenAISSEParser(hub, "req_openai")
    parser.feed(b'data: {"choices":[{"delta":{"reasoning":"think"}}]}\n')
    parser.feed(b'\ndata: {"choices":[{"delta":{"content":"answer"}}]}\n\n')
    parser.flush()
    record = hub.records["req_openai"]
    assert record["reasoning"] == "think"
    assert record["content"] == "answer"


def test_native_ndjson_parser_handles_split_chunks() -> None:
    hub = _started_hub("req_native")
    parser = NativeNDJSONParser(hub, "req_native")
    parser.feed(b'{"message":{"thinking":"t","content":"a"}}')
    parser.feed(b'\n{"response":"b"}\n')
    parser.flush()
    record = hub.records["req_native"]
    assert record["reasoning"] == "t"
    assert record["content"] == "ab"
