from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from llm_relay_desk.storage import JsonStore


class PromptService:
    def __init__(self, store: JsonStore) -> None:
        self.store = store

    @staticmethod
    def sanitize_name(name: str) -> str:
        clean = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name.strip())
        clean = re.sub(r"\s+", " ", clean)
        if not clean:
            raise HTTPException(status_code=400, detail="提示词名称不能为空")
        if len(clean) > 80:
            raise HTTPException(status_code=400, detail="提示词名称不能超过 80 个字符")
        return clean

    def get_active(self) -> tuple[str | None, str]:
        data = self.store.read()
        active = data.get("active")
        profiles = data.get("profiles", {})
        if not isinstance(profiles, dict):
            return None, ""
        content = profiles.get(active, "") if active else ""
        return active, str(content or "")

    def list_profiles(self) -> dict[str, Any]:
        data = self.store.read()
        profiles = data.get("profiles", {})
        if not isinstance(profiles, dict):
            profiles = {}
        return {
            "active": data.get("active"),
            "profiles": profiles,
            "names": sorted(profiles.keys()),
        }

    def save(self, profile_name: str, content: str) -> dict[str, Any]:
        name = self.sanitize_name(profile_name)
        data = self.store.read()
        profiles = data.setdefault("profiles", {})
        if not isinstance(profiles, dict):
            profiles = {}
            data["profiles"] = profiles
        profiles[name] = content
        if not data.get("active"):
            data["active"] = name
        self.store.write(data)
        return {"ok": True, "name": name, "active": data.get("active")}

    def activate(self, profile_name: str) -> dict[str, Any]:
        name = self.sanitize_name(profile_name)
        data = self.store.read()
        profiles = data.get("profiles", {})
        if name not in profiles:
            raise HTTPException(status_code=404, detail="提示词不存在")
        data["active"] = name
        self.store.write(data)
        return {"ok": True, "active": name}

    def delete(self, profile_name: str) -> dict[str, Any]:
        name = self.sanitize_name(profile_name)
        data = self.store.read()
        profiles = data.get("profiles", {})
        if name not in profiles:
            raise HTTPException(status_code=404, detail="提示词不存在")
        del profiles[name]
        if data.get("active") == name:
            data["active"] = next(iter(sorted(profiles.keys())), None)
        self.store.write(data)
        return {"ok": True, "active": data.get("active")}

    def inject_messages(
        self,
        messages: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not config.get("prompt_enabled", True):
            return messages
        _, prompt = self.get_active()
        if not prompt.strip():
            return messages
        return [{"role": "system", "content": prompt}, *messages]

    def inject_generate_system(
        self,
        payload: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        if not config.get("prompt_enabled", True):
            return
        _, prompt = self.get_active()
        if not prompt.strip():
            return
        existing_system = str(payload.get("system", "")).strip()
        payload["system"] = (
            f"{prompt}\n\n{existing_system}" if existing_system else prompt
        )
