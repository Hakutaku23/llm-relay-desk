from pathlib import Path


def test_ui_script_is_injected_after_existing_app_script() -> None:
    source = Path("llm_relay_desk/application.py").read_text(encoding="utf-8")
    assert 'game-mode-controls.js?v=5.2.0' in source
    assert 'marker = "</body>"' in source


def test_ui_script_injection_is_idempotent() -> None:
    source = Path("llm_relay_desk/application.py").read_text(encoding="utf-8")
    assert 'if "game-mode-controls.js" in html:' in source


def test_vllm_option_is_injected() -> None:
    script = Path("static/game-mode-controls.js").read_text(encoding="utf-8")
    assert 'option.value = PROTOCOL_VLLM' in script
    assert 'vLLM（OpenAI 兼容）' in script
    assert '127.0.0.1:8000/v1' in script
