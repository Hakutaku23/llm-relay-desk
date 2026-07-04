from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
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
from .extractors import extract_reasoning, publish_openai_object, text_from_content
from .parsers import OpenAISSEParser
from .reasoning import apply_openai_reasoning_default


class _OpenAIStreamCollector:
    def __init__(self, runtime: Runtime, request_id: str, model: str) -> None:
        self.runtime = runtime
        self.request_id = request_id
        self.model = model
        self.buffer = bytearray()
        self.response_id = f"chatcmpl-relay-{uuid.uuid4().hex[:12]}"
        self.created = int(time.time())
        self.role = "assistant"
        self.content: list[str] = []
        self.reasoning: list[str] = []
        self.finish_reason: str | None = None
        self.usage: Any = None
        self.system_fingerprint: Any = None
        self.service_tier: Any = None
        self.tool_calls: dict[int, dict[str, Any]] = {}
        self.error: str | None = None

    def feed(self, chunk: bytes) -> None:
        self.buffer.extend(chunk)
        while True:
            lf_index = self.buffer.find(b"\n\n")
            crlf_index = self.buffer.find(b"\r\n\r\n")
            candidates = [(lf_index, 2), (crlf_index, 4)]
            candidates = [(pos, size) for pos, size in candidates if pos >= 0]
            if not candidates:
                break
            pos, size = min(candidates, key=lambda item: item[0])
            block = bytes(self.buffer[:pos])
            del self.buffer[: pos + size]
            self._process_block(block)

    def finish(self) -> dict[str, Any]:
        if self.buffer:
            self._process_block(bytes(self.buffer))
            self.buffer.clear()
        message: dict[str, Any] = {
            "role": self.role,
            "content": "".join(self.content),
        }
        if self.reasoning:
            message["reasoning_content"] = "".join(self.reasoning)
        if self.tool_calls:
            message["tool_calls"] = [
                self.tool_calls[index] for index in sorted(self.tool_calls)
            ]
        result: dict[str, Any] = {
            "id": self.response_id,
            "object": "chat.completion",
            "created": self.created,
            "model": self.model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": self.finish_reason or "stop",
                }
            ],
        }
        if self.usage is not None:
            result["usage"] = self.usage
        if self.system_fingerprint is not None:
            result["system_fingerprint"] = self.system_fingerprint
        if self.service_tier is not None:
            result["service_tier"] = self.service_tier
        return result

    def _process_block(self, block: bytes) -> None:
        data_lines: list[str] = []
        text = block.decode("utf-8", errors="replace").replace("\r\n", "\n")
        for line in text.split("\n"):
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines:
            return
        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            return
        try:
            value = json.loads(data)
        except json.JSONDecodeError:
            return
        if not isinstance(value, dict):
            return
        if isinstance(value.get("error"), dict):
            self.error = str(value["error"].get("message") or value["error"])
            return

        publish_openai_object(self.runtime.monitor, self.request_id, value)
        if value.get("id"):
            self.response_id = str(value["id"])
        if isinstance(value.get("created"), (int, float)):
            self.created = int(value["created"])
        if value.get("model"):
            self.model = str(value["model"])
        if value.get("usage") is not None:
            self.usage = value["usage"]
        if value.get("system_fingerprint") is not None:
            self.system_fingerprint = value["system_fingerprint"]
        if value.get("service_tier") is not None:
            self.service_tier = value["service_tier"]

        choices = value.get("choices")
        if not isinstance(choices, list):
            return
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason") is not None:
                self.finish_reason = str(choice["finish_reason"])
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            if delta.get("role"):
                self.role = str(delta["role"])
            content = text_from_content(delta.get("content"))
            reasoning = extract_reasoning(delta)
            if content:
                self.content.append(content)
            if reasoning:
                self.reasoning.append(reasoning)
            self._absorb_tool_calls(delta.get("tool_calls"))

    def _absorb_tool_calls(self, value: Any) -> None:
        if not isinstance(value, list):
            return
        for item in value:
            if not isinstance(item, dict):
                continue
            index = int(item.get("index") or 0)
            current = self.tool_calls.setdefault(
                index,
                {
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                },
            )
            if item.get("id"):
                current["id"] = str(item["id"])
            if item.get("type"):
                current["type"] = str(item["type"])
            function = item.get("function")
            if isinstance(function, dict):
                if function.get("name"):
                    current["function"]["name"] += str(function["name"])
                if function.get("arguments"):
                    current["function"]["arguments"] += str(function["arguments"])


async def list_models(runtime: Runtime, request: Request) -> Response:
    config = runtime.config_store.read()
    url = f"{config['upstream_base_url']}/models"

    request_id = new_request_id()
    headers = upstream_headers(config)
    trace = runtime.debug_logs.start(
        request_id=request_id,
        request=request,
        incoming_body=None,
        upstream_method="GET",
        upstream_url=url,
        upstream_headers=headers,
        upstream_body=None,
    )
    try:
        async with httpx.AsyncClient(
            timeout=timeout_config(config),
            trust_env=False,
        ) as client:
            response = await client.get(url, headers=headers)
    except httpx.RequestError as exc:
        trace.finish(outcome="error", status_code=502, error=str(exc))
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

    trace.response_start(response.status_code, response.headers)
    trace.append_response(response.content)
    trace.finish(
        outcome="completed" if response.is_success else "upstream_error",
        status_code=response.status_code,
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

    incoming_payload = copy.deepcopy(payload)
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="'messages' must be a list")

    payload["model"] = payload.get("model") or config["default_model"]
    payload["messages"] = runtime.prompts.inject_messages(messages, config)
    apply_openai_reasoning_default(payload, config)

    client_stream = bool(payload.get("stream", False))
    force_stream = bool(
        not client_stream and config.get("native_popup_enabled", True)
        and config.get("native_popup_force_upstream_stream", True)
    )
    upstream_stream = client_stream or force_stream
    payload["stream"] = upstream_stream

    url = f"{config['upstream_base_url']}/chat/completions"
    request_id = new_request_id()
    headers = upstream_headers(config)
    trace = runtime.debug_logs.start(
        request_id=request_id,
        request=request,
        incoming_body=incoming_payload,
        upstream_method="POST",
        upstream_url=url,
        upstream_headers=headers,
        upstream_body=payload,
    )
    started = publish_start(
        runtime.monitor,
        request_id=request_id,
        request=request,
        api="openai",
        route="/v1/chat/completions",
        model=str(payload.get("model", "")),
        stream=client_stream,
    )

    client = httpx.AsyncClient(timeout=timeout_config(config), trust_env=False)

    try:
        upstream_request = client.build_request(
            "POST",
            url,
            headers=headers,
            json=payload,
        )
        upstream_response = await client.send(upstream_request, stream=upstream_stream)
    except httpx.RequestError as exc:
        await client.aclose()
        trace.finish(outcome="error", status_code=502, error=str(exc))
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

    trace.response_start(upstream_response.status_code, upstream_response.headers)
    content_type = upstream_response.headers.get("content-type", "").lower()
    if (
        force_stream
        and upstream_response.status_code < 400
        and "text/event-stream" in content_type
    ):
        collector = _OpenAIStreamCollector(
            runtime,
            request_id,
            str(payload.get("model", "")),
        )
        try:
            async for chunk in upstream_response.aiter_raw():
                trace.append_response(chunk)
                collector.feed(chunk)
            converted = collector.finish()
            if collector.error:
                publish_error(
                    runtime.monitor,
                    request_id,
                    started,
                    collector.error,
                    502,
                )
                trace.finish(
                    outcome="error",
                    status_code=upstream_response.status_code,
                    error=collector.error,
                )
                return JSONResponse(status_code=502, content={"error": {"message": collector.error}})
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
            return JSONResponse(status_code=502, content={"error": {"message": str(exc)}})
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
                trace.append_response(chunk)
                parser.feed(chunk)
                yield chunk
            parser.flush()
            trace.finish(status_code=upstream_response.status_code)
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
