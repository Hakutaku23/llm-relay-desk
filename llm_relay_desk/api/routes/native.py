from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from llm_relay_desk.api.dependencies import runtime_from_request
from llm_relay_desk.prompts import bind_relay_request_context
from llm_relay_desk.proxy.native import forward_native_request

router = APIRouter(prefix="/api", tags=["ollama-compatible"])


async def _json_object(request: Request) -> dict[str, Any] | None:
    try:
        value = await request.json()
    except Exception:
        return None
    return value if isinstance(value, dict) else None


@router.get("/tags")
async def tags(request: Request) -> Response:
    return await forward_native_request(
        runtime_from_request(request),
        request=request,
        path="/api/tags",
        method="GET",
    )


@router.get("/ps")
async def ps(request: Request) -> Response:
    return await forward_native_request(
        runtime_from_request(request),
        request=request,
        path="/api/ps",
        method="GET",
    )


@router.get("/version")
async def version(request: Request) -> Response:
    return await forward_native_request(
        runtime_from_request(request),
        request=request,
        path="/api/version",
        method="GET",
    )


@router.post("/show")
async def show(request: Request) -> Response:
    return await forward_native_request(
        runtime_from_request(request),
        request=request,
        path="/api/show",
        method="POST",
    )


@router.post("/chat")
async def chat(request: Request) -> Response:
    payload = await _json_object(request)
    with bind_relay_request_context(
        payload=payload,
        headers=request.headers,
        endpoint="/api/chat",
    ):
        return await forward_native_request(
            runtime_from_request(request),
            request=request,
            path="/api/chat",
            method="POST",
            inject_prompt_mode="chat",
        )


@router.post("/generate")
async def generate(request: Request) -> Response:
    payload = await _json_object(request)
    with bind_relay_request_context(
        payload=payload,
        headers=request.headers,
        endpoint="/api/generate",
    ):
        return await forward_native_request(
            runtime_from_request(request),
            request=request,
            path="/api/generate",
            method="POST",
            inject_prompt_mode="generate",
        )


@router.post("/embed")
async def embed(request: Request) -> Response:
    return await forward_native_request(
        runtime_from_request(request),
        request=request,
        path="/api/embed",
        method="POST",
    )


@router.post("/embeddings")
async def embeddings(request: Request) -> Response:
    return await forward_native_request(
        runtime_from_request(request),
        request=request,
        path="/api/embeddings",
        method="POST",
    )
