from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from llm_relay_desk.security import SecretStoreError, SecretVault

from .json_store import JsonStore, atomic_write_json

SECRET_KEYS = ("upstream_api_key", "local_api_key")
_PUBLIC_ONLY_KEYS = {
    "secret_storage",
    "upstream_api_key_configured",
    "local_api_key_configured",
}
_PRESERVE_SECRET_VALUES = {
    "",
    "***",
    "********",
    "<redacted>",
    "<stored>",
    "<stored-securely>",
}


class SecretConfigStore(JsonStore):
    """JSON configuration whose API keys are stored outside the JSON file."""

    def __init__(
        self,
        path: Path,
        default: dict[str, Any],
        *,
        vault: SecretVault | None = None,
    ) -> None:
        self.vault = vault or SecretVault(path.parent)
        self._secret_lock = threading.RLock()
        super().__init__(path, self._without_secrets(default))
        self._migrate_plaintext_secrets()
        self._ensure_defaults()

    @staticmethod
    def _without_secrets(value: dict[str, Any]) -> dict[str, Any]:
        result = {
            key: item
            for key, item in value.items()
            if key not in SECRET_KEYS and key not in _PUBLIC_ONLY_KEYS
        }
        return result

    def _raw_read(self) -> dict[str, Any]:
        return super().read()

    def _migrate_plaintext_secrets(self) -> None:
        with self._secret_lock:
            raw = self._raw_read()
            changed = False
            for key in SECRET_KEYS:
                if key not in raw:
                    continue
                value = str(raw.get(key) or "").strip()
                if value:
                    current = self.vault.get(key)
                    if current is None:
                        self.vault.set(key, value)
                raw.pop(key, None)
                changed = True
            if changed:
                atomic_write_json(self.path, raw)

    def _ensure_defaults(self) -> None:
        if self.vault.get("upstream_api_key") is None:
            self.vault.set("upstream_api_key", "ollama")
        if self.vault.get("local_api_key") is None:
            self.vault.set(
                "local_api_key",
                SecretVault.generate_local_api_key(),
            )

    def read(self) -> dict[str, Any]:
        with self._secret_lock:
            value = self._raw_read()
            for key in SECRET_KEYS:
                value[key] = self.vault.get(key) or ""
            return value

    def public_view(self) -> dict[str, Any]:
        with self._secret_lock:
            value = self._raw_read()
            statuses = {key: self.vault.status(key) for key in SECRET_KEYS}
            value["upstream_api_key"] = ""
            value["local_api_key"] = ""
            value["upstream_api_key_configured"] = statuses[
                "upstream_api_key"
            ]["configured"]
            value["local_api_key_configured"] = statuses[
                "local_api_key"
            ]["configured"]
            value["secret_storage"] = {
                "format_version": 1,
                "upstream_api_key": statuses["upstream_api_key"],
                "local_api_key": statuses["local_api_key"],
            }
            return value

    def write(self, value: dict[str, Any]) -> dict[str, Any]:
        with self._secret_lock:
            current_effective = {
                key: self.vault.get(key) or ""
                for key in SECRET_KEYS
            }
            for key in SECRET_KEYS:
                if key not in value:
                    continue
                candidate = value.get(key)
                normalized = "" if candidate is None else str(candidate).strip()
                if normalized in _PRESERVE_SECRET_VALUES:
                    continue
                if normalized == current_effective[key]:
                    continue
                self.vault.set(key, normalized)

            sanitized = self._without_secrets(dict(value))
            atomic_write_json(self.path, sanitized)
            return self.read()

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._secret_lock:
            current = self.read()
            updated = {**current, **values}
            return self.write(updated)

    def clear_secret(self, name: str) -> None:
        if name not in SECRET_KEYS:
            raise KeyError(name)
        self.vault.delete(name)

    def secret_status(self) -> dict[str, Any]:
        result: dict[str, Any] = {"format_version": 1}
        for key in SECRET_KEYS:
            result[key] = self.vault.status(key)
        return result

    def reveal_secret(self, name: str) -> str:
        if name not in SECRET_KEYS:
            raise KeyError(name)
        return self.vault.get(name) or ""
