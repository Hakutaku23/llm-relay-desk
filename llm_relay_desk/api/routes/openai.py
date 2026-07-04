from __future__ import annotations

from fastapi import APIRouter, Header, Request
from fastapi.responses import Response

from llm_relay_desk.api.dependencies import runtime_from_request
from llm_relay_desk.proxy.common import verify_local_api_key
from llm_relay_desk.proxy.openai import chat_completions, list_models

router = APIRouter(prefix="/v1", tags=["openai-compatible"])


@router.get("/models")
async def models(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    runtime = runtime_from_request(request)
    verify_local_api_key(runtime, authorization)
    return await list_models(runtime, request)


@router.post("/chat/completions")
async def completions(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    runtime = runtime_from_request(request)
    verify_local_api_key(runtime, authorization)
    return await chat_completions(runtime, request)
