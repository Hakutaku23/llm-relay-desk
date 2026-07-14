from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .scenarios import (
    ALL_SCENARIOS,
    MOCK_HEADER_NAME,
    MOCK_HEADER_VALUE,
    load_json,
    load_text,
    resolve_scenario,
)


def _json_error(status: int, native: bool = False) -> JSONResponse:
    messages = {401: "Mock authentication failed", 429: "Mock rate limit exceeded", 500: "Mock upstream failure"}
    content: dict[str, Any]
    if native:
        content = {"error": messages[status]}
    else:
        content = {"error": {"message": messages[status], "type": f"mock_http_{status}"}}
    headers = {"Retry-After": "7"} if status == 429 else None
    return JSONResponse(content, status_code=status, headers=headers)


def _special_response(scenario: str, native: bool = False) -> Response | None:
    if scenario.startswith("http-"):
        return _json_error(int(scenario.removeprefix("http-")), native)
    if scenario == "malformed-json":
        return Response(load_text("malformed.json"), media_type="application/json")
    return None


async def _single_chunk(content: str) -> AsyncIterator[bytes]:
    yield content.encode("utf-8")


def _openai_response(scenario: str) -> Response:
    special = _special_response(scenario)
    if special is not None:
        return special
    if scenario == "malformed-sse":
        return StreamingResponse(_single_chunk(load_text("malformed.sse")), media_type="text/event-stream")
    stream_fixture = {
        "openai-stream-final-usage": "openai_stream.sse",
        "vllm-stream-final-usage": "vllm_stream.sse",
        "interrupted-stream": "interrupted.sse",
    }.get(scenario)
    if stream_fixture:
        return StreamingResponse(_single_chunk(load_text(stream_fixture)), media_type="text/event-stream")
    fixture = {
        "openai-nonstream-usage": "openai_nonstream.json",
        "deepseek-cache-usage": "deepseek_cache.json",
        "vllm-nonstream-usage": "vllm_nonstream.json",
        "usage-missing": "openai_usage_missing.json",
        "cache-details-missing": "openai_cache_details_missing.json",
        "reasoning-only": "openai_reasoning_only.json",
    }[scenario]
    return JSONResponse(deepcopy(load_json(fixture)))


def _ollama_payload(scenario: str, endpoint: str, stream: bool) -> Response:
    special = _special_response(scenario, native=True)
    if special is not None:
        return special
    field = "message" if endpoint == "chat" else "response"
    if scenario == "interrupted-stream":
        name = f"ollama_{endpoint}_interrupted.ndjson"
        return StreamingResponse(_single_chunk(load_text(name)), media_type="application/x-ndjson")

    payload = deepcopy(load_json(f"ollama_{endpoint}.json"))
    if scenario == "usage-missing":
        payload.pop("prompt_eval_count", None)
        payload.pop("eval_count", None)
    elif scenario == "reasoning-only":
        if endpoint == "chat":
            payload["message"] = {"role": "assistant", "thinking": "Mock reasoning only.", "content": ""}
        else:
            payload["thinking"] = "Mock reasoning only."
            payload["response"] = ""
    if not stream:
        return JSONResponse(payload)

    first: dict[str, Any]
    if endpoint == "chat":
        first = {"model": payload["model"], "message": {"role": "assistant", "content": "Mock "}, "done": False}
    else:
        first = {"model": payload["model"], field: "Mock ", "done": False}
    if scenario == "reasoning-only":
        first = {"model": payload["model"], "thinking": "Mock reasoning only.", field: "", "done": False}
        if endpoint == "chat":
            first = {"model": payload["model"], "message": payload["message"], "done": False}
    import json

    content = json.dumps(first, separators=(",", ":")) + "\n" + json.dumps(payload, separators=(",", ":")) + "\n"
    return StreamingResponse(_single_chunk(content), media_type="application/x-ndjson")


def create_app() -> FastAPI:
    app = FastAPI(title="LLM Relay Desk Mock Upstream", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def identify_mock(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers[MOCK_HEADER_NAME] = MOCK_HEADER_VALUE
        return response

    @app.get("/v1/models")
    async def models(request: Request) -> Response:
        resolution = resolve_scenario(request, "models")
        if resolution.error:
            return JSONResponse(resolution.error, status_code=400)
        if resolution.name:
            return _special_response(resolution.name)  # type: ignore[return-value]
        data = [{"id": f"mock/{name}", "object": "model", "created": 1700000000, "owned_by": "llm-relay-desk"} for name in ALL_SCENARIOS]
        return JSONResponse({"object": "list", "data": data})

    @app.get("/api/tags")
    async def tags(request: Request) -> Response:
        resolution = resolve_scenario(request, "tags")
        if resolution.error:
            return JSONResponse(resolution.error, status_code=400)
        if resolution.name:
            return _special_response(resolution.name, native=True)  # type: ignore[return-value]
        models_data = [{"name": f"mock/{name}", "model": f"mock/{name}", "modified_at": "2024-01-01T00:00:00Z", "size": 1, "digest": "mock-fixed-digest"} for name in ALL_SCENARIOS]
        return JSONResponse({"models": models_data})

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        payload = await request.json()
        default = "openai-stream-final-usage" if payload.get("stream") else "openai-nonstream-usage"
        resolution = resolve_scenario(request, "openai-chat", payload, default)
        if resolution.error:
            return JSONResponse(resolution.error, status_code=400)
        return _openai_response(resolution.name or default)

    @app.post("/v1/embeddings")
    async def embeddings(request: Request) -> Response:
        payload = await request.json()
        resolution = resolve_scenario(request, "embeddings", payload, "embeddings-usage")
        if resolution.error:
            return JSONResponse(resolution.error, status_code=400)
        scenario = resolution.name or "embeddings-usage"
        special = _special_response(scenario)
        if special is not None:
            return special
        result = deepcopy(load_json("embeddings.json"))
        if scenario == "usage-missing":
            result.pop("usage", None)
        return JSONResponse(result)

    async def ollama(request: Request, endpoint: str) -> Response:
        payload = await request.json()
        resolution = resolve_scenario(request, "ollama", payload, "ollama-usage")
        if resolution.error:
            native_error = {"error": resolution.error["error"]}
            return JSONResponse(native_error, status_code=400)
        return _ollama_payload(resolution.name or "ollama-usage", endpoint, bool(payload.get("stream", True)))

    @app.post("/api/chat")
    async def api_chat(request: Request) -> Response:
        return await ollama(request, "chat")

    @app.post("/api/generate")
    async def api_generate(request: Request) -> Response:
        return await ollama(request, "generate")

    return app


app = create_app()
