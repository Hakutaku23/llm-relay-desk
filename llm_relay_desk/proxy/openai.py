from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from llm_relay_desk.monitoring.events import (
    new_request_id,
    publish_cancelled,
    publish_done,
    publish_error,
    publish_start,
)
from llm_relay_desk.runtime import Runtime

from .common import error_from_body, timeout_config, upstream_headers
from .extractors import publish_openai_object
from .parsers import OpenAISSEParser


async def list_models(runtime: Runtime) -> Response:
    config = runtime.config_store.read()
    url = f"{config['upstream_base_url']}/models"

    try:
        async with httpx.AsyncClient(
            timeout=timeout_config(config),
            trust_env=False,
        ) as client:
            response = await client.get(url, headers=upstream_headers(config))
    except httpx.RequestError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": f"Cannot reach upstream: {exc}",
                    "type": "upstream_connection_error",
                    "upstream": url,
                }
            },
        )

    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get(
            "content-type", "application/json"
        ).split(";")[0],
    )


async def chat_completions(runtime: Runtime, request: Request) -> Response:
    config = runtime.config_store.read()

    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="'messages' must be a list")

    payload["model"] = payload.get("model") or config["default_model"]
    payload["messages"] = runtime.prompts.inject_messages(messages, config)

    stream = bool(payload.get("stream", False))
    url = f"{config['upstream_base_url']}/chat/completions"
    request_id = new_request_id()
    started = publish_start(
        runtime.monitor,
        request_id=request_id,
        request=request,
        api="openai",
        route="/v1/chat/completions",
        model=str(payload.get("model", "")),
        stream=stream,
    )

    client = httpx.AsyncClient(timeout=timeout_config(config), trust_env=False)

    try:
        upstream_request = client.build_request(
            "POST",
            url,
            headers=upstream_headers(config),
            json=payload,
        )
        upstream_response = await client.send(upstream_request, stream=stream)
    except httpx.RequestError as exc:
        await client.aclose()
        publish_error(
            runtime.monitor,
            request_id,
            started,
            f"无法连接上游：{exc}",
            502,
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": f"Cannot reach upstream: {exc}",
                    "type": "upstream_connection_error",
                    "upstream": url,
                }
            },
            headers={"X-Relay-Request-ID": request_id},
        )

    if not stream or upstream_response.status_code >= 400:
        body = await upstream_response.aread()
        status_code = upstream_response.status_code
        media_type = upstream_response.headers.get(
            "content-type", "application/json"
        ).split(";")[0]
        await upstream_response.aclose()
        await client.aclose()

        if status_code < 400:
            try:
                value = json.loads(body)
                if isinstance(value, dict):
                    publish_openai_object(runtime.monitor, request_id, value)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            publish_done(runtime.monitor, request_id, started, status_code)
        else:
            publish_error(
                runtime.monitor,
                request_id,
                started,
                error_from_body(body),
                status_code,
            )

        return Response(
            content=body,
            status_code=status_code,
            media_type=media_type,
            headers={"X-Relay-Request-ID": request_id},
        )

    parser = OpenAISSEParser(runtime.monitor, request_id)

    async def stream_body() -> AsyncIterator[bytes]:
        completed = False
        try:
            async for chunk in upstream_response.aiter_raw():
                parser.feed(chunk)
                yield chunk
            parser.flush()
            publish_done(
                runtime.monitor,
                request_id,
                started,
                upstream_response.status_code,
            )
            completed = True
        except asyncio.CancelledError:
            publish_cancelled(
                runtime.monitor,
                request_id,
                started,
                upstream_response.status_code,
            )
            raise
        except Exception as exc:
            publish_error(
                runtime.monitor,
                request_id,
                started,
                f"读取上游流失败：{exc}",
                upstream_response.status_code,
            )
            raise
        finally:
            await upstream_response.aclose()
            await client.aclose()
            if not completed:
                parser.flush()

    return StreamingResponse(
        stream_body(),
        status_code=upstream_response.status_code,
        media_type=upstream_response.headers.get(
            "content-type", "text/event-stream"
        ).split(";")[0],
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Relay-Request-ID": request_id,
        },
    )
