from llm_relay_desk.application import inject_ui_scripts


def test_security_script_is_injected_once() -> None:
    source = "<html><body><main>ok</main></body></html>"
    first = inject_ui_scripts(source)
    second = inject_ui_scripts(first)
    assert 'security-controls.js?v=5.3.0' in first
    assert first.count("security-controls.js") == 1
    assert second.count("security-controls.js") == 1
