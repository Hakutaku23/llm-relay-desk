from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


class JsonStore:
    """Thread-safe JSON file store with atomic replacement writes."""

    def __init__(self, path: Path, default: dict[str, Any]) -> None:
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

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        """Atomically merge selected keys into the current JSON object."""
        with self.lock:
            current = self.read()
            updated = {**current, **values}
            atomic_write_json(self.path, updated)
            return updated
