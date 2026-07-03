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

from .common import (
    error_from_body,
    native_upstream_root,
    timeout_config,
    upstream_headers,
)
from .extractors import publish_native_object
from .parsers import NativeNDJSONParser


async def forward_native_request(
    runtime: Runtime,
    *,
    request: Request,
    path: str,
    method: str,
    inject_prompt_mode: str | None = None,
) -> Response:
    config = runtime.config_store.read()
    url = f"{native_upstream_root(config)}{path}"

    payload: dict[str, Any] | None = None
    if method not in {"GET", "HEAD"}:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        if inject_prompt_mode == "chat":
            messages = payload.get("messages")
            if not isinstance(messages, list):
                raise HTTPException(status_code=400, detail="'messages' must be a list")
            payload["model"] = payload.get("model") or config["default_model"]
            payload["messages"] = runtime.prompts.inject_messages(messages, config)
        elif inject_prompt_mode == "generate":
            payload["model"] = payload.get("model") or config["default_model"]
            runtime.prompts.inject_generate_system(payload, config)

    stream = bool(payload.get("stream", True)) if payload is not None else False
    monitored = inject_prompt_mode in {"chat", "generate"}
    request_id = new_request_id() if monitored else ""
    started = (
        publish_start(
            runtime.monitor,
            request_id=request_id,
            request=request,
            api="ollama",
            route=path,
            model=str((payload or {}).get("model", config.get("default_model", ""))),
            stream=stream,
        )
        if monitored
        else 0.0
    )

    client = httpx.AsyncClient(timeout=timeout_config(config), trust_env=False)

    try:
        upstream_request = client.build_request(
            method,
            url,
            headers=upstream_headers(config),
            json=payload if method not in {"GET", "HEAD"} else None,
        )
        upstream_response = await client.send(upstream_request, stream=stream)
    except httpx.RequestError as exc:
        await client.aclose()
        if monitored:
            publish_error(
                runtime.monitor,
                request_id,
                started,
                f"无法连接 Ollama 上游：{exc}",
                502,
            )
        return JSONResponse(
            status_code=502,
            content={
                "error": f"Cannot reach Ollama native upstream: {exc}",
                "upstream": url,
            },
            headers={"X-Relay-Request-ID": request_id} if monitored else None,
        )

    if not stream or upstream_response.status_code >= 400:
        body = await upstream_response.aread()
        status_code = upstream_response.status_code
        media_type = upstream_response.headers.get(
            "content-type", "application/json"
        ).split(";")[0]
        await upstream_response.aclose()
        await client.aclose()

        if monitored:
            if status_code < 400:
                try:
                    value = json.loads(body)
                    if isinstance(value, dict):
                        publish_native_object(runtime.monitor, request_id, value)
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
            headers={"X-Relay-Request-ID": request_id} if monitored else None,
        )

    parser = NativeNDJSONParser(runtime.monitor, request_id)

    async def stream_body() -> AsyncIterator[bytes]:
        completed = False
        try:
            async for chunk in upstream_response.aiter_raw():
                if monitored:
                    parser.feed(chunk)
                yield chunk
            if monitored:
                parser.flush()
                publish_done(
                    runtime.monitor,
                    request_id,
                    started,
                    upstream_response.status_code,
                )
            completed = True
        except asyncio.CancelledError:
            if monitored:
                publish_cancelled(
                    runtime.monitor,
                    request_id,
                    started,
                    upstream_response.status_code,
                )
            raise
        except Exception as exc:
            if monitored:
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
            if monitored and not completed:
                parser.flush()

    return StreamingResponse(
        stream_body(),
        status_code=upstream_response.status_code,
        media_type=upstream_response.headers.get(
            "content-type", "application/x-ndjson"
        ).split(";")[0],
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Relay-Request-ID": request_id,
        },
    )
