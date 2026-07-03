from __future__ import annotations

import json

from llm_relay_desk.monitoring import MonitorHub

from .extractors import publish_native_object, publish_openai_object


class OpenAISSEParser:
    def __init__(self, hub: MonitorHub, request_id: str) -> None:
        self.hub = hub
        self.request_id = request_id
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> None:
        self.buffer.extend(chunk)
        while True:
            lf_index = self.buffer.find(b"\n\n")
            crlf_index = self.buffer.find(b"\r\n\r\n")
            candidates = [
                index for index in (lf_index, crlf_index) if index >= 0
            ]
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
            publish_openai_object(self.hub, self.request_id, value)


class NativeNDJSONParser:
    def __init__(self, hub: MonitorHub, request_id: str) -> None:
        self.hub = hub
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
            publish_native_object(self.hub, self.request_id, value)
