from llm_relay_desk.proxy.protocol import (
    configured_upstream_protocol,
    resolve_upstream_protocol,
)


def test_explicit_vllm_uses_openai_transport() -> None:
    config = {
        "upstream_protocol": "vllm",
        "upstream_base_url": "http://127.0.0.1:8000/v1",
    }
    assert configured_upstream_protocol(config) == "vllm"
    assert resolve_upstream_protocol(config) == "openai"


def test_auto_local_v1_is_openai_compatible() -> None:
    assert resolve_upstream_protocol(
        {
            "upstream_protocol": "auto",
            "upstream_base_url": "http://127.0.0.1:8000/v1",
        }
    ) == "openai"


def test_auto_local_root_remains_ollama() -> None:
    assert resolve_upstream_protocol(
        {
            "upstream_protocol": "auto",
            "upstream_base_url": "http://127.0.0.1:11434",
        }
    ) == "ollama"
