from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "11434"))
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).resolve()
STATIC_DIR = BASE_DIR / "static"
MONITOR_DIR = BASE_DIR / "monitor"
CONFIG_PATH = DATA_DIR / "config.json"
PROMPTS_PATH = DATA_DIR / "prompts.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG: dict[str, Any] = {
    "upstream_base_url": "http://127.0.0.1:11435/v1",
    "upstream_api_key": "ollama",
    "local_api_key": "sk-local-ollama-change-me",
    "default_model": "qwen3.6:35b",
    "default_reasoning_effort": "",
    "request_timeout_seconds": 600,
    "prompt_enabled": True,
}

DEFAULT_PROMPTS: dict[str, Any] = {
    "active": "默认中文助手",
    "profiles": {
        "默认中文助手": (
            "你是一个本地部署的中文助手。\n\n"
            "要求：\n"
            "1. 优先准确回答问题，不编造事实。\n"
            "2. 对不确定的信息明确说明不确定性。\n"
            "3. 默认使用简体中文。\n"
            "4. 输出结构清晰，避免无关展开。\n"
            "5. 涉及命令、配置或代码时，给出可直接执行的完整示例。"
        ),
        "提示词测试": (
            "当用户询问“提示词测试码是什么”时，"
            "只回复：prompt_test_001"
        ),
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


class JsonStore:
    def __init__(self, path: Path, default: dict[str, Any]):
        self.path = path
        self.default = default
        self.lock = threading.RLock()
        if not self.path.exists():
            atomic_write_json(self.path, self.default)

    def read(self) -> dict[str, Any]:
        with self.lock:
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                value = json.loads(json.dumps(self.default, ensure_ascii=False))
                atomic_write_json(self.path, value)
            return value

    def write(self, value: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            atomic_write_json(self.path, value)
            return value


class MonitorHub:
    """In-memory, best-effort side channel for the independent monitor UI.

    API forwarding never awaits monitor consumers. Slow or disconnected monitor
    windows therefore cannot delay or pause callers.
    """

    def __init__(
        self,
        *,
        history_limit: int = 60,
        queue_size: int = 2048,
        capture_char_limit: int = 1_000_000,
    ) -> None:
        self.history_limit = history_limit
        self.queue_size = queue_size
        self.capture_char_limit = capture_char_limit
        self.records: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.queue_size)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(queue)

    def snapshot(self) -> list[dict[str, Any]]:
        return [dict(record) for record in self.records.values()]

    def clear(self) -> None:
        self.records.clear()
        self.publish({"type": "monitor_cleared", "at": utc_now_iso()})

    def _append_text(self, record: dict[str, Any], field: str, text: str) -> None:
        if not text:
            return
        current = str(record.get(field, ""))
        combined = current + text
        if len(combined) > self.capture_char_limit:
            combined = combined[-self.capture_char_limit :]
            record[f"{field}_truncated"] = True
        record[field] = combined

    def _update_record(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        request_id = event.get("request_id")
        if not request_id:
            return

        if event_type == "request_start":
            record = {
                "request_id": request_id,
                "api": event.get("api", ""),
                "route": event.get("route", ""),
                "model": event.get("model", ""),
                "source": event.get("source", ""),
                "user_agent": event.get("user_agent", ""),
                "stream": bool(event.get("stream")),
                "started_at": event.get("started_at", utc_now_iso()),
                "finished_at": None,
                "elapsed_ms": None,
                "status_code": None,
                "status": "streaming",
                "content": "",
                "reasoning": "",
                "error": "",
            }
            self.records[request_id] = record
            self.records.move_to_end(request_id)
            while len(self.records) > self.history_limit:
                self.records.popitem(last=False)
            return

        record = self.records.get(request_id)
        if record is None:
            return

        if event_type == "content_delta":
            self._append_text(record, "content", str(event.get("text", "")))
        elif event_type == "reasoning_delta":
            self._append_text(record, "reasoning", str(event.get("text", "")))
        elif event_type == "request_done":
            record["status"] = "complete"
            record["finished_at"] = event.get("finished_at", utc_now_iso())
            record["elapsed_ms"] = event.get("elapsed_ms")
            record["status_code"] = event.get("status_code")
        elif event_type == "request_error":
            record["status"] = "error"
            record["finished_at"] = event.get("finished_at", utc_now_iso())
            record["elapsed_ms"] = event.get("elapsed_ms")
            record["status_code"] = event.get("status_code")
            record["error"] = str(event.get("error", "未知错误"))
        elif event_type == "request_cancelled":
            record["status"] = "cancelled"
            record["finished_at"] = event.get("finished_at", utc_now_iso())
            record["elapsed_ms"] = event.get("elapsed_ms")
            record["status_code"] = event.get("status_code")
            record["error"] = str(event.get("error", "调用方已断开连接"))

    def publish(self, event: dict[str, Any]) -> None:
        self._update_record(event)
        if not self.subscribers:
            return

        for queue in tuple(self.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A slow monitor must never back-pressure the API. Replace its
                # stale queue with one current snapshot so it can recover.
                try:
                    while True:
                        queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(
                        {
                            "type": "snapshot",
                            "requests": self.snapshot(),
                            "resync": True,
                        }
                    )
                except asyncio.QueueFull:
                    pass


config_store = JsonStore(CONFIG_PATH, DEFAULT_CONFIG)
prompt_store = JsonStore(PROMPTS_PATH, DEFAULT_PROMPTS)
monitor_hub = MonitorHub()


def normalize_upstream_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    for suffix in ("/chat/completions", "/models"):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        raise HTTPException(
            status_code=400,
            detail="上游地址必须以 http:// 或 https:// 开头",
        )
    return url


def validate_config(payload: dict[str, Any]) -> dict[str, Any]:
    current = config_store.read()
    updated = {**current, **payload}

    updated["upstream_base_url"] = normalize_upstream_base_url(
        str(updated.get("upstream_base_url", ""))
    )
    updated["upstream_api_key"] = str(updated.get("upstream_api_key", "ollama")).strip()
    updated["local_api_key"] = str(updated.get("local_api_key", "")).strip()
    updated["default_model"] = str(updated.get("default_model", "")).strip()

    reasoning = str(updated.get("default_reasoning_effort", "")).strip().lower()
    allowed_reasoning = {"", "none", "low", "medium", "high", "max"}
    if reasoning not in allowed_reasoning:
        raise HTTPException(
            status_code=400,
            detail="默认思考强度必须为 none/low/medium/high/max 或留空",
        )
    updated["default_reasoning_effort"] = reasoning

    try:
        timeout = int(updated.get("request_timeout_seconds", 600))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="超时时间必须为整数") from exc
    if timeout < 30 or timeout > 7200:
        raise HTTPException(status_code=400, detail="超时时间范围为 30～7200 秒")
    updated["request_timeout_seconds"] = timeout
    updated["prompt_enabled"] = bool(updated.get("prompt_enabled", True))

    if not updated["default_model"]:
        raise HTTPException(status_code=400, detail="默认模型不能为空")

    return updated


def sanitize_profile_name(name: str) -> str:
    clean = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name.strip())
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        raise HTTPException(status_code=400, detail="提示词名称不能为空")
    if len(clean) > 80:
        raise HTTPException(status_code=400, detail="提示词名称不能超过 80 个字符")
    return clean


def get_active_prompt() -> tuple[str | None, str]:
    prompt_data = prompt_store.read()
    active = prompt_data.get("active")
    profiles = prompt_data.get("profiles", {})
    if not isinstance(profiles, dict):
        return None, ""
    content = profiles.get(active, "") if active else ""
    return active, str(content or "")


def verify_local_api_key(authorization: str | None) -> None:
    local_api_key = str(config_store.read().get("local_api_key", "")).strip()
    if not local_api_key:
        return
    if authorization != f"Bearer {local_api_key}":
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


def upstream_headers(config: dict[str, Any]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.get('upstream_api_key', 'ollama')}",
        "Content-Type": "application/json",
    }


def timeout_config(config: dict[str, Any]) -> httpx.Timeout:
    seconds = int(config.get("request_timeout_seconds", 600))
    return httpx.Timeout(
        connect=min(30.0, float(seconds)),
        read=float(seconds),
        write=min(120.0, float(seconds)),
        pool=30.0,
    )


def inject_active_prompt(
    messages: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    if not config.get("prompt_enabled", True):
        return messages
    _, prompt = get_active_prompt()
    if not prompt.strip():
        return messages
    return [{"role": "system", "content": prompt}, *messages]


def native_upstream_root(config: dict[str, Any]) -> str:
    """Convert an OpenAI base URL into the Ollama native API root."""
    base = str(config.get("upstream_base_url", "")).strip().rstrip("/")
    if base.lower().endswith("/v1"):
        base = base[:-3].rstrip("/")
    return base


def request_source(request: Request) -> tuple[str, str]:
    source = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "").strip()[:300]
    return source, user_agent


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:16]}"


def text_from_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, dict):
                    text = text.get("value", "")
                if text is None:
                    text = item.get("content", "")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    if isinstance(value, dict):
        text = value.get("text") or value.get("value") or value.get("content")
        return text_from_content(text)
    return ""


def extract_reasoning(container: dict[str, Any]) -> str:
    for key in ("reasoning_content", "reasoning", "thinking"):
        text = text_from_content(container.get(key))
        if text:
            return text
    return ""


def publish_openai_object(request_id: str, value: dict[str, Any]) -> None:
    choices = value.get("choices")
    if not isinstance(choices, list):
        return
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        container = choice.get("delta")
        if not isinstance(container, dict):
            container = choice.get("message")
        if not isinstance(container, dict):
            container = choice
        reasoning = extract_reasoning(container)
        content = text_from_content(container.get("content"))
        if not content:
            content = text_from_content(container.get("text"))
        if reasoning:
            monitor_hub.publish(
                {"type": "reasoning_delta", "request_id": request_id, "text": reasoning}
            )
        if content:
            monitor_hub.publish(
                {"type": "content_delta", "request_id": request_id, "text": content}
            )


def publish_native_object(request_id: str, value: dict[str, Any]) -> None:
    message = value.get("message")
    if isinstance(message, dict):
        reasoning = extract_reasoning(message)
        content = text_from_content(message.get("content"))
    else:
        reasoning = extract_reasoning(value)
        content = text_from_content(value.get("response"))

    if reasoning:
        monitor_hub.publish(
            {"type": "reasoning_delta", "request_id": request_id, "text": reasoning}
        )
    if content:
        monitor_hub.publish(
            {"type": "content_delta", "request_id": request_id, "text": content}
        )


def error_from_body(body: bytes) -> str:
    if not body:
        return "上游返回空错误响应"
    try:
        value = json.loads(body)
        if isinstance(value, dict):
            error = value.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error)[:1200]
            return str(value.get("message") or value.get("detail") or value)[:1200]
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    return body.decode("utf-8", errors="replace")[:1200]


class OpenAISSEParser:
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> None:
        self.buffer.extend(chunk)
        while True:
            lf_index = self.buffer.find(b"\n\n")
            crlf_index = self.buffer.find(b"\r\n\r\n")
            candidates = [index for index in (lf_index, crlf_index) if index >= 0]
            if not candidates:
                break
            index = min(candidates)
            delimiter_length = 4 if crlf_index == index else 2
            block = bytes(self.buffer[:index])
            del self.buffer[: index + delimiter_length]
            self._process_block(block)

    def flush(self) -> None:
        if self.buffer:
            self._process_block(bytes(self.buffer))
            self.buffer.clear()

    def _process_block(self, block: bytes) -> None:
        text = block.decode("utf-8", errors="replace")
        data_lines = []
        for line in text.replace("\r\n", "\n").split("\n"):
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
        if isinstance(value, dict):
            publish_openai_object(self.request_id, value)


class NativeNDJSONParser:
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> None:
        self.buffer.extend(chunk)
        while True:
            index = self.buffer.find(b"\n")
            if index < 0:
                break
            line = bytes(self.buffer[:index]).strip()
            del self.buffer[: index + 1]
            self._process_line(line)

    def flush(self) -> None:
        line = bytes(self.buffer).strip()
        self.buffer.clear()
        self._process_line(line)

    def _process_line(self, line: bytes) -> None:
        if not line:
            return
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if isinstance(value, dict):
            publish_native_object(self.request_id, value)


def publish_start(
    *,
    request_id: str,
    request: Request,
    api: str,
    route: str,
    model: str,
    stream: bool,
) -> float:
    source, user_agent = request_source(request)
    monitor_hub.publish(
        {
            "type": "request_start",
            "request_id": request_id,
            "api": api,
            "route": route,
            "model": model,
            "source": source,
            "user_agent": user_agent,
            "stream": stream,
            "started_at": utc_now_iso(),
        }
    )
    return time.perf_counter()


def publish_done(request_id: str, started: float, status_code: int) -> None:
    monitor_hub.publish(
        {
            "type": "request_done",
            "request_id": request_id,
            "finished_at": utc_now_iso(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "status_code": status_code,
        }
    )


def publish_error(
    request_id: str,
    started: float,
    error: str,
    status_code: int | None = None,
) -> None:
    monitor_hub.publish(
        {
            "type": "request_error",
            "request_id": request_id,
            "finished_at": utc_now_iso(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "status_code": status_code,
            "error": error,
        }
    )


async def forward_native_request(
    *,
    request: Request,
    path: str,
    method: str,
    inject_prompt_mode: str | None = None,
) -> Response:
    """Forward an Ollama native API request, preserving streaming responses."""
    config = config_store.read()
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
            payload["messages"] = inject_active_prompt(messages, config)

        elif inject_prompt_mode == "generate":
            payload["model"] = payload.get("model") or config["default_model"]
            if config.get("prompt_enabled", True):
                _, active_prompt = get_active_prompt()
                if active_prompt.strip():
                    existing_system = str(payload.get("system", "")).strip()
                    payload["system"] = (
                        f"{active_prompt}\n\n{existing_system}"
                        if existing_system
                        else active_prompt
                    )

    stream = bool(payload.get("stream", True)) if payload is not None else False
    monitored = inject_prompt_mode in {"chat", "generate"}
    request_id = new_request_id() if monitored else ""
    started = (
        publish_start(
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
            publish_error(request_id, started, f"无法连接 Ollama 上游：{exc}", 502)
        return JSONResponse(
            status_code=502,
            content={"error": f"Cannot reach Ollama native upstream: {exc}", "upstream": url},
            headers={"X-Relay-Request-ID": request_id} if monitored else None,
        )

    if not stream or upstream_response.status_code >= 400:
        body = await upstream_response.aread()
        status_code = upstream_response.status_code
        media_type = upstream_response.headers.get("content-type", "application/json").split(";")[0]
        await upstream_response.aclose()
        await client.aclose()

        if monitored:
            if status_code < 400:
                try:
                    value = json.loads(body)
                    if isinstance(value, dict):
                        publish_native_object(request_id, value)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
                publish_done(request_id, started, status_code)
            else:
                publish_error(request_id, started, error_from_body(body), status_code)

        return Response(
            content=body,
            status_code=status_code,
            media_type=media_type,
            headers={"X-Relay-Request-ID": request_id} if monitored else None,
        )

    parser = NativeNDJSONParser(request_id)

    async def stream_body() -> AsyncIterator[bytes]:
        completed = False
        try:
            async for chunk in upstream_response.aiter_raw():
                if monitored:
                    parser.feed(chunk)
                yield chunk
            if monitored:
                parser.flush()
                publish_done(request_id, started, upstream_response.status_code)
            completed = True
        except asyncio.CancelledError:
            if monitored:
                monitor_hub.publish(
                    {
                        "type": "request_cancelled",
                        "request_id": request_id,
                        "finished_at": utc_now_iso(),
                        "elapsed_ms": round((time.perf_counter() - started) * 1000),
                        "status_code": upstream_response.status_code,
                        "error": "调用方已断开连接",
                    }
                )
            raise
        except Exception as exc:
            if monitored:
                publish_error(request_id, started, f"读取上游流失败：{exc}", upstream_response.status_code)
            raise
        finally:
            await upstream_response.aclose()
            await client.aclose()
            if monitored and not completed:
                parser.flush()

    return StreamingResponse(
        stream_body(),
        status_code=upstream_response.status_code,
        media_type=upstream_response.headers.get("content-type", "application/x-ndjson").split(";")[0],
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Relay-Request-ID": request_id,
        },
    )


app = FastAPI(
    title="LLM Relay Desk",
    version="3.0.0",
    description="本地 LLM API 转发、提示词管理与独立实时响应监视器",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.get("/health")
async def health() -> dict[str, Any]:
    config = config_store.read()
    active, prompt = get_active_prompt()
    return {
        "service": "LLM Relay Desk",
        "version": app.version,
        "status": "ok",
        "listen": f"http://{APP_HOST}:{APP_PORT}",
        "openai_base_url": f"http://{APP_HOST}:{APP_PORT}/v1",
        "monitor_url": f"http://{APP_HOST}:{APP_PORT}/monitor/",
        "upstream": config.get("upstream_base_url"),
        "model": config.get("default_model"),
        "prompt_enabled": config.get("prompt_enabled"),
        "active_prompt": active,
        "active_prompt_length": len(prompt),
        "monitor_history_count": len(monitor_hub.records),
        "monitor_clients": len(monitor_hub.subscribers),
    }


@app.websocket("/ws/monitor")
async def monitor_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = monitor_hub.subscribe()
    try:
        await websocket.send_json({"type": "snapshot", "requests": monitor_hub.snapshot()})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20.0)
            except asyncio.TimeoutError:
                event = {"type": "heartbeat", "at": utc_now_iso()}
            await websocket.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        monitor_hub.unsubscribe(queue)


@app.delete("/admin/monitor/history")
async def clear_monitor_history() -> dict[str, Any]:
    monitor_hub.clear()
    return {"ok": True}


@app.get("/admin/config")
async def admin_get_config() -> dict[str, Any]:
    return config_store.read()


@app.put("/admin/config")
async def admin_put_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    updated = validate_config(payload)
    config_store.write(updated)
    return {"ok": True, "config": updated}


@app.get("/admin/prompts")
async def admin_get_prompts() -> dict[str, Any]:
    data = prompt_store.read()
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
    return {"active": data.get("active"), "profiles": profiles, "names": sorted(profiles.keys())}


@app.put("/admin/prompts/{profile_name}")
async def admin_save_prompt(profile_name: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    name = sanitize_profile_name(profile_name)
    content = str(payload.get("content", ""))
    data = prompt_store.read()
    profiles = data.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
        data["profiles"] = profiles
    profiles[name] = content
    if not data.get("active"):
        data["active"] = name
    prompt_store.write(data)
    return {"ok": True, "name": name, "active": data.get("active")}


@app.post("/admin/prompts/{profile_name}/activate")
async def admin_activate_prompt(profile_name: str) -> dict[str, Any]:
    name = sanitize_profile_name(profile_name)
    data = prompt_store.read()
    profiles = data.get("profiles", {})
    if name not in profiles:
        raise HTTPException(status_code=404, detail="提示词不存在")
    data["active"] = name
    prompt_store.write(data)
    return {"ok": True, "active": name}


@app.delete("/admin/prompts/{profile_name}")
async def admin_delete_prompt(profile_name: str) -> dict[str, Any]:
    name = sanitize_profile_name(profile_name)
    data = prompt_store.read()
    profiles = data.get("profiles", {})
    if name not in profiles:
        raise HTTPException(status_code=404, detail="提示词不存在")
    del profiles[name]
    if data.get("active") == name:
        data["active"] = next(iter(sorted(profiles.keys())), None)
    prompt_store.write(data)
    return {"ok": True, "active": data.get("active")}


@app.post("/admin/test-upstream")
async def admin_test_upstream() -> JSONResponse:
    config = config_store.read()
    url = f"{config['upstream_base_url']}/models"
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout_config(config), trust_env=False) as client:
            response = await client.get(url, headers=upstream_headers(config))
    except httpx.RequestError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "ok": False,
                "message": str(exc),
                "upstream": url,
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            },
        )

    try:
        upstream_body: Any = response.json()
    except ValueError:
        upstream_body = response.text[:500]

    return JSONResponse(
        status_code=200 if response.is_success else 502,
        content={
            "ok": response.is_success,
            "upstream": url,
            "upstream_status": response.status_code,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "response": upstream_body,
        },
    )


# Ollama native API compatibility. Native clients usually do not send a Bearer
# key, so these routes remain local-only by default through APP_HOST=127.0.0.1.
@app.get("/api/tags")
async def native_tags(request: Request) -> Response:
    return await forward_native_request(request=request, path="/api/tags", method="GET")


@app.get("/api/ps")
async def native_ps(request: Request) -> Response:
    return await forward_native_request(request=request, path="/api/ps", method="GET")


@app.get("/api/version")
async def native_version(request: Request) -> Response:
    return await forward_native_request(request=request, path="/api/version", method="GET")


@app.post("/api/show")
async def native_show(request: Request) -> Response:
    return await forward_native_request(request=request, path="/api/show", method="POST")


@app.post("/api/chat")
async def native_chat(request: Request) -> Response:
    return await forward_native_request(
        request=request,
        path="/api/chat",
        method="POST",
        inject_prompt_mode="chat",
    )


@app.post("/api/generate")
async def native_generate(request: Request) -> Response:
    return await forward_native_request(
        request=request,
        path="/api/generate",
        method="POST",
        inject_prompt_mode="generate",
    )


@app.post("/api/embed")
async def native_embed(request: Request) -> Response:
    return await forward_native_request(request=request, path="/api/embed", method="POST")


@app.post("/api/embeddings")
async def native_embeddings(request: Request) -> Response:
    return await forward_native_request(request=request, path="/api/embeddings", method="POST")


@app.get("/v1/models")
async def list_models(authorization: str | None = Header(default=None)) -> Response:
    verify_local_api_key(authorization)
    config = config_store.read()
    url = f"{config['upstream_base_url']}/models"

    try:
        async with httpx.AsyncClient(timeout=timeout_config(config), trust_env=False) as client:
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
        media_type=response.headers.get("content-type", "application/json").split(";")[0],
    )


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    verify_local_api_key(authorization)
    config = config_store.read()

    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="'messages' must be a list")

    payload["model"] = payload.get("model") or config["default_model"]
    payload["messages"] = inject_active_prompt(messages, config)

    # Thinking/reasoning fields remain pass-through. The proxy does not add or
    # remove reasoning_effort, thinking, reasoning, tools, or tool_choice.
    stream = bool(payload.get("stream", False))
    url = f"{config['upstream_base_url']}/chat/completions"
    request_id = new_request_id()
    started = publish_start(
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
        publish_error(request_id, started, f"无法连接上游：{exc}", 502)
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
        media_type = upstream_response.headers.get("content-type", "application/json").split(";")[0]
        await upstream_response.aclose()
        await client.aclose()

        if status_code < 400:
            try:
                value = json.loads(body)
                if isinstance(value, dict):
                    publish_openai_object(request_id, value)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            publish_done(request_id, started, status_code)
        else:
            publish_error(request_id, started, error_from_body(body), status_code)

        return Response(
            content=body,
            status_code=status_code,
            media_type=media_type,
            headers={"X-Relay-Request-ID": request_id},
        )

    parser = OpenAISSEParser(request_id)

    async def stream_body() -> AsyncIterator[bytes]:
        completed = False
        try:
            async for chunk in upstream_response.aiter_raw():
                parser.feed(chunk)
                yield chunk
            parser.flush()
            publish_done(request_id, started, upstream_response.status_code)
            completed = True
        except asyncio.CancelledError:
            monitor_hub.publish(
                {
                    "type": "request_cancelled",
                    "request_id": request_id,
                    "finished_at": utc_now_iso(),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000),
                    "status_code": upstream_response.status_code,
                    "error": "调用方已断开连接",
                }
            )
            raise
        except Exception as exc:
            publish_error(request_id, started, f"读取上游流失败：{exc}", upstream_response.status_code)
            raise
        finally:
            await upstream_response.aclose()
            await client.aclose()
            if not completed:
                parser.flush()

    return StreamingResponse(
        stream_body(),
        status_code=upstream_response.status_code,
        media_type=upstream_response.headers.get("content-type", "text/event-stream").split(";")[0],
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Relay-Request-ID": request_id,
        },
    )


app.mount("/monitor", StaticFiles(directory=MONITOR_DIR, html=True), name="monitor")
app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=APP_HOST,
        port=APP_PORT,
        reload=False,
        log_level="info",
    )
