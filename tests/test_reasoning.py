from __future__ import annotations

from llm_relay_desk.proxy.reasoning import (
    apply_ollama_reasoning_default,
    apply_openai_reasoning_default,
    caller_has_reasoning_preference,
)


def test_reasoning_preference_detects_explicit_disable() -> None:
    assert caller_has_reasoning_preference({"think": False}) is True
    assert caller_has_reasoning_preference({"reasoning_effort": "none"}) is True
    assert caller_has_reasoning_preference(
        {"extra_body": {"thinking": {"type": "disabled"}}}
    ) is True
    assert caller_has_reasoning_preference({"stream": True}) is False


def test_openai_default_reasoning_is_injected_for_generic_upstream() -> None:
    payload = {"model": "m", "messages": []}
    changed = apply_openai_reasoning_default(
        payload,
        {
            "force_reasoning_enabled": True,
            "default_reasoning_effort": "high",
            "upstream_base_url": "http://127.0.0.1:11435/v1",
        },
    )
    assert changed is True
    assert payload["reasoning_effort"] == "high"
    assert "thinking" not in payload


def test_openai_default_reasoning_uses_deepseek_thinking() -> None:
    payload = {"model": "deepseek", "messages": []}
    changed = apply_openai_reasoning_default(
        payload,
        {
            "force_reasoning_enabled": True,
            "default_reasoning_effort": "medium",
            "upstream_base_url": "https://api.deepseek.com",
        },
    )
    assert changed is True
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "medium"


def test_openai_default_does_not_override_caller_choice() -> None:
    payload = {
        "model": "m",
        "messages": [],
        "reasoning_effort": "none",
    }
    changed = apply_openai_reasoning_default(
        payload,
        {
            "force_reasoning_enabled": True,
            "default_reasoning_effort": "high",
            "upstream_base_url": "https://api.deepseek.com",
        },
    )
    assert changed is False
    assert payload == {
        "model": "m",
        "messages": [],
        "reasoning_effort": "none",
    }


def test_ollama_default_reasoning_is_injected_and_respects_false() -> None:
    config = {
        "force_reasoning_enabled": True,
        "default_reasoning_effort": "low",
    }
    payload = {"model": "m", "messages": []}
    assert apply_ollama_reasoning_default(payload, config) is True
    assert payload["think"] == "low"

    disabled = {"model": "m", "messages": [], "think": False}
    assert apply_ollama_reasoning_default(disabled, config) is False
    assert disabled["think"] is False


def test_ollama_normalizes_openai_style_explicit_controls() -> None:
    config = {"force_reasoning_enabled": True, "default_reasoning_effort": "high"}

    disabled = {"reasoning_effort": "none"}
    assert apply_ollama_reasoning_default(disabled, config) is True
    assert disabled == {"think": False}

    enabled = {"thinking": {"type": "enabled"}}
    assert apply_ollama_reasoning_default(enabled, config) is True
    assert enabled == {"think": True}
