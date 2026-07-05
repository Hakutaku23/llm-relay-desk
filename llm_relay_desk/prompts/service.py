from __future__ import annotations

import re
from typing import Any, Mapping

from fastapi import HTTPException

from llm_relay_desk.storage import JsonStore

from .context import (
    current_relay_request_context,
    set_current_injection_decision,
)
from .task_isolation import (
    ALLOWED_TASK_TYPES,
    GLOBAL_PROFILE_ID,
    GLOBAL_PROFILE_MARKER,
    GLOBAL_PROFILE_VERSION,
    INJECTION_MODE_BANNERLORD,
    INJECTION_MODE_NORMAL,
    KNOWN_PROFILE_MARKERS,
    PROFILE_ID,
    PROFILE_MARKER,
    PROFILE_VERSION,
    InjectionDecision,
    MessageInjectionResult,
    TaskType,
    classify_task,
    normalize_injection_mode,
    strip_relay_metadata,
    system_hash,
)


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
            "task_isolation": {
                "profile_id": PROFILE_ID,
                "profile_version": PROFILE_VERSION,
                "allowed_task_types": sorted(
                    item.value for item in ALLOWED_TASK_TYPES
                ),
                "deduplication_marker": PROFILE_MARKER,
                "unknown_default": "passthrough",
                "active_only_in_mode": INJECTION_MODE_BANNERLORD,
            },
            "injection_modes": {
                INJECTION_MODE_NORMAL: {
                    "profile_id": GLOBAL_PROFILE_ID,
                    "profile_version": GLOBAL_PROFILE_VERSION,
                    "deduplication_marker": GLOBAL_PROFILE_MARKER,
                    "behavior": "inject_all_chat_and_generate_requests",
                },
                INJECTION_MODE_BANNERLORD: {
                    "profile_id": PROFILE_ID,
                    "profile_version": PROFILE_VERSION,
                    "allowed_task_types": sorted(
                        item.value for item in ALLOWED_TASK_TYPES
                    ),
                    "deduplication_marker": PROFILE_MARKER,
                    "unknown_default": "passthrough",
                },
            },
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

    @staticmethod
    def _config_flag(
        config: Mapping[str, Any],
        key: str,
        default: bool = True,
    ) -> bool:
        value = config.get(key, default)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"0", "false", "no", "off", "disabled"}:
                return False
            if normalized in {"1", "true", "yes", "on", "enabled"}:
                return True
        return bool(value)

    @classmethod
    def _task_switch_enabled(
        cls,
        task_type: TaskType,
        config: Mapping[str, Any],
    ) -> bool:
        switches = {
            TaskType.PLAYER_NPC_DIALOGUE: "enable_player_initiated_dialogue",
            TaskType.PLAYER_NPC_ACTION_DIALOGUE: "enable_action_dialogue",
            TaskType.NPC_INITIATED_PLAYER_DIALOGUE: "enable_npc_initiated_dialogue",
        }
        key = switches.get(task_type)
        return cls._config_flag(config, key, True) if key else False

    @staticmethod
    def _existing_profile(
        messages: list[dict[str, Any]],
    ) -> tuple[str, int] | None:
        marker_profiles = {
            PROFILE_MARKER: (PROFILE_ID, PROFILE_VERSION),
            GLOBAL_PROFILE_MARKER: (GLOBAL_PROFILE_ID, GLOBAL_PROFILE_VERSION),
        }
        for item in messages:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", ""))
            for marker in KNOWN_PROFILE_MARKERS:
                if marker in content:
                    return marker_profiles[marker]
        return None

    def prepare_messages(
        self,
        messages: list[dict[str, Any]],
        config: dict[str, Any],
        *,
        payload: dict[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        endpoint: str = "",
    ) -> MessageInjectionResult:
        original = [dict(item) for item in messages]
        original_hash = system_hash(original)
        classification = classify_task(
            messages=original,
            payload=payload,
            headers=headers,
            endpoint=endpoint,
        )
        if payload is not None:
            strip_relay_metadata(payload)

        mode = normalize_injection_mode(config.get("prompt_injection_mode"))
        active_name, prompt = self.get_active()
        prompt_enabled = self._config_flag(config, "prompt_enabled", True)
        has_prompt = bool(prompt.strip())
        existing_profile = self._existing_profile(original)
        deduplicated = existing_profile is not None

        if mode == INJECTION_MODE_NORMAL:
            global_enabled = prompt_enabled
            allowed = True
            task_switch = True
            marker = GLOBAL_PROFILE_MARKER
            selected_profile = GLOBAL_PROFILE_ID
            selected_version = GLOBAL_PROFILE_VERSION
        else:
            global_enabled = prompt_enabled and self._config_flag(
                config,
                "player_friendly_injection_enabled",
                True,
            )
            allowed = classification.task_type in ALLOWED_TASK_TYPES
            task_switch = self._task_switch_enabled(
                classification.task_type,
                config,
            )
            marker = PROFILE_MARKER
            selected_profile = PROFILE_ID
            selected_version = PROFILE_VERSION

        inject = (
            global_enabled
            and allowed
            and task_switch
            and has_prompt
            and not deduplicated
        )

        if inject:
            final_messages = [
                {
                    "role": "system",
                    "content": f"{marker}\n{prompt.strip()}",
                },
                *original,
            ]
            reason = (
                "normal_mode_global_injection"
                if mode == INJECTION_MODE_NORMAL
                else "bannerlord_allowed_task_type"
            )
        else:
            final_messages = original
            if deduplicated:
                reason = "deduplicated"
            elif not global_enabled:
                reason = "global_switch_disabled"
            elif not allowed:
                reason = "task_type_not_allowed"
            elif not task_switch:
                reason = "task_switch_disabled"
            elif not has_prompt:
                reason = "empty_active_prompt"
            else:
                reason = "passthrough"

        decision = InjectionDecision(
            task_type=classification.task_type,
            classification_source=classification.source,
            classification_confidence=classification.confidence,
            injection_mode=mode,
            matched_positive_markers=classification.matched_positive_markers,
            matched_negative_markers=classification.matched_negative_markers,
            selected_profile=(
                selected_profile
                if inject
                else existing_profile[0]
                if existing_profile is not None
                else "passthrough"
            ),
            profile_version=(
                selected_version
                if inject
                else existing_profile[1]
                if existing_profile is not None
                else None
            ),
            active_prompt_name=active_name,
            injection_enabled=inject,
            injection_deduplicated=deduplicated,
            original_system_hash=original_hash,
            final_system_hash=system_hash(final_messages),
            reason=reason,
            explicit_value_invalid=classification.explicit_value_invalid,
        )
        set_current_injection_decision(decision)
        return MessageInjectionResult(final_messages, decision)

    def prepare_generate_system(
        self,
        payload: dict[str, Any],
        config: dict[str, Any],
        *,
        headers: Mapping[str, Any] | None = None,
        endpoint: str = "/api/generate",
    ) -> InjectionDecision:
        existing_system = str(payload.get("system", "")).strip()
        synthetic_messages: list[dict[str, Any]] = []
        if existing_system:
            synthetic_messages.append(
                {"role": "system", "content": existing_system}
            )
        synthetic_messages.append(
            {"role": "user", "content": str(payload.get("prompt", ""))}
        )
        result = self.prepare_messages(
            synthetic_messages,
            config,
            payload=payload,
            headers=headers,
            endpoint=endpoint,
        )
        if result.decision.injection_enabled:
            injected_system = str(result.messages[0].get("content", ""))
            payload["system"] = (
                f"{injected_system}\n\n{existing_system}"
                if existing_system
                else injected_system
            )
        return result.decision

    # Backward-compatible entry points used by the existing proxy modules.
    # Request metadata is supplied through a request-local ContextVar bound by
    # the API routes, avoiding invasive changes to the proxy pipelines.
    def inject_messages(
        self,
        messages: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        context = current_relay_request_context()
        return self.prepare_messages(
            messages,
            config,
            payload=context.payload if context is not None else None,
            headers=context.headers if context is not None else None,
            endpoint=context.endpoint if context is not None else "",
        ).messages

    def inject_generate_system(
        self,
        payload: dict[str, Any],
        config: dict[str, Any],
    ) -> InjectionDecision:
        context = current_relay_request_context()
        return self.prepare_generate_system(
            payload,
            config,
            headers=context.headers if context is not None else None,
            endpoint=(
                context.endpoint
                if context is not None
                else "/api/generate"
            ),
        )
