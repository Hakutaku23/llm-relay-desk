from llm_relay_desk.application import inject_mode_control_script


def test_ui_script_is_injected_after_existing_app_script() -> None:
    html = '<html><body><script src="/ui/app.js"></script></body></html>'
    result = inject_mode_control_script(html)
    assert result.count("game-mode-controls.js") == 1
    assert result.index("/ui/app.js") < result.index("game-mode-controls.js")


def test_ui_script_injection_is_idempotent() -> None:
    html = '<html><body><script src="/ui/game-mode-controls.js"></script></body></html>'
    assert inject_mode_control_script(html) == html
