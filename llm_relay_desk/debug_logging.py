from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Mapping

from fastapi import Request

from llm_relay_desk.storage import JsonStore

_REDACTED = "<redacted>"
_SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "cookie",
    "set-cookie",
}
_SENSITIVE_BODY_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
    "password",
    "secret",
    "client_secret",
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")
_STREAM_SUFFIXES = ("*.json", "*.jsonl")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _redact_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    if not headers:
        return {}
    result: dict[str, str] = {}
    for key, value in headers.items():
        name = str(key)
        result[name] = _REDACTED if name.lower() in _SENSITIVE_HEADERS else str(value)
    return result


def _redact_body(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            result[name] = (
                _REDACTED
                if name.lower() in _SENSITIVE_BODY_KEYS
                else _redact_body(item)
            )
        return result
    if isinstance(value, list):
        return [_redact_body(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_body(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _safe_name(value: str, fallback: str) -> str:
    cleaned = _SAFE_NAME.sub("_", value).strip("._-")
    return (cleaned or fallback)[:80]


def _decode_utf8(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _parse_sse_values(text: str) -> tuple[list[Any], bool]:
    values: list[Any] = []
    done_seen = False
    normalized = text.replace("\r\n", "\n")
    for block in normalized.split("\n\n"):
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines:
            continue
        data = "\n".join(data_lines).strip()
        if not data:
            continue
        if data == "[DONE]":
            done_seen = True
            continue
        try:
            values.append(json.loads(data))
        except json.JSONDecodeError:
            values.append(data)
    return values, done_seen


def _append_content(target: list[Any], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, list):
        target.extend(deepcopy(value))
    else:
        target.append(deepcopy(value))


def _finalize_content(parts: list[Any]) -> Any:
    if not parts:
        return ""
    if all(isinstance(item, str) for item in parts):
        return "".join(parts)
    result: list[Any] = []
    for item in parts:
        if isinstance(item, list):
            result.extend(item)
        else:
            result.append(item)
    return result


def _merge_tool_calls(
    destination: dict[int, dict[str, Any]],
    value: Any,
) -> None:
    if not isinstance(value, list):
        return
    for fallback_index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index", fallback_index))
        except (TypeError, ValueError):
            index = fallback_index
        current = destination.setdefault(index, {})
        for key, item_value in item.items():
            if key in {"index", "function"}:
                continue
            if item_value is not None:
                current[key] = deepcopy(item_value)
        function = item.get("function")
        if isinstance(function, dict):
            merged_function = current.setdefault("function", {})
            name = function.get("name")
            if name is not None:
                merged_function["name"] = str(name)
            arguments = function.get("arguments")
            if arguments is not None:
                previous = merged_function.get("arguments", "")
                if isinstance(arguments, str) and isinstance(previous, str):
                    merged_function["arguments"] = previous + arguments
                else:
                    merged_function["arguments"] = deepcopy(arguments)


def _aggregate_openai_stream(values: list[Any]) -> Any:
    dictionary_values = [value for value in values if isinstance(value, dict)]
    if not dictionary_values:
        return values[-1] if len(values) == 1 else {"events": values}

    top_level: dict[str, Any] = {}
    choices_state: dict[int, dict[str, Any]] = {}
    saw_choices = False

    for event in dictionary_values:
        for key, value in event.items():
            if key != "choices" and value is not None:
                top_level[key] = deepcopy(value)

        choices = event.get("choices")
        if not isinstance(choices, list):
            continue
        saw_choices = True
        for fallback_index, choice in enumerate(choices):
            if not isinstance(choice, dict):
                continue
            try:
                index = int(choice.get("index", fallback_index))
            except (TypeError, ValueError):
                index = fallback_index
            state = choices_state.setdefault(
                index,
                {
                    "message": {},
                    "content_parts": [],
                    "reasoning_parts": {},
                    "refusal_parts": [],
                    "text_parts": [],
                    "tool_calls": {},
                    "function_call": {},
                    "finish_reason": None,
                    "extra": {},
                },
            )
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                message = choice.get("message")
                delta = message if isinstance(message, dict) else {}

            role = delta.get("role")
            if role is not None:
                state["message"]["role"] = role
            if "content" in delta:
                _append_content(state["content_parts"], delta.get("content"))
            for reasoning_key in ("reasoning_content", "reasoning", "thinking"):
                if reasoning_key in delta:
                    parts = state["reasoning_parts"].setdefault(reasoning_key, [])
                    _append_content(parts, delta.get(reasoning_key))
            if "refusal" in delta:
                _append_content(state["refusal_parts"], delta.get("refusal"))
            if "tool_calls" in delta:
                _merge_tool_calls(state["tool_calls"], delta.get("tool_calls"))
            function_call = delta.get("function_call")
            if isinstance(function_call, dict):
                merged = state["function_call"]
                if function_call.get("name") is not None:
                    merged["name"] = function_call["name"]
                arguments = function_call.get("arguments")
                if arguments is not None:
                    previous = merged.get("arguments", "")
                    merged["arguments"] = (
                        previous + arguments
                        if isinstance(previous, str) and isinstance(arguments, str)
                        else deepcopy(arguments)
                    )

            known_delta = {
                "role",
                "content",
                "reasoning_content",
                "reasoning",
                "thinking",
                "refusal",
                "tool_calls",
                "function_call",
            }
            for key, value in delta.items():
                if key not in known_delta and value is not None:
                    state["message"][key] = deepcopy(value)

            if "text" in choice:
                _append_content(state["text_parts"], choice.get("text"))
            if choice.get("finish_reason") is not None:
                state["finish_reason"] = choice.get("finish_reason")
            for key, value in choice.items():
                if key not in {
                    "index",
                    "delta",
                    "message",
                    "text",
                    "finish_reason",
                } and value is not None:
                    state["extra"][key] = deepcopy(value)

    if not saw_choices:
        return dictionary_values[-1] if len(dictionary_values) == 1 else {
            **top_level,
            "events": values,
        }

    object_name = str(top_level.get("object", ""))
    if object_name.endswith(".chunk"):
        top_level["object"] = object_name[: -len(".chunk")]
    elif not object_name:
        top_level["object"] = "chat.completion"

    completed_choices: list[dict[str, Any]] = []
    for index in sorted(choices_state):
        state = choices_state[index]
        message = state["message"]
        message.setdefault("role", "assistant")
        if state["content_parts"]:
            message["content"] = _finalize_content(state["content_parts"])
        elif "content" not in message:
            message["content"] = ""
        for key, parts in state["reasoning_parts"].items():
            message[key] = _finalize_content(parts)
        if state["refusal_parts"]:
            message["refusal"] = _finalize_content(state["refusal_parts"])
        if state["tool_calls"]:
            message["tool_calls"] = [
                state["tool_calls"][tool_index]
                for tool_index in sorted(state["tool_calls"])
            ]
        if state["function_call"]:
            message["function_call"] = state["function_call"]

        completed: dict[str, Any] = {
            "index": index,
            "message": message,
            "finish_reason": state["finish_reason"],
        }
        if state["text_parts"]:
            completed["text"] = _finalize_content(state["text_parts"])
        completed.update(state["extra"])
        completed_choices.append(completed)

    top_level["choices"] = completed_choices
    return top_level


def _parse_ndjson_values(text: str) -> list[Any]:
    values: list[Any] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            values.append(json.loads(stripped))
        except json.JSONDecodeError:
            values.append(stripped)
    return values


def _aggregate_ollama_stream(values: list[Any]) -> Any:
    dictionary_values = [value for value in values if isinstance(value, dict)]
    if not dictionary_values:
        return values[-1] if len(values) == 1 else {"events": values}
    if len(dictionary_values) == 1:
        return dictionary_values[0]

    result: dict[str, Any] = {}
    message: dict[str, Any] = {}
    message_content: list[Any] = []
    message_reasoning: dict[str, list[Any]] = {}
    top_content: list[Any] = []
    top_reasoning: dict[str, list[Any]] = {}
    tool_calls: list[Any] = []

    for event in dictionary_values:
        for key, value in event.items():
            if key not in {"message", "response", "thinking", "reasoning"}:
                result[key] = deepcopy(value)

        event_message = event.get("message")
        if isinstance(event_message, dict):
            if event_message.get("role") is not None:
                message["role"] = event_message["role"]
            _append_content(message_content, event_message.get("content"))
            for key in ("thinking", "reasoning", "reasoning_content"):
                if key in event_message:
                    parts = message_reasoning.setdefault(key, [])
                    _append_content(parts, event_message.get(key))
            if isinstance(event_message.get("tool_calls"), list):
                tool_calls.extend(deepcopy(event_message["tool_calls"]))
            for key, value in event_message.items():
                if key not in {
                    "role",
                    "content",
                    "thinking",
                    "reasoning",
                    "reasoning_content",
                    "tool_calls",
                }:
                    message[key] = deepcopy(value)

        if "response" in event:
            _append_content(top_content, event.get("response"))
        for key in ("thinking", "reasoning", "reasoning_content"):
            if key in event:
                parts = top_reasoning.setdefault(key, [])
                _append_content(parts, event.get(key))

    if message or message_content or message_reasoning or tool_calls:
        message.setdefault("role", "assistant")
        message["content"] = _finalize_content(message_content)
        for key, parts in message_reasoning.items():
            message[key] = _finalize_content(parts)
        if tool_calls:
            message["tool_calls"] = tool_calls
        result["message"] = message
    if top_content:
        result["response"] = _finalize_content(top_content)
    for key, parts in top_reasoning.items():
        result[key] = _finalize_content(parts)
    return result


def _complete_response_body(
    raw: bytes,
    content_type: str,
) -> tuple[Any, str, int, bool]:
    text = _decode_utf8(raw)
    normalized_type = content_type.lower()
    stripped = text.lstrip()

    if "text/event-stream" in normalized_type or stripped.startswith("data:"):
        values, done_seen = _parse_sse_values(text)
        return _aggregate_openai_stream(values), "openai-sse", len(values), done_seen

    if "ndjson" in normalized_type or "jsonlines" in normalized_type:
        values = _parse_ndjson_values(text)
        return _aggregate_ollama_stream(values), "ollama-ndjson", len(values), False

    if not raw:
        return None, "empty", 0, False

    try:
        return json.loads(text), "json", 1, False
    except json.JSONDecodeError:
        # Some Ollama-compatible gateways omit the NDJSON media type.
        values = _parse_ndjson_values(text)
        if len(values) > 1 and all(isinstance(value, dict) for value in values):
            return _aggregate_ollama_stream(values), "ollama-ndjson", len(values), False
        return text, "text", 1, False


class NullDebugLogSession:
    enabled = False
    path: Path | None = None

    def response_start(
        self,
        status_code: int,
        headers: Mapping[str, Any] | None = None,
    ) -> None:
        del status_code, headers

    def append_response(self, chunk: bytes) -> None:
        del chunk

    def finish(
        self,
        *,
        outcome: str = "completed",
        status_code: int | None = None,
        error: str | None = None,
    ) -> None:
        del outcome, status_code, error


class DebugLogSession:
    enabled = True

    def __init__(
        self,
        manager: "DebugLogManager",
        temp_path: Path,
        final_path: Path,
        request_document: dict[str, Any],
    ) -> None:
        self.manager = manager
        self.temp_path = temp_path
        self.path = final_path
        self._lock = threading.RLock()
        self._response_buffer: BinaryIO = tempfile.SpooledTemporaryFile(
            max_size=1024 * 1024,
            mode="w+b",
        )
        self._sha256 = hashlib.sha256()
        self._response_bytes = 0
        self._response_chunks = 0
        self._status_code: int | None = None
        self._response_headers: dict[str, str] = {}
        self._response_started_at: str | None = None
        self._closed = False
        self._request_document = request_document

    def response_start(
        self,
        status_code: int,
        headers: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            if self._closed:
                return
            self._status_code = int(status_code)
            self._response_headers = _redact_headers(headers)
            self._response_started_at = _utc_now()

    def append_response(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            if self._closed:
                return
            data = bytes(chunk)
            self._response_buffer.write(data)
            self._sha256.update(data)
            self._response_bytes += len(data)
            self._response_chunks += 1

    def finish(
        self,
        *,
        outcome: str = "completed",
        status_code: int | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            if self._closed:
                return
            final_status = self._status_code if status_code is None else int(status_code)
            try:
                self._response_buffer.seek(0)
                raw = self._response_buffer.read()
                content_type = next(
                    (
                        value
                        for key, value in self._response_headers.items()
                        if key.lower() == "content-type"
                    ),
                    "",
                )
                body, response_format, stream_events, done_seen = _complete_response_body(
                    raw,
                    content_type,
                )
                response: dict[str, Any] = {
                    "started_at": self._response_started_at,
                    "completed_at": _utc_now(),
                    "outcome": str(outcome),
                    "status_code": final_status,
                    "headers": self._response_headers,
                    "content_type": content_type.split(";", 1)[0] if content_type else "",
                    "format": response_format,
                    "body": body,
                    "stream_events": stream_events,
                    "stream_done_marker": done_seen,
                    "transport_chunks": self._response_chunks,
                    "response_bytes": self._response_bytes,
                    "response_sha256": self._sha256.hexdigest(),
                }
                if error:
                    response["error"] = str(error)

                document = {
                    **self._request_document,
                    "upstream_response": response,
                }
                with self.temp_path.open(
                    "w",
                    encoding="utf-8",
                    newline="\n",
                ) as file:
                    json.dump(document, file, ensure_ascii=False, indent=2)
                    file.write("\n")
                try:
                    self.temp_path.replace(self.path)
                except OSError:
                    self.path = self.temp_path
            except Exception:
                # Debug logging is best effort and must never alter proxy behavior.
                try:
                    self.temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            finally:
                self._response_buffer.close()
                self._closed = True
        self.manager.cleanup()


class DebugLogManager:
    """Best-effort per-request complete-response JSON logger.

    Logging is intentionally isolated from proxy control flow: any filesystem
    failure disables only the current trace and never changes the API response.
    """

    def __init__(self, config_store: JsonStore, data_dir: Path) -> None:
        self.config_store = config_store
        self.data_dir = data_dir
        self._cleanup_lock = threading.RLock()

    def resolve_directory(self, config: dict[str, Any] | None = None) -> Path:
        current = config or self.config_store.read()
        configured = str(current.get("debug_log_directory", "debug_logs")).strip()
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = self.data_dir / path
        return path.resolve()

    def start(
        self,
        *,
        request_id: str,
        request: Request,
        incoming_body: Any,
        upstream_method: str,
        upstream_url: str,
        upstream_headers: Mapping[str, Any] | None,
        upstream_body: Any,
    ) -> DebugLogSession | NullDebugLogSession:
        try:
            config = self.config_store.read()
            if not bool(config.get("debug_logging_enabled", False)):
                return NullDebugLogSession()
            directory = self.resolve_directory(config)
            directory.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            route_name = _safe_name(request.url.path, "request")
            request_name = _safe_name(request_id, "request")
            final_path = directory / f"{timestamp}_{request_name}_{route_name}.json"
            temp_path = final_path.with_suffix(final_path.suffix + ".tmp")
            client_info = request.client
            request_document = {
                "format_version": 2,
                "timestamp": _utc_now(),
                "request_id": request_id,
                "client_request": {
                    "method": request.method,
                    "url": str(request.url),
                    "path": request.url.path,
                    "query": list(request.query_params.multi_items()),
                    "client": (
                        {"host": client_info.host, "port": client_info.port}
                        if client_info is not None
                        else None
                    ),
                    "headers": _redact_headers(request.headers),
                    "body": _redact_body(incoming_body),
                },
                "upstream_request": {
                    "method": upstream_method.upper(),
                    "url": upstream_url,
                    "headers": _redact_headers(upstream_headers),
                    "body": _redact_body(upstream_body),
                },
            }
            return DebugLogSession(self, temp_path, final_path, request_document)
        except Exception:
            return NullDebugLogSession()

    def _log_files(self, directory: Path) -> list[Path]:
        files: dict[Path, None] = {}
        for pattern in _STREAM_SUFFIXES:
            for path in directory.glob(pattern):
                files[path] = None
        return list(files)

    def status(self) -> dict[str, Any]:
        config = self.config_store.read()
        directory = self.resolve_directory(config)
        try:
            file_count = len(self._log_files(directory)) if directory.exists() else 0
        except OSError:
            file_count = 0
        return {
            "enabled": bool(config.get("debug_logging_enabled", False)),
            "directory": str(directory),
            "retention_files": int(config.get("debug_log_retention_files", 100)),
            "file_count": file_count,
            "format": "json-per-request-complete-response",
            "response_mode": "complete",
            "sensitive_headers_redacted": True,
        }

    def clear(self) -> int:
        directory = self.resolve_directory()
        removed = 0
        try:
            paths = self._log_files(directory)
            paths.extend(directory.glob("*.json.tmp"))
            paths.extend(directory.glob("*.jsonl.tmp"))
            for path in dict.fromkeys(paths):
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    continue
        except OSError:
            return removed
        return removed

    def cleanup(self) -> None:
        with self._cleanup_lock:
            try:
                config = self.config_store.read()
                keep = max(1, int(config.get("debug_log_retention_files", 100)))
                directory = self.resolve_directory(config)
                files = sorted(
                    self._log_files(directory),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
                for path in files[keep:]:
                    try:
                        path.unlink()
                    except OSError:
                        continue
            except Exception:
                return
