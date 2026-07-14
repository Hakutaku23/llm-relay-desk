from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import threading
from pathlib import Path
from typing import Any

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError as exc:  # pragma: no cover - dependency error is explicit
    raise RuntimeError(
        "缺少 cryptography，无法启用安全密钥存储。请重新安装 requirements.txt。"
    ) from exc


SECRET_ENV_VARS = {
    "upstream_api_key": "LLM_RELAY_UPSTREAM_API_KEY",
    "local_api_key": "LLM_RELAY_LOCAL_API_KEY",
}


class SecretStoreError(RuntimeError):
    pass


class SecretReadOnlyError(SecretStoreError):
    pass


def _chmod_private(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _default_master_key_path() -> Path:
    explicit = os.getenv("LLM_RELAY_MASTER_KEY_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    system = platform.system().lower()
    if system == "windows":
        base = Path(
            os.getenv("LOCALAPPDATA")
            or os.getenv("APPDATA")
            or str(Path.home())
        )
        return base / "LLM Relay Desk" / "master.key"
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "LLM Relay Desk" / "master.key"
    base = Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "llm-relay-desk" / "master.key"


class EncryptedFileSecretBackend:
    """Fernet-encrypted fallback with its master key outside the project tree."""

    def __init__(self, secret_path: Path, key_path: Path | None = None) -> None:
        self.secret_path = secret_path
        self.key_path = key_path or _default_master_key_path()
        self._lock = threading.RLock()

    def _fernet(self) -> Fernet:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if self.key_path.exists():
            _chmod_private(self.key_path)
            key = self.key_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            temp = self.key_path.with_suffix(self.key_path.suffix + ".tmp")
            temp.write_bytes(key + b"\n")
            _chmod_private(temp)
            temp.replace(self.key_path)
            _chmod_private(self.key_path)
        try:
            return Fernet(key)
        except (TypeError, ValueError) as exc:
            raise SecretStoreError(f"主密钥文件无效：{self.key_path}") from exc

    def _read_all(self) -> dict[str, str]:
        if not self.secret_path.exists():
            return {}
        try:
            raw = self._fernet().decrypt(self.secret_path.read_bytes())
            value = json.loads(raw.decode("utf-8"))
        except (OSError, InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecretStoreError(
                f"安全密钥文件损坏或无法解密：{self.secret_path}"
            ) from exc
        if not isinstance(value, dict):
            raise SecretStoreError("安全密钥文件格式无效")
        secrets_value = value.get("secrets", {})
        if not isinstance(secrets_value, dict):
            raise SecretStoreError("安全密钥文件内容无效")
        return {
            str(key): str(item)
            for key, item in secrets_value.items()
            if item is not None
        }

    def _write_all(self, values: dict[str, str]) -> None:
        self.secret_path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "format_version": 1,
            "secrets": values,
        }
        plaintext = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        encrypted = self._fernet().encrypt(plaintext)
        temp = self.secret_path.with_suffix(self.secret_path.suffix + ".tmp")
        temp.write_bytes(encrypted)
        _chmod_private(temp)
        temp.replace(self.secret_path)
        _chmod_private(self.secret_path)

    def get(self, name: str) -> str | None:
        with self._lock:
            return self._read_all().get(name)

    def set(self, name: str, value: str) -> None:
        with self._lock:
            current = self._read_all()
            current[name] = value
            self._write_all(current)

    def delete(self, name: str) -> None:
        with self._lock:
            current = self._read_all()
            if name not in current:
                return
            del current[name]
            self._write_all(current)


class KeyringSecretBackend:
    def __init__(self, service_name: str, module: Any) -> None:
        self.service_name = service_name
        self._module = module

    @classmethod
    def try_create(cls, service_name: str) -> "KeyringSecretBackend | None":
        try:
            import keyring

            backend = keyring.get_keyring()
            backend_name = f"{backend.__class__.__module__}.{backend.__class__.__name__}".lower()
            if "plaintext" in backend_name or "fail" in backend_name:
                return None
            if float(getattr(backend, "priority", 0) or 0) <= 0:
                return None
            keyring.get_password(service_name, "__health_check__")
            return cls(service_name, keyring)
        except Exception:
            return None

    def get(self, name: str) -> str | None:
        try:
            return self._module.get_password(self.service_name, name)
        except Exception:
            return None

    def set(self, name: str, value: str) -> bool:
        try:
            self._module.set_password(self.service_name, name, value)
            return True
        except Exception:
            return False

    def delete(self, name: str) -> None:
        try:
            self._module.delete_password(self.service_name, name)
        except Exception:
            pass


class SecretVault:
    """Environment override, OS keyring, then encrypted-file fallback."""

    def __init__(
        self,
        data_dir: Path,
        *,
        encrypted_backend: EncryptedFileSecretBackend | None = None,
        keyring_backend: KeyringSecretBackend | None = None,
        use_keyring: bool = True,
    ) -> None:
        resolved = data_dir.expanduser().resolve()
        scope = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
        self.service_name = f"llm-relay-desk:{scope}"
        self.keyring = (
            keyring_backend
            if keyring_backend is not None
            else KeyringSecretBackend.try_create(self.service_name)
            if use_keyring
            else None
        )
        self.encrypted = encrypted_backend or EncryptedFileSecretBackend(
            resolved / "secrets.enc"
        )

    @staticmethod
    def _env_name(name: str) -> str | None:
        return SECRET_ENV_VARS.get(name)

    def get(self, name: str) -> str | None:
        env_name = self._env_name(name)
        if env_name and env_name in os.environ:
            return os.environ.get(env_name, "")
        if self.keyring is not None:
            value = self.keyring.get(name)
            if value is not None:
                return value
        return self.encrypted.get(name)

    def set(self, name: str, value: str) -> None:
        value = str(value)
        env_name = self._env_name(name)
        if env_name and env_name in os.environ:
            if os.environ.get(env_name, "") == value:
                return
            raise SecretReadOnlyError(
                f"{name} 当前由环境变量 {env_name} 提供，不能在 WebUI 中覆盖"
            )
        if self.keyring is not None and self.keyring.set(name, value):
            try:
                self.encrypted.delete(name)
            except SecretStoreError:
                pass
            return
        self.encrypted.set(name, value)

    def delete(self, name: str) -> None:
        env_name = self._env_name(name)
        if env_name and env_name in os.environ:
            raise SecretReadOnlyError(
                f"{name} 当前由环境变量 {env_name} 提供，请在进程环境中删除"
            )
        if self.keyring is not None:
            self.keyring.delete(name)
        self.encrypted.delete(name)

    def source(self, name: str) -> str:
        env_name = self._env_name(name)
        if env_name and env_name in os.environ:
            return "environment"
        if self.keyring is not None and self.keyring.get(name) is not None:
            return "os_keyring"
        if self.encrypted.get(name) is not None:
            return "encrypted_file"
        return "missing"

    def status(self, name: str) -> dict[str, Any]:
        source = self.source(name)
        return {
            "configured": source != "missing",
            "source": source,
            "environment_variable": self._env_name(name),
            "webui_writable": source != "environment",
        }

    @staticmethod
    def generate_local_api_key() -> str:
        return "sk-local-" + secrets.token_urlsafe(32)
