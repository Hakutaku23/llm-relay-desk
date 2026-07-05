from __future__ import annotations

from pathlib import Path

from llm_relay_desk.prompts import (
    GLOBAL_PROFILE_MARKER,
    INJECTION_MODE_BANNERLORD,
    INJECTION_MODE_NORMAL,
    PROFILE_MARKER,
    PromptService,
    TaskType,
)
from llm_relay_desk.storage import JsonStore


def _service(tmp_path: Path) -> PromptService:
    store = JsonStore(
        tmp_path / "prompts.json",
        {
            "active": "测试提示词",
            "profiles": {"测试提示词": "只输出：prompt_test_001"},
        },
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


def test_normal_mode_is_default_and_injects_unknown_task(tmp_path: Path) -> None:
    service = _service(tmp_path)
    messages = [{"role": "user", "content": "提示词测试码是什么？"}]
    result = service.prepare_messages(
        messages,
        {"prompt_enabled": True},
        endpoint="/v1/chat/completions",
    )
    assert result.decision.injection_mode == INJECTION_MODE_NORMAL
    assert result.decision.task_type is TaskType.UNKNOWN
    assert result.decision.injection_enabled is True
    assert result.messages[0]["content"].startswith(GLOBAL_PROFILE_MARKER)
    assert result.decision.reason == "normal_mode_global_injection"


def test_normal_mode_injects_system_event(tmp_path: Path) -> None:
    service = _service(tmp_path)
    payload = {"relay_task_type": "dynamic_event_world_state"}
    result = service.prepare_messages(
        [{"role": "user", "content": "分析世界状态"}],
        {
            "prompt_enabled": True,
            "prompt_injection_mode": "normal",
        },
        payload=payload,
        endpoint="/v1/chat/completions",
    )
    assert result.decision.task_type is TaskType.DYNAMIC_EVENT_WORLD_STATE
    assert result.decision.injection_enabled is True
    assert "relay_task_type" not in payload


def test_bannerlord_npc_dialogue_injects(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.prepare_messages(
        _dialogue_messages(),
        {
            "prompt_enabled": True,
            "prompt_injection_mode": "bannerlord",
            "player_friendly_injection_enabled": True,
        },
        payload={"relay_task_type": "player_npc_dialogue"},
        endpoint="/v1/chat/completions",
    )
    assert result.decision.injection_mode == INJECTION_MODE_BANNERLORD
    assert result.decision.injection_enabled is True
    assert result.messages[0]["content"].startswith(PROFILE_MARKER)


def test_bannerlord_system_event_does_not_inject(tmp_path: Path) -> None:
    service = _service(tmp_path)
    messages = [{"role": "user", "content": "分析世界状态"}]
    result = service.prepare_messages(
        messages,
        {
            "prompt_enabled": True,
            "prompt_injection_mode": "bannerlord",
            "player_friendly_injection_enabled": True,
        },
        payload={"relay_task_type": "dynamic_event_world_state"},
        endpoint="/v1/chat/completions",
    )
    assert result.decision.task_type is TaskType.DYNAMIC_EVENT_WORLD_STATE
    assert result.decision.injection_enabled is False
    assert result.messages == messages
    assert result.decision.reason == "task_type_not_allowed"


def test_bannerlord_negative_marker_beats_dialogue_markers(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.prepare_messages(
        _dialogue_messages("# DIPLOMATIC STATEMENT GENERATION"),
        {
            "prompt_enabled": True,
            "prompt_injection_mode": "bannerlord",
        },
        endpoint="/api/chat",
    )
    assert result.decision.task_type is TaskType.DIPLOMACY_STATEMENT
    assert result.decision.injection_enabled is False


def test_prompt_switch_disables_both_modes(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.prepare_messages(
        [{"role": "user", "content": "hello"}],
        {
            "prompt_enabled": False,
            "prompt_injection_mode": "normal",
        },
        endpoint="/v1/chat/completions",
    )
    assert result.decision.injection_enabled is False
    assert result.decision.reason == "global_switch_disabled"


def test_global_marker_prevents_duplicate_injection(tmp_path: Path) -> None:
    service = _service(tmp_path)
    config = {"prompt_enabled": True, "prompt_injection_mode": "normal"}
    first = service.prepare_messages(
        [{"role": "user", "content": "hello"}],
        config,
        endpoint="/api/chat",
    )
    second = service.prepare_messages(
        first.messages,
        config,
        endpoint="/api/chat",
    )
    assert second.decision.injection_enabled is False
    assert second.decision.injection_deduplicated is True
    assert sum(
        GLOBAL_PROFILE_MARKER in str(item.get("content", ""))
        for item in second.messages
    ) == 1


def test_existing_bannerlord_marker_is_also_deduplicated_in_normal_mode(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    messages = [
        {"role": "system", "content": f"{PROFILE_MARKER}\nold prompt"},
        {"role": "user", "content": "hello"},
    ]
    result = service.prepare_messages(
        messages,
        {"prompt_enabled": True, "prompt_injection_mode": "normal"},
        endpoint="/v1/chat/completions",
    )
    assert result.decision.injection_deduplicated is True
    assert result.messages == messages


def test_invalid_mode_falls_back_to_normal(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.prepare_messages(
        [{"role": "user", "content": "hello"}],
        {"prompt_enabled": True, "prompt_injection_mode": "invalid"},
        endpoint="/v1/chat/completions",
    )
    assert result.decision.injection_mode == INJECTION_MODE_NORMAL
    assert result.decision.injection_enabled is True


def test_generate_obeys_selected_mode(tmp_path: Path) -> None:
    service = _service(tmp_path)

    normal_payload = {"prompt": "普通生成任务"}
    normal_decision = service.prepare_generate_system(
        normal_payload,
        {"prompt_enabled": True, "prompt_injection_mode": "normal"},
    )
    assert normal_decision.injection_enabled is True
    assert normal_payload["system"].startswith(GLOBAL_PROFILE_MARKER)

    game_payload = {
        "prompt": "分析世界状态",
        "relay_task_type": "dynamic_event_world_state",
    }
    game_decision = service.prepare_generate_system(
        game_payload,
        {"prompt_enabled": True, "prompt_injection_mode": "bannerlord"},
    )
    assert game_decision.injection_enabled is False
    assert "system" not in game_payload
    assert "relay_task_type" not in game_payload
