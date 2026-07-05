from __future__ import annotations

from pathlib import Path

from llm_relay_desk.prompts import PROFILE_MARKER, PromptService, TaskType, classify_task
from llm_relay_desk.storage import JsonStore


def _service(tmp_path: Path) -> PromptService:
    store = JsonStore(
        tmp_path / "prompts.json",
        {"active": "玩家友好", "profiles": {"玩家友好": "积极回应玩家，但不得伪造技术事实。"}},
    )
    return PromptService(store)


def _dialogue_messages(extra: str = "") -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Role-play a character. Stay in character. "
                "The conversation partner is main_hero. "
                'JSON Output Format: {"response":"...","actions":[]} '
                + extra
            ),
        },
        {"role": "user", "content": "请跟随我前往城镇。"},
    ]


def test_explicit_allowed_type_injects(tmp_path: Path) -> None:
    service = _service(tmp_path)
    payload = {"relay_task_type": "player_npc_action_dialogue"}
    result = service.prepare_messages(
        _dialogue_messages(),
        {"prompt_enabled": True, "player_friendly_injection_enabled": True},
        payload=payload,
        endpoint="/v1/chat/completions",
    )
    assert result.decision.task_type is TaskType.PLAYER_NPC_ACTION_DIALOGUE
    assert result.decision.injection_enabled is True
    assert result.messages[0]["content"].startswith(PROFILE_MARKER)
    assert "relay_task_type" not in payload


def test_explicit_forbidden_type_never_injects(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.prepare_messages(
        _dialogue_messages(),
        {"prompt_enabled": True, "player_friendly_injection_enabled": True},
        payload={"relay_task_type": "diplomacy_statement"},
        endpoint="/v1/chat/completions",
    )
    assert result.decision.task_type is TaskType.DIPLOMACY_STATEMENT
    assert result.decision.injection_enabled is False


def test_negative_marker_beats_dialogue_markers(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.prepare_messages(
        _dialogue_messages("# DIPLOMATIC STATEMENT GENERATION"),
        {"prompt_enabled": True, "player_friendly_injection_enabled": True},
        endpoint="/api/chat",
    )
    assert result.decision.task_type is TaskType.DIPLOMACY_STATEMENT
    assert result.decision.injection_enabled is False


def test_unknown_defaults_to_passthrough(tmp_path: Path) -> None:
    service = _service(tmp_path)
    messages = [{"role": "user", "content": "summarize this text"}]
    result = service.prepare_messages(
        messages,
        {"prompt_enabled": True, "player_friendly_injection_enabled": True},
        endpoint="/v1/chat/completions",
    )
    assert result.decision.task_type is TaskType.UNKNOWN
    assert result.messages == messages


def test_invalid_explicit_value_is_safe_unknown(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.prepare_messages(
        _dialogue_messages(),
        {"prompt_enabled": True, "player_friendly_injection_enabled": True},
        payload={"relay_task_type": "everything_is_dialogue"},
        endpoint="/v1/chat/completions",
    )
    assert result.decision.task_type is TaskType.UNKNOWN
    assert result.decision.injection_enabled is False
    assert result.decision.explicit_value_invalid == "everything_is_dialogue"


def test_deduplication_marker_prevents_second_injection(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.prepare_messages(
        _dialogue_messages(),
        {"prompt_enabled": True, "player_friendly_injection_enabled": True},
        payload={"relay_task_type": "player_npc_dialogue"},
        endpoint="/api/chat",
    )
    second = service.prepare_messages(
        first.messages,
        {"prompt_enabled": True, "player_friendly_injection_enabled": True},
        payload={"relay_task_type": "player_npc_dialogue"},
        endpoint="/api/chat",
    )
    assert second.decision.injection_enabled is False
    assert second.decision.injection_deduplicated is True
    assert sum(PROFILE_MARKER in str(item.get("content", "")) for item in second.messages) == 1


def test_npc_to_npc_marker_blocks_injection(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.prepare_messages(
        _dialogue_messages("NPC TO NPC; the player is only observing."),
        {"prompt_enabled": True, "player_friendly_injection_enabled": True},
        endpoint="/api/chat",
    )
    assert result.decision.task_type is TaskType.NPC_TO_NPC_DIALOGUE
    assert not result.decision.injection_enabled


def test_generate_requires_high_confidence_markers(tmp_path: Path) -> None:
    service = _service(tmp_path)
    payload = {"prompt": "main_hero asks a question"}
    decision = service.prepare_generate_system(
        payload,
        {"prompt_enabled": True, "player_friendly_injection_enabled": True},
    )
    assert decision.task_type is TaskType.UNKNOWN
    assert "system" not in payload
