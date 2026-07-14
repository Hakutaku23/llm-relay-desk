from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_relay_desk.security import (
    EncryptedFileSecretBackend,
    SecretReadOnlyError,
    SecretVault,
)
from llm_relay_desk.storage import SecretConfigStore


def build_store(tmp_path: Path, initial: dict | None = None) -> SecretConfigStore:
    config_path = tmp_path / "data" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if initial is not None:
        config_path.write_text(json.dumps(initial), encoding="utf-8")
    encrypted = EncryptedFileSecretBackend(
        tmp_path / "data" / "secrets.enc",
        tmp_path / "outside-project" / "master.key",
    )
    vault = SecretVault(
        tmp_path / "data",
        encrypted_backend=encrypted,
        use_keyring=False,
    )
    return SecretConfigStore(
        config_path,
        {"config_schema_version": 14, "default_model": "test-model"},
        vault=vault,
    )


def test_plaintext_keys_are_migrated_and_removed(tmp_path: Path) -> None:
    store = build_store(
        tmp_path,
        {
            "config_schema_version": 13,
            "default_model": "demo",
            "upstream_api_key": "upstream-secret-value",
            "local_api_key": "local-secret-value",
        },
    )

    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert "upstream_api_key" not in raw
    assert "local_api_key" not in raw
    assert store.read()["upstream_api_key"] == "upstream-secret-value"
    assert store.read()["local_api_key"] == "local-secret-value"
    assert b"upstream-secret-value" not in (tmp_path / "data" / "secrets.enc").read_bytes()


def test_public_view_never_returns_secret_values(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    store.write(
        {
            "config_schema_version": 14,
            "default_model": "demo",
            "upstream_api_key": "new-upstream-secret",
            "local_api_key": "new-local-secret",
        }
    )

    public = store.public_view()
    assert public["upstream_api_key"] == ""
    assert public["local_api_key"] == ""
    assert public["upstream_api_key_configured"] is True
    assert public["local_api_key_configured"] is True
    assert "new-upstream-secret" not in json.dumps(public)


def test_blank_input_preserves_existing_secret(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    store.write(
        {
            "config_schema_version": 14,
            "default_model": "demo",
            "upstream_api_key": "keep-me",
        }
    )
    store.write(
        {
            "config_schema_version": 14,
            "default_model": "changed",
            "upstream_api_key": "",
        }
    )
    assert store.read()["upstream_api_key"] == "keep-me"
    assert store.read()["default_model"] == "changed"


def test_environment_secret_is_read_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_RELAY_UPSTREAM_API_KEY", "from-env")
    encrypted = EncryptedFileSecretBackend(
        tmp_path / "data" / "secrets.enc",
        tmp_path / "outside-project" / "master.key",
    )
    vault = SecretVault(
        tmp_path / "data",
        encrypted_backend=encrypted,
        use_keyring=False,
    )
    assert vault.get("upstream_api_key") == "from-env"
    with pytest.raises(SecretReadOnlyError):
        vault.set("upstream_api_key", "replacement")
