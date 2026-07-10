from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from .proxy.reasoning_normalizer import (
    NativeNDJSONTransformer,
    OpenAISSETransformer,
    normalize_native_object,
    normalize_openai_object,
)

ASGIApp = Callable[
    [dict[str, Any], Callable[[], Awaitable[dict[str, Any]]], Callable[[dict[str, Any]], Awaitable[None]]],
    Awaitable[None],
]


def _content_type(headers: list[tuple[bytes, bytes]]) -> str:
    for key, value in headers:
        if key.lower() == b"content-type":
            return value.decode("latin-1", errors="replace").lower()
    return ""


def _replace_content_length(
    headers: list[tuple[bytes, bytes]],
    length: int | None,
) -> list[tuple[bytes, bytes]]:
    result = [
        (key, value)
        for key, value in headers
        if key.lower() not in {
            b"content-length",
            b"x-relay-reasoning-normalizer",
        }
    ]
    if length is not None:
        result.append((b"content-length", str(length).encode("ascii")))
    result.append((b"x-relay-reasoning-normalizer", b"v5.2.4"))
    return result


class VLLMReasoningResponseMiddleware:
    """Separate leaked vLLM reasoning from final content at the ASGI boundary.

    The proxy still records the raw upstream response in debug logs. Only the
    response delivered to local callers is normalized.
    """

    def __init__(self, app: ASGIApp, runtime: Any) -> None:
        self.app = app
        self.runtime = runtime

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if path not in {
            "/v1/chat/completions",
            "/api/chat",
            "/api/generate",
        }:
            await self.app(scope, receive, send)
            return

        start_message: dict[str, Any] | None = None
        buffered = bytearray()
        mode = "passthrough"
        sse: OpenAISSETransformer | None = None
        ndjson: NativeNDJSONTransformer | None = None

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal start_message, mode, sse, ndjson

            if message["type"] == "http.response.start":
                start_message = dict(message)
                status = int(message.get("status", 200))
                headers = list(message.get("headers", []))
                media_type = _content_type(headers)

                if status >= 400:
                    mode = "passthrough"
                elif path == "/v1/chat/completions" and "text/event-stream" in media_type:
                    mode = "openai-sse"
                    sse = OpenAISSETransformer()
                    start_message["headers"] = _replace_content_length(headers, None)
                    await send(start_message)
                    start_message = None
                elif path == "/v1/chat/completions" and "json" in media_type:
                    mode = "openai-json"
                elif path in {"/api/chat", "/api/generate"} and (
                    "ndjson" in media_type or "jsonl" in media_type
                ):
                    mode = "native-ndjson"
                    ndjson = NativeNDJSONTransformer()
                    start_message["headers"] = _replace_content_length(headers, None)
                    await send(start_message)
                    start_message = None
                elif path in {"/api/chat", "/api/generate"} and "json" in media_type:
                    mode = "native-json"
                else:
                    mode = "passthrough"
                    start_message["headers"] = _replace_content_length(
                        headers,
                        None,
                    )
                    await send(start_message)
                    start_message = None
                return

            if message["type"] != "http.response.body":
                await send(message)
                return

            body = bytes(message.get("body", b""))
            more_body = bool(message.get("more_body", False))

            if mode == "passthrough":
                if start_message is not None:
                    await send(start_message)
                    start_message = None
                await send(message)
                return

            if mode == "openai-sse" and sse is not None:
                for chunk in sse.feed(body):
                    await send(
                        {
                            "type": "http.response.body",
                            "body": chunk,
                            "more_body": True,
                        }
                    )
                if not more_body:
                    tail = sse.flush()
                    for index, chunk in enumerate(tail):
                        await send(
                            {
                                "type": "http.response.body",
                                "body": chunk,
                                "more_body": index < len(tail) - 1,
                            }
                        )
                    if not tail:
                        await send(
                            {
                                "type": "http.response.body",
                                "body": b"",
                                "more_body": False,
                            }
                        )
                return

            if mode == "native-ndjson" and ndjson is not None:
                for chunk in ndjson.feed(body):
                    await send(
                        {
                            "type": "http.response.body",
                            "body": chunk,
                            "more_body": True,
                        }
                    )
                if not more_body:
                    tail = ndjson.flush()
                    for index, chunk in enumerate(tail):
                        await send(
                            {
                                "type": "http.response.body",
                                "body": chunk,
                                "more_body": index < len(tail) - 1,
                            }
                        )
                    if not tail:
                        await send(
                            {
                                "type": "http.response.body",
                                "body": b"",
                                "more_body": False,
                            }
                        )
                return

            buffered.extend(body)
            if more_body:
                return

            transformed = bytes(buffered)
            try:
                value = json.loads(transformed)
                if isinstance(value, dict):
                    if mode == "openai-json":
                        normalize_openai_object(value)
                    elif mode == "native-json":
                        normalize_native_object(value)
                    transformed = json.dumps(
                        value,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass

            if start_message is None:
                await send(message)
                return

            headers = list(start_message.get("headers", []))
            start_message["headers"] = _replace_content_length(
                headers,
                len(transformed),
            )
            await send(start_message)
            start_message = None
            await send(
                {
                    "type": "http.response.body",
                    "body": transformed,
                    "more_body": False,
                }
            )

        await self.app(scope, receive, send_wrapper)
