from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
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

from .common import error_from_body, openai_upstream_base, timeout_config, upstream_headers
from .extractors import extract_reasoning, publish_native_object, text_from_content
from .reasoning import apply_openai_reasoning_default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_line(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def _model_digest(model: str) -> str:
    return "sha256:" + hashlib.sha256(model.encode("utf-8")).hexdigest()


def _model_entry(value: dict[str, Any] | str, default_model: str) -> dict[str, Any]:
    if isinstance(value, dict):
        model = str(value.get("id") or value.get("name") or default_model)
        owned_by = str(value.get("owned_by") or "openai")
        created = value.get("created")
    else:
        model = str(value or default_model)
        owned_by = "openai"
        created = None

    if isinstance(created, (int, float)):
        modified_at = datetime.fromtimestamp(float(created), timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        modified_at = _now_iso()

    return {
        "name": model,
        "model": model,
        "modified_at": modified_at,
        "size": 0,
        "digest": _model_digest(model),
        "details": {
            "parent_model": "",
            "format": "api",
            "family": owned_by,
            "families": [owned_by],
            "parameter_size": "remote",
            "quantization_level": "",
        },
    }


def _openai_error_response(body: bytes, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error_from_body(body)})


def _convert_tool_calls_to_openai(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    converted: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        arguments = function.get("arguments", {})
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        converted.append(
            {
                "id": str(item.get("id") or f"call_{index}_{uuid.uuid4().hex[:8]}"),
                "type": "function",
                "function": {
                    "name": str(function.get("name") or ""),
                    "arguments": arguments,
                },
            }
        )
    return converted


def _convert_tool_calls_to_ollama(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    converted: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        arguments: Any = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        converted.append(
            {
                "function": {
                    "name": str(function.get("name") or ""),
                    "arguments": arguments,
                }
            }
        )
    return converted


def _convert_message_to_openai(message: dict[str, Any]) -> dict[str, Any]:
    role = str(message.get("role") or "user")
    content: Any = message.get("content", "")
    images = message.get("images")
    if isinstance(images, list) and images:
        parts: list[dict[str, Any]] = []
        if content:
            parts.append({"type": "text", "text": str(content)})
        for image in images:
            data = str(image or "")
            if not data:
                continue
            if not data.startswith("data:"):
                data = f"data:image/png;base64,{data}"
            parts.append({"type": "image_url", "image_url": {"url": data}})
        content = parts

    converted: dict[str, Any] = {"role": role, "content": content}
    if message.get("name") is not None:
        converted["name"] = str(message["name"])
    if role == "tool" and message.get("tool_call_id") is not None:
        converted["tool_call_id"] = str(message["tool_call_id"])
    tool_calls = _convert_tool_calls_to_openai(message.get("tool_calls"))
    if tool_calls:
        converted["tool_calls"] = tool_calls
    return converted


def _apply_options(native: dict[str, Any], payload: dict[str, Any]) -> None:
    options = native.get("options")
    if not isinstance(options, dict):
        options = {}

    direct_map = {
        "temperature": "temperature",
        "top_p": "top_p",
        "seed": "seed",
        "stop": "stop",
        "frequency_penalty": "frequency_penalty",
        "presence_penalty": "presence_penalty",
    }
    for source, target in direct_map.items():
        if source in options:
            payload[target] = options[source]
    if "num_predict" in options:
        payload["max_tokens"] = options["num_predict"]
    elif native.get("max_tokens") is not None:
        payload["max_tokens"] = native["max_tokens"]

    format_value = native.get("format")
    if format_value == "json":
        payload["response_format"] = {"type": "json_object"}
    elif isinstance(format_value, dict):
        # DeepSeek and many OpenAI-compatible providers support json_object but
        # not the newer json_schema response format. Prefer broad compatibility.
        payload["response_format"] = {"type": "json_object"}

    direct_thinking = native.get("thinking")
    direct_effort = native.get("reasoning_effort")
    think = native.get("think")

    if "thinking" in native:
        payload["thinking"] = direct_thinking
    elif isinstance(think, bool):
        payload["thinking"] = {"type": "enabled" if think else "disabled"}
    elif isinstance(think, str) and think.strip():
        payload["thinking"] = {"type": "enabled"}

    if "reasoning_effort" in native:
        payload["reasoning_effort"] = direct_effort
    elif isinstance(think, str) and think.strip():
        effort = think.strip().lower()
        if effort in {"low", "medium", "high", "max", "xhigh"}:
            payload["reasoning_effort"] = effort

    if native.get("tools") is not None:
        payload["tools"] = native["tools"]
    if native.get("tool_choice") is not None:
        payload["tool_choice"] = native["tool_choice"]


def _chat_payload(runtime: Runtime, native: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    messages = native.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="'messages' must be a list")
    injected = runtime.prompts.inject_messages(messages, config)
    payload: dict[str, Any] = {
        "model": str(native.get("model") or config.get("default_model", "")),
        "messages": [
            _convert_message_to_openai(item)
            for item in injected
            if isinstance(item, dict)
        ],
        "stream": bool(native.get("stream", True)),
    }
    _apply_options(native, payload)
    apply_openai_reasoning_default(payload, config, caller_payload=native)
    return payload


def _generate_payload(runtime: Runtime, native: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    native_copy = dict(native)
    runtime.prompts.inject_generate_system(native_copy, config)
    messages: list[dict[str, Any]] = []
    system = native_copy.get("system")
    if system:
        messages.append({"role": "system", "content": str(system)})
    prompt = native_copy.get("prompt", "")
    messages.append({"role": "user", "content": str(prompt)})
    payload: dict[str, Any] = {
        "model": str(native_copy.get("model") or config.get("default_model", "")),
        "messages": messages,
        "stream": bool(native_copy.get("stream", True)),
    }
    _apply_options(native_copy, payload)
    apply_openai_reasoning_default(payload, config, caller_payload=native)
    return payload


def _usage_counts(usage: Any) -> tuple[int, int]:
    if not isinstance(usage, dict):
        return 0, 0
    return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


def _done_object(
    *,
    model: str,
    mode: str,
    finish_reason: str | None,
    usage: Any,
    started: float,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prompt_tokens, completion_tokens = _usage_counts(usage)
    elapsed_ns = max(0, int((time.perf_counter() - started) * 1_000_000_000))
    common: dict[str, Any] = {
        "model": model,
        "created_at": _now_iso(),
        "done": True,
        "done_reason": finish_reason or "stop",
        "total_duration": elapsed_ns,
        "load_duration": 0,
        "prompt_eval_count": prompt_tokens,
        "prompt_eval_duration": 0,
        "eval_count": completion_tokens,
        "eval_duration": 0,
    }
    if mode == "chat":
        message: dict[str, Any] = {"role": "assistant", "content": ""}
        if tool_calls:
            message["tool_calls"] = tool_calls
        common["message"] = message
    else:
        common["response"] = ""
    return common


def _convert_nonstream_chat(value: dict[str, Any], model: str, started: float) -> dict[str, Any]:
    choices = value.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = text_from_content(message.get("content"))
    reasoning = extract_reasoning(message)
    converted_message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning:
        converted_message["thinking"] = reasoning
    tool_calls = _convert_tool_calls_to_ollama(message.get("tool_calls"))
    if tool_calls:
        converted_message["tool_calls"] = tool_calls
    result = _done_object(
        model=str(value.get("model") or model),
        mode="chat",
        finish_reason=str(choice.get("finish_reason") or "stop"),
        usage=value.get("usage"),
        started=started,
        tool_calls=tool_calls,
    )
    result["message"] = converted_message
    return result


def _convert_nonstream_generate(value: dict[str, Any], model: str, started: float) -> dict[str, Any]:
    choices = value.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    result = _done_object(
        model=str(value.get("model") or model),
        mode="generate",
        finish_reason=str(choice.get("finish_reason") or "stop"),
        usage=value.get("usage"),
        started=started,
    )
    result["response"] = text_from_content(message.get("content"))
    reasoning = extract_reasoning(message)
    if reasoning:
        result["thinking"] = reasoning
    return result


class _SSEDecoder:
    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> list[str]:
        self.buffer.extend(chunk)
        values: list[str] = []
        while True:
            normalized = bytes(self.buffer).replace(b"\r\n", b"\n")
            index = normalized.find(b"\n\n")
            if index < 0:
                break
            # Determine the consumed byte count from the original buffer.
            original = bytes(self.buffer)
            lf_index = original.find(b"\n\n")
            crlf_index = original.find(b"\r\n\r\n")
            candidates = [(lf_index, 2), (crlf_index, 4)]
            candidates = [(pos, length) for pos, length in candidates if pos >= 0]
            pos, length = min(candidates, key=lambda item: item[0])
            block = bytes(self.buffer[:pos])
            del self.buffer[: pos + length]
            data_lines: list[str] = []
            for line in block.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n"):
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
            if data_lines:
                values.append("\n".join(data_lines).strip())
        return values

    def flush(self) -> list[str]:
        if not self.buffer:
            return []
        block = bytes(self.buffer)
        self.buffer.clear()
        data_lines: list[str] = []
        for line in block.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n"):
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        return ["\n".join(data_lines).strip()] if data_lines else []


class _StreamState:
    def __init__(self, model: str) -> None:
        self.model = model
        self.finish_reason: str | None = None
        self.usage: Any = None
        self.done_seen = False
        self.tool_calls: dict[int, dict[str, Any]] = {}

    def absorb_tool_deltas(self, value: Any) -> None:
        if not isinstance(value, list):
            return
        for item in value:
            if not isinstance(item, dict):
                continue
            index = int(item.get("index") or 0)
            current = self.tool_calls.setdefault(
                index,
                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
            )
            if item.get("id"):
                current["id"] = str(item["id"])
            function = item.get("function")
            if isinstance(function, dict):
                if function.get("name"):
                    current["function"]["name"] += str(function["name"])
                if function.get("arguments"):
                    current["function"]["arguments"] += str(function["arguments"])

    def ollama_tool_calls(self) -> list[dict[str, Any]]:
        ordered = [self.tool_calls[key] for key in sorted(self.tool_calls)]
        return _convert_tool_calls_to_ollama(ordered)


def _stream_delta_objects(value: dict[str, Any], state: _StreamState, mode: str) -> list[dict[str, Any]]:
    if value.get("model"):
        state.model = str(value["model"])
    if value.get("usage") is not None:
        state.usage = value["usage"]

    output: list[dict[str, Any]] = []
    choices = value.get("choices")
    if not isinstance(choices, list):
        return output
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        if choice.get("finish_reason") is not None:
            state.finish_reason = str(choice["finish_reason"])
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        content = text_from_content(delta.get("content"))
        reasoning = extract_reasoning(delta)
        state.absorb_tool_deltas(delta.get("tool_calls"))
        if not content and not reasoning:
            continue
        item: dict[str, Any] = {
            "model": state.model,
            "created_at": _now_iso(),
            "done": False,
        }
        if mode == "chat":
            message: dict[str, Any] = {"role": "assistant", "content": content}
            if reasoning:
                message["thinking"] = reasoning
            item["message"] = message
        else:
            item["response"] = content
            if reasoning:
                item["thinking"] = reasoning
        output.append(item)
    return output


async def _forward_models(runtime: Runtime, request: Request, config: dict[str, Any]) -> Response:
    url = f"{openai_upstream_base(config)}/models"
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
        async with httpx.AsyncClient(timeout=timeout_config(config), trust_env=False) as client:
            response = await client.get(url, headers=headers)
    except httpx.RequestError as exc:
        trace.finish(outcome="error", status_code=502, error=str(exc))
        return JSONResponse(status_code=502, content={"error": f"Cannot reach OpenAI-compatible upstream: {exc}"})

    trace.response_start(response.status_code, response.headers)
    trace.append_response(response.content)
    trace.finish(
        outcome="completed" if response.is_success else "upstream_error",
        status_code=response.status_code,
        error=error_from_body(response.content) if not response.is_success else None,
    )
    default_model = str(config.get("default_model", ""))
    if response.is_success:
        try:
            value = response.json()
        except ValueError:
            value = {}
        data = value.get("data") if isinstance(value, dict) else None
        entries = [_model_entry(item, default_model) for item in data] if isinstance(data, list) else []
    elif response.status_code in {404, 405}:
        # Some compatible providers omit /models. Keep Ollama clients usable by
        # exposing the configured default model instead of propagating a 404.
        entries = []
    else:
        return _openai_error_response(response.content, response.status_code)

    if not entries and default_model:
        entries = [_model_entry(default_model, default_model)]
    return JSONResponse(content={"models": entries})


async def _forward_show(request: Request, config: dict[str, Any]) -> Response:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    model = str(payload.get("model") or payload.get("name") or config.get("default_model", ""))
    entry = _model_entry(model, model)
    return JSONResponse(
        content={
            "license": "",
            "modelfile": f"# OpenAI-compatible remote model\nFROM {model}",
            "parameters": "",
            "template": "",
            "details": entry["details"],
            "model_info": {"general.architecture": "remote-api", "general.name": model},
            "capabilities": ["completion", "tools", "thinking"],
            "modified_at": entry["modified_at"],
        }
    )


async def _forward_embeddings(runtime: Runtime, request: Request, config: dict[str, Any], legacy: bool) -> Response:
    try:
        native = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    incoming_native = copy.deepcopy(native)
    model = str(native.get("model") or config.get("default_model", ""))
    input_value = native.get("prompt") if legacy else native.get("input")
    if input_value is None:
        input_value = native.get("input", native.get("prompt", ""))
    url = f"{openai_upstream_base(config)}/embeddings"
    outbound = {"model": model, "input": input_value}
    request_id = new_request_id()
    headers = upstream_headers(config)
    trace = runtime.debug_logs.start(
        request_id=request_id,
        request=request,
        incoming_body=incoming_native,
        upstream_method="POST",
        upstream_url=url,
        upstream_headers=headers,
        upstream_body=outbound,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout_config(config), trust_env=False) as client:
            response = await client.post(
                url,
                headers=headers,
                json=outbound,
            )
    except httpx.RequestError as exc:
        trace.finish(outcome="error", status_code=502, error=str(exc))
        return JSONResponse(status_code=502, content={"error": f"Cannot reach OpenAI-compatible upstream: {exc}"})
    body = await response.aread()
    trace.response_start(response.status_code, response.headers)
    trace.append_response(body)
    trace.finish(
        outcome="completed" if response.is_success else "upstream_error",
        status_code=response.status_code,
        error=error_from_body(body) if not response.is_success else None,
    )
    if not response.is_success:
        return _openai_error_response(body, response.status_code)
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse(status_code=502, content={"error": "Invalid embedding response from upstream"})
    data = value.get("data") if isinstance(value, dict) else None
    embeddings = [item.get("embedding", []) for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    if legacy:
        return JSONResponse(content={"embedding": embeddings[0] if embeddings else []})
    return JSONResponse(
        content={
            "model": model,
            "embeddings": embeddings,
            "total_duration": 0,
            "load_duration": 0,
            "prompt_eval_count": int((value.get("usage") or {}).get("prompt_tokens") or 0),
        }
    )


async def _collect_sse_as_nonstream_ollama(
    runtime: Runtime,
    upstream_response: httpx.Response,
    request_id: str,
    model: str,
    mode: str,
    started_request: float,
    trace: Any,
) -> dict[str, Any]:
    decoder = _SSEDecoder()
    state = _StreamState(model)
    content_parts: list[str] = []
    reasoning_parts: list[str] = []

    def absorb(value: dict[str, Any]) -> None:
        for converted in _stream_delta_objects(value, state, mode):
            publish_native_object(runtime.monitor, request_id, converted)
            if mode == "chat":
                message = converted.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    reasoning = message.get("thinking")
                else:
                    content = ""
                    reasoning = ""
            else:
                content = converted.get("response")
                reasoning = converted.get("thinking")
            if isinstance(content, str) and content:
                content_parts.append(content)
            if isinstance(reasoning, str) and reasoning:
                reasoning_parts.append(reasoning)

    async for chunk in upstream_response.aiter_raw():
        trace.append_response(chunk)
        for data in decoder.feed(chunk):
            if not data or data == "[DONE]":
                continue
            try:
                value = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and isinstance(value.get("error"), (dict, str)):
                error = value["error"]
                message = str(error.get("message") if isinstance(error, dict) else error)
                raise RuntimeError(message)
            if isinstance(value, dict):
                absorb(value)
    for data in decoder.flush():
        if not data or data == "[DONE]":
            continue
        try:
            value = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            absorb(value)

    final = _done_object(
        model=state.model,
        mode=mode,
        finish_reason=state.finish_reason,
        usage=state.usage,
        started=started_request,
        tool_calls=state.ollama_tool_calls(),
    )
    if mode == "chat":
        message = final.get("message")
        if not isinstance(message, dict):
            message = {"role": "assistant"}
            final["message"] = message
        message["content"] = "".join(content_parts)
        if reasoning_parts:
            message["thinking"] = "".join(reasoning_parts)
    else:
        final["response"] = "".join(content_parts)
        if reasoning_parts:
            final["thinking"] = "".join(reasoning_parts)
    return final


async def _forward_chat_or_generate(
    runtime: Runtime,
    request: Request,
    config: dict[str, Any],
    mode: str,
) -> Response:
    try:
        native: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    incoming_native = copy.deepcopy(native)
    payload = _chat_payload(runtime, native, config) if mode == "chat" else _generate_payload(runtime, native, config)
    model = str(payload["model"])
    client_stream = bool(payload.get("stream", True))
    force_stream = bool(
        not client_stream and config.get("native_popup_enabled", True)
        and config.get("native_popup_force_upstream_stream", True)
    )
    upstream_stream = client_stream or force_stream
    payload["stream"] = upstream_stream
    url = f"{openai_upstream_base(config)}/chat/completions"
    request_id = new_request_id()
    headers = upstream_headers(config)
    trace = runtime.debug_logs.start(
        request_id=request_id,
        request=request,
        incoming_body=incoming_native,
        upstream_method="POST",
        upstream_url=url,
        upstream_headers=headers,
        upstream_body=payload,
    )
    started_monitor = publish_start(
        runtime.monitor,
        request_id=request_id,
        request=request,
        api="ollama-adapter",
        route=f"/api/{mode}",
        model=model,
        stream=client_stream,
    )
    started_request = time.perf_counter()
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
        publish_error(runtime.monitor, request_id, started_monitor, str(exc), 502)
        return JSONResponse(
            status_code=502,
            content={"error": f"Cannot reach OpenAI-compatible upstream: {exc}"},
            headers={"X-Relay-Request-ID": request_id},
        )

    trace.response_start(upstream_response.status_code, upstream_response.headers)
    content_type = upstream_response.headers.get("content-type", "").lower()
    if (
        force_stream
        and upstream_response.status_code < 400
        and "text/event-stream" in content_type
    ):
        try:
            converted = await _collect_sse_as_nonstream_ollama(
                runtime,
                upstream_response,
                request_id,
                model,
                mode,
                started_request,
                trace,
            )
            trace.finish(status_code=upstream_response.status_code)
            publish_done(runtime.monitor, request_id, started_monitor, upstream_response.status_code)
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
                started_monitor,
                str(exc),
                upstream_response.status_code,
            )
            return JSONResponse(status_code=502, content={"error": str(exc)})
        finally:
            await upstream_response.aclose()
            await client.aclose()

    if not upstream_stream or upstream_response.status_code >= 400 or "text/event-stream" not in content_type:
        body = await upstream_response.aread()
        trace.append_response(body)
        status_code = upstream_response.status_code
        await upstream_response.aclose()
        await client.aclose()
        trace.finish(
            outcome="completed" if status_code < 400 else "upstream_error",
            status_code=status_code,
            error=error_from_body(body) if status_code >= 400 else None,
        )
        if status_code >= 400:
            publish_error(runtime.monitor, request_id, started_monitor, error_from_body(body), status_code)
            response = _openai_error_response(body, status_code)
            response.headers["X-Relay-Request-ID"] = request_id
            return response
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            publish_error(runtime.monitor, request_id, started_monitor, "Invalid JSON from upstream", 502)
            return JSONResponse(status_code=502, content={"error": "Invalid JSON from upstream"})
        converted = (
            _convert_nonstream_chat(value, model, started_request)
            if mode == "chat"
            else _convert_nonstream_generate(value, model, started_request)
        )
        publish_native_object(runtime.monitor, request_id, converted)
        publish_done(runtime.monitor, request_id, started_monitor, status_code)
        if client_stream:
            return Response(
                content=_json_line(converted),
                media_type="application/x-ndjson",
                headers={"X-Relay-Request-ID": request_id},
            )
        return JSONResponse(content=converted, headers={"X-Relay-Request-ID": request_id})

    decoder = _SSEDecoder()
    state = _StreamState(model)

    async def stream_body() -> AsyncIterator[bytes]:
        completed = False
        final_emitted = False
        try:
            async for chunk in upstream_response.aiter_raw():
                trace.append_response(chunk)
                for data in decoder.feed(chunk):
                    if data == "[DONE]":
                        state.done_seen = True
                        continue
                    if not data:
                        continue
                    try:
                        value = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict) and isinstance(value.get("error"), (dict, str)):
                        error = value["error"]
                        message = str(error.get("message") if isinstance(error, dict) else error)
                        yield _json_line({"error": message})
                        continue
                    if not isinstance(value, dict):
                        continue
                    for converted in _stream_delta_objects(value, state, mode):
                        publish_native_object(runtime.monitor, request_id, converted)
                        yield _json_line(converted)
            for data in decoder.flush():
                if not data or data == "[DONE]":
                    continue
                try:
                    value = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    for converted in _stream_delta_objects(value, state, mode):
                        publish_native_object(runtime.monitor, request_id, converted)
                        yield _json_line(converted)
            final = _done_object(
                model=state.model,
                mode=mode,
                finish_reason=state.finish_reason,
                usage=state.usage,
                started=started_request,
                tool_calls=state.ollama_tool_calls(),
            )
            yield _json_line(final)
            final_emitted = True
            trace.finish(status_code=upstream_response.status_code)
            publish_done(runtime.monitor, request_id, started_monitor, upstream_response.status_code)
            completed = True
        except asyncio.CancelledError:
            trace.finish(
                outcome="cancelled",
                status_code=upstream_response.status_code,
                error="client disconnected",
            )
            publish_cancelled(runtime.monitor, request_id, started_monitor, upstream_response.status_code)
            raise
        except Exception as exc:
            trace.finish(
                outcome="error",
                status_code=upstream_response.status_code,
                error=str(exc),
            )
            publish_error(runtime.monitor, request_id, started_monitor, str(exc), upstream_response.status_code)
            if not final_emitted:
                yield _json_line({"error": str(exc)})
            raise
        finally:
            await upstream_response.aclose()
            await client.aclose()
            if not completed:
                pass

    return StreamingResponse(
        stream_body(),
        status_code=upstream_response.status_code,
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Relay-Request-ID": request_id,
        },
    )


async def forward_openai_as_ollama(
    runtime: Runtime,
    *,
    request: Request,
    path: str,
    method: str,
    inject_prompt_mode: str | None = None,
) -> Response:
    del method, inject_prompt_mode
    config = runtime.config_store.read()

    if path == "/api/tags":
        return await _forward_models(runtime, request, config)
    if path == "/api/ps":
        return JSONResponse(content={"models": []})
    if path == "/api/version":
        return JSONResponse(content={"version": "0.0.0-llm-relay-openai-adapter"})
    if path == "/api/show":
        return await _forward_show(request, config)
    if path == "/api/chat":
        return await _forward_chat_or_generate(runtime, request, config, "chat")
    if path == "/api/generate":
        return await _forward_chat_or_generate(runtime, request, config, "generate")
    if path == "/api/embed":
        return await _forward_embeddings(runtime, request, config, legacy=False)
    if path == "/api/embeddings":
        return await _forward_embeddings(runtime, request, config, legacy=True)
    return JSONResponse(status_code=404, content={"error": f"Unsupported Ollama compatibility path: {path}"})
