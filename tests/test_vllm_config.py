from pathlib import Path

from llm_relay_desk.config import normalize_vllm_base_url, validate_config
from llm_relay_desk.settings import DEFAULT_CONFIG
from llm_relay_desk.storage import JsonStore


def test_vllm_base_url_adds_v1() -> None:
    assert normalize_vllm_base_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000/v1"
    assert normalize_vllm_base_url("http://127.0.0.1:8000/v1") == "http://127.0.0.1:8000/v1"


def test_vllm_protocol_is_saved_and_survives_unrelated_updates(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "config.json", DEFAULT_CONFIG)
    updated = validate_config(
        store,
        {
            "upstream_protocol": "vllm",
            "upstream_base_url": "http://127.0.0.1:8000",
        },
    )
    assert updated["upstream_protocol"] == "vllm"
    assert updated["upstream_base_url"] == "http://127.0.0.1:8000/v1"
    store.write(updated)

    updated_again = validate_config(store, {"prompt_enabled": False})
    assert updated_again["upstream_protocol"] == "vllm"
    assert updated_again["upstream_base_url"] == "http://127.0.0.1:8000/v1"
