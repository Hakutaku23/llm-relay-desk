from pathlib import Path


def test_ui_script_is_injected_after_existing_app_script() -> None:
    source = Path("llm_relay_desk/application.py").read_text(encoding="utf-8")
    assert '/ui-legacy/game-mode-controls.js?v=5.2.0' in source
    assert 'marker = "</body>"' in source


def test_ui_script_injection_is_idempotent() -> None:
    from llm_relay_desk.application import inject_ui_scripts

    source = "<html><body></body></html>"
    assert inject_ui_scripts(inject_ui_scripts(source)).count("game-mode-controls.js") == 1


def test_vllm_option_is_injected() -> None:
    script = Path("static/game-mode-controls.js").read_text(encoding="utf-8")
    assert 'option.value = PROTOCOL_VLLM' in script
    assert 'vLLM（OpenAI 兼容）' in script
    assert '127.0.0.1:8000/v1' in script
