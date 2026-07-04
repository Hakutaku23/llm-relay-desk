from __future__ import annotations

import asyncio
import copy
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
from .ollama_openai_adapter import forward_openai_as_ollama
from .protocol import resolve_upstream_protocol
from .reasoning import apply_ollama_reasoning_default
from .parsers import NativeNDJSONParser


class _NativeStreamCollector:
    def __init__(self, runtime: Runtime, request_id: str, mode: str) -> None:
        self.runtime = runtime
        self.request_id = request_id
        self.mode = mode
        self.buffer = bytearray()
        self.content: list[str] = []
        self.reasoning: list[str] = []
        self.last: dict[str, Any] = {}
        self.last_message: dict[str, Any] = {}

    def feed(self, chunk: bytes) -> None:
        self.buffer.extend(chunk)
        while True:
            index = self.buffer.find(b"\n")
            if index < 0:
                break
            line = bytes(self.buffer[:index]).strip()
            del self.buffer[: index + 1]
            self._process(line)

    def finish(self) -> dict[str, Any]:
        self._process(bytes(self.buffer).strip())
        self.buffer.clear()
        result = dict(self.last)
        result["done"] = True
        if self.mode == "chat":
            message = dict(self.last_message)
            message.setdefault("role", "assistant")
            message["content"] = "".join(self.content)
            if self.reasoning:
                message["thinking"] = "".join(self.reasoning)
            result["message"] = message
        else:
            result["response"] = "".join(self.content)
            if self.reasoning:
                result["thinking"] = "".join(self.reasoning)
        return result

    def _process(self, line: bytes) -> None:
        if not line:
            return
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(value, dict):
            return
        self.last = value
        publish_native_object(self.runtime.monitor, self.request_id, value)
        message = value.get("message")
        if isinstance(message, dict):
            self.last_message.update(message)
            content = message.get("content")
            thinking = message.get("thinking") or message.get("reasoning")
        else:
            content = value.get("response")
            thinking = value.get("thinking") or value.get("reasoning")
        if isinstance(content, str) and content:
            self.content.append(content)
        if isinstance(thinking, str) and thinking:
            self.reasoning.append(thinking)


async def forward_native_request(
    runtime: Runtime,
    *,
    request: Request,
    path: str,
    method: str,
    inject_prompt_mode: str | None = None,
) -> Response:
    config = runtime.config_store.read()
    if resolve_upstream_protocol(config) == "openai":
        return await forward_openai_as_ollama(
            runtime,
            request=request,
            path=path,
            method=method,
            inject_prompt_mode=inject_prompt_mode,
        )
    url = f"{native_upstream_root(config)}{path}"

    payload: dict[str, Any] | None = None
    incoming_payload: dict[str, Any] | None = None
    if method not in {"GET", "HEAD"}:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        incoming_payload = copy.deepcopy(payload)

        if inject_prompt_mode == "chat":
            messages = payload.get("messages")
            if not isinstance(messages, list):
                raise HTTPException(status_code=400, detail="'messages' must be a list")
            payload["model"] = payload.get("model") or config["default_model"]
            payload["messages"] = runtime.prompts.inject_messages(messages, config)
        elif inject_prompt_mode == "generate":
            payload["model"] = payload.get("model") or config["default_model"]
            runtime.prompts.inject_generate_system(payload, config)

        if inject_prompt_mode in {"chat", "generate"}:
            apply_ollama_reasoning_default(payload, config)

    client_stream = bool(payload.get("stream", True)) if payload is not None else False
    monitored = inject_prompt_mode in {"chat", "generate"}
    force_stream = bool(
        monitored
        and not client_stream
        and config.get("native_popup_enabled", True)
        and config.get("native_popup_force_upstream_stream", True)
    )
    upstream_stream = client_stream or force_stream
    if payload is not None and monitored:
        payload["stream"] = upstream_stream

    request_id = new_request_id() if monitored else ""
    trace_request_id = request_id or new_request_id()
    headers = upstream_headers(config)
    trace = runtime.debug_logs.start(
        request_id=trace_request_id,
        request=request,
        incoming_body=incoming_payload,
        upstream_method=method,
        upstream_url=url,
        upstream_headers=headers,
        upstream_body=payload if method not in {"GET", "HEAD"} else None,
    )
    started = (
        publish_start(
            runtime.monitor,
            request_id=request_id,
            request=request,
            api="ollama",
            route=path,
            model=str((payload or {}).get("model", config.get("default_model", ""))),
            stream=client_stream,
        )
        if monitored
        else 0.0
    )

    client = httpx.AsyncClient(timeout=timeout_config(config), trust_env=False)

    try:
        upstream_request = client.build_request(
            method,
            url,
            headers=headers,
            json=payload if method not in {"GET", "HEAD"} else None,
        )
        upstream_response = await client.send(upstream_request, stream=upstream_stream)
    except httpx.RequestError as exc:
        await client.aclose()
        trace.finish(outcome="error", status_code=502, error=str(exc))
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

    trace.response_start(upstream_response.status_code, upstream_response.headers)
    content_type = upstream_response.headers.get("content-type", "").lower()
    if force_stream and upstream_response.status_code < 400:
        collector = _NativeStreamCollector(
            runtime,
            request_id,
            "chat" if inject_prompt_mode == "chat" else "generate",
        )
        try:
            async for chunk in upstream_response.aiter_raw():
                trace.append_response(chunk)
                collector.feed(chunk)
            converted = collector.finish()
            trace.finish(status_code=upstream_response.status_code)
            publish_done(runtime.monitor, request_id, started, upstream_response.status_code)
            return JSONResponse(
                content=converted,
                status_code=upstream_response.status_code,
                headers={"X-Relay-Request-ID": request_id},
            )
        except Exception as exc:
            trace.finish(
                outcome="error",
                status_code=upstream_response.status_code,
                error=str(exc),
            )
            publish_error(
                runtime.monitor,
                request_id,
                started,
                f"读取上游流失败：{exc}",
                upstream_response.status_code,
            )
            return JSONResponse(status_code=502, content={"error": str(exc)})
        finally:
            await upstream_response.aclose()
            await client.aclose()

    if not upstream_stream or upstream_response.status_code >= 400 or force_stream:
        body = await upstream_response.aread()
        trace.append_response(body)
        status_code = upstream_response.status_code
        media_type = upstream_response.headers.get(
            "content-type", "application/json"
        ).split(";")[0]
        await upstream_response.aclose()
        await client.aclose()

        trace.finish(
            outcome="completed" if status_code < 400 else "upstream_error",
            status_code=status_code,
            error=error_from_body(body) if status_code >= 400 else None,
        )

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
                trace.append_response(chunk)
                if monitored:
                    parser.feed(chunk)
                yield chunk
            trace.finish(status_code=upstream_response.status_code)
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
            trace.finish(
                outcome="cancelled",
                status_code=upstream_response.status_code,
                error="client disconnected",
            )
            if monitored:
                publish_cancelled(
                    runtime.monitor,
                    request_id,
                    started,
                    upstream_response.status_code,
                )
            raise
        except Exception as exc:
            trace.finish(
                outcome="error",
                status_code=upstream_response.status_code,
                error=str(exc),
            )
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
