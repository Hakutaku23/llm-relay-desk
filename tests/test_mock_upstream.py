from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tools.mock_upstream.app import create_app
from tools.mock_upstream.cli import build_parser
from tools.mock_upstream.scenarios import ALL_SCENARIOS, OPENAI_CHAT_SCENARIOS


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app()) as value:
        yield value


def identified(response) -> None:  # type: ignore[no-untyped-def]
    assert response.headers["X-Mock-Upstream"] == "llm-relay-desk"


def test_cli_defaults() -> None:
    args = build_parser().parse_args([])
    assert (args.host, args.port) == ("127.0.0.1", 18000)


@pytest.mark.parametrize("path,key", [("/v1/models", "data"), ("/api/tags", "models")])
def test_model_lists(client: TestClient, path: str, key: str) -> None:
    response = client.get(path)
    identified(response)
    names = [item.get("id", item.get("name")) for item in response.json()[key]]
    assert set(names) == {f"mock/{name}" for name in ALL_SCENARIOS}


def test_header_selection_and_precedence(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", headers={"X-Mock-Scenario": "deepseek-cache-usage"}, json={"model": "mock/openai-nonstream-usage"})
    assert response.json()["usage"]["prompt_cache_hit_tokens"] == 12


def test_reserved_model_selection(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json={"model": "mock/vllm-nonstream-usage"})
    assert response.json()["model"] == "mock/vllm-nonstream-usage"


def test_unknown_scenario(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", headers={"X-Mock-Scenario": "unknown"}, json={"model": "plain"})
    assert response.status_code == 400
    identified(response)
    assert response.json()["error"]["unknown_scenario"] == "unknown"
    assert response.json()["error"]["supported_scenarios"] == list(OPENAI_CHAT_SCENARIOS)


def test_openai_nonstream_usage(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json={"model": "plain"})
    assert response.json()["usage"] == {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}


@pytest.mark.parametrize("scenario,total", [("openai-stream-final-usage", 16), ("vllm-stream-final-usage", 15)])
def test_stream_final_usage(client: TestClient, scenario: str, total: int) -> None:
    response = client.post("/v1/chat/completions", json={"model": f"mock/{scenario}", "stream": True})
    identified(response)
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    assert json.loads(events[-2])["usage"]["total_tokens"] == total
    assert all("usage" not in json.loads(event) for event in events[:-2])


def test_embeddings(client: TestClient) -> None:
    body = client.post("/v1/embeddings", json={"model": "plain", "input": "fixed"}).json()
    assert body["data"][0]["embedding"] == [0.125, -0.25, 0.5]
    assert body["usage"] == {"prompt_tokens": 4, "total_tokens": 4}


@pytest.mark.parametrize("path", ["/api/chat", "/api/generate"])
@pytest.mark.parametrize("stream", [False, True])
def test_ollama_usage(client: TestClient, path: str, stream: bool) -> None:
    response = client.post(path, json={"model": "mock/ollama-usage", "stream": stream})
    identified(response)
    objects = [json.loads(line) for line in response.text.splitlines()] if stream else [response.json()]
    assert objects[-1]["done"] is True
    assert objects[-1]["prompt_eval_count"] > 0 and objects[-1]["eval_count"] > 0
    media_type = "application/x-ndjson" if stream else "application/json"
    assert response.headers["content-type"].startswith(media_type)


def test_deepseek_and_vllm_nonstream(client: TestClient) -> None:
    deepseek = client.post("/v1/chat/completions", json={"model": "mock/deepseek-cache-usage"}).json()
    assert deepseek["usage"]["prompt_cache_hit_tokens"] + deepseek["usage"]["prompt_cache_miss_tokens"] == deepseek["usage"]["prompt_tokens"]
    vllm = client.post("/v1/chat/completions", json={"model": "mock/vllm-nonstream-usage"}).json()
    assert vllm["usage"]["total_tokens"] == 13


@pytest.mark.parametrize("path,payload", [
    ("/v1/chat/completions", {"model": "mock/usage-missing"}),
    ("/v1/embeddings", {"model": "mock/usage-missing", "input": "x"}),
    ("/api/chat", {"model": "mock/usage-missing", "stream": False}),
    ("/api/generate", {"model": "mock/usage-missing", "stream": False}),
])
def test_usage_missing(client: TestClient, path: str, payload: dict[str, object]) -> None:
    body = client.post(path, json=payload).json()
    assert "usage" not in body and "prompt_eval_count" not in body and "eval_count" not in body


def test_cache_details_missing(client: TestClient) -> None:
    usage = client.post("/v1/chat/completions", json={"model": "mock/cache-details-missing"}).json()["usage"]
    assert usage == {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
    for path in ("/api/chat", "/api/generate"):
        body = client.post(path, json={"model": "mock/cache-details-missing", "stream": False}).json()
        assert all("cache" not in key for key in body)


def test_reasoning_only(client: TestClient) -> None:
    message = client.post("/v1/chat/completions", json={"model": "mock/reasoning-only"}).json()["choices"][0]["message"]
    assert message["reasoning_content"] and message["content"] == ""
    chat = client.post("/api/chat", json={"model": "mock/reasoning-only", "stream": False}).json()["message"]
    assert chat["thinking"] and chat["content"] == ""
    generate = client.post("/api/generate", json={"model": "mock/reasoning-only", "stream": False}).json()
    assert generate["thinking"] and generate["response"] == ""


@pytest.mark.parametrize("status", [401, 429, 500])
@pytest.mark.parametrize("method,path,payload", [
    ("get", "/v1/models", None), ("get", "/api/tags", None),
    ("post", "/v1/chat/completions", {"model": "plain"}),
    ("post", "/v1/embeddings", {"model": "plain", "input": "x"}),
    ("post", "/api/chat", {"model": "plain", "stream": False}),
    ("post", "/api/generate", {"model": "plain", "stream": False}),
])
def test_http_errors(client: TestClient, status: int, method: str, path: str, payload: dict[str, object] | None) -> None:
    response = client.request(method, path, headers={"X-Mock-Scenario": f"http-{status}"}, json=payload)
    assert response.status_code == status
    identified(response)
    assert "error" in response.json()
    assert response.headers.get("Retry-After") == ("7" if status == 429 else None)


def test_interrupted_sse(client: TestClient) -> None:
    text = client.post("/v1/chat/completions", json={"model": "mock/interrupted-stream", "stream": True}).text
    assert "Partial" in text and "[DONE]" not in text and '"usage"' not in text


@pytest.mark.parametrize("path", ["/api/chat", "/api/generate"])
def test_interrupted_ndjson(client: TestClient, path: str) -> None:
    text = client.post(path, json={"model": "mock/interrupted-stream", "stream": True}).text
    assert all(json.loads(line).get("done") is not True for line in text.splitlines())


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/v1/models", None), ("get", "/api/tags", None),
    ("post", "/v1/chat/completions", {"model": "mock/malformed-json"}),
    ("post", "/v1/embeddings", {"model": "mock/malformed-json", "input": "x"}),
    ("post", "/api/chat", {"model": "mock/malformed-json"}),
    ("post", "/api/generate", {"model": "mock/malformed-json"}),
])
def test_malformed_json(client: TestClient, method: str, path: str, payload: dict[str, object] | None) -> None:
    headers = {"X-Mock-Scenario": "malformed-json"} if method == "get" else None
    response = client.request(method, path, headers=headers, json=payload)
    identified(response)
    with pytest.raises(json.JSONDecodeError):
        response.json()


def test_malformed_sse(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json={"model": "mock/malformed-sse", "stream": True})
    assert "not valid sse" in response.text and "[DONE]" not in response.text
    identified(response)


@pytest.mark.parametrize("scenario", OPENAI_CHAT_SCENARIOS)
def test_all_openai_scenarios_are_finite(client: TestClient, scenario: str) -> None:
    response = client.post("/v1/chat/completions", headers={"X-Mock-Scenario": scenario}, json={"model": "plain", "stream": "stream" in scenario})
    assert response.status_code in {200, 401, 429, 500}
    identified(response)


def test_client_uses_in_process_test_transport(client: TestClient) -> None:
    assert str(client.base_url) == "http://testserver"
