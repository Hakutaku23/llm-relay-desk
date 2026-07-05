from __future__ import annotations

from pathlib import Path

from llm_relay_desk.prompts import (
    PROFILE_MARKER,
    PromptService,
    TaskType,
    bind_relay_request_context,
    current_injection_decision,
    current_relay_request_context,
)
from llm_relay_desk.storage import JsonStore


def _service(tmp_path: Path) -> PromptService:
    return PromptService(
        JsonStore(
            tmp_path / "prompts.json",
            {
                "active": "玩家友好",
                "profiles": {"玩家友好": "积极回应玩家，但不得伪造技术事实。"},
            },
        )
    )


def _messages() -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Role-play a character. Stay in character. "
                "The conversation partner is main_hero. "
                'JSON Output Format: {"response":"...","actions":[]}'
            ),
        },
        {"role": "user", "content": "请跟随我前往城镇。"},
    ]


def test_backward_proxy_entry_uses_request_local_body_metadata(tmp_path: Path) -> None:
    service = _service(tmp_path)
    payload = {
        "relay_task_type": "player_npc_action_dialogue",
        "messages": _messages(),
    }
    with bind_relay_request_context(
        payload=payload,
        headers={},
        endpoint="/v1/chat/completions",
    ):
        result = service.inject_messages(
            payload["messages"],
            {"prompt_enabled": True},
        )
        decision = current_injection_decision()
        assert decision is not None
        assert decision.task_type is TaskType.PLAYER_NPC_ACTION_DIALOGUE
        assert decision.injection_enabled is True
        assert result[0]["content"].startswith(PROFILE_MARKER)
        assert "relay_task_type" not in payload

    assert current_relay_request_context() is None


def test_backward_proxy_entry_uses_request_header_metadata(tmp_path: Path) -> None:
    service = _service(tmp_path)
    payload = {"messages": _messages()}
    with bind_relay_request_context(
        payload=payload,
        headers={"X-Relay-Task-Type": "diplomacy_statement"},
        endpoint="/api/chat",
    ):
        result = service.inject_messages(payload["messages"], {"prompt_enabled": True})
        decision = current_injection_decision()
        assert decision is not None
        assert decision.task_type is TaskType.DIPLOMACY_STATEMENT
        assert decision.injection_enabled is False
        assert result == payload["messages"]


def test_string_false_switch_is_not_treated_as_enabled(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.prepare_messages(
        _messages(),
        {
            "prompt_enabled": "true",
            "player_friendly_injection_enabled": "false",
        },
        payload={"relay_task_type": "player_npc_dialogue"},
        endpoint="/v1/chat/completions",
    )
    assert result.decision.injection_enabled is False
    assert result.decision.reason == "global_switch_disabled"
