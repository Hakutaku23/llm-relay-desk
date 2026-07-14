from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request

FIXTURE_DIR = Path(__file__).with_name("fixtures")
MOCK_HEADER_NAME = "X-Mock-Upstream"
MOCK_HEADER_VALUE = "llm-relay-desk"

OPENAI_CHAT_SCENARIOS = (
    "openai-nonstream-usage",
    "openai-stream-final-usage",
    "deepseek-cache-usage",
    "vllm-nonstream-usage",
    "vllm-stream-final-usage",
    "usage-missing",
    "cache-details-missing",
    "reasoning-only",
    "http-401",
    "http-429",
    "http-500",
    "interrupted-stream",
    "malformed-json",
    "malformed-sse",
)
EMBEDDING_SCENARIOS = (
    "embeddings-usage",
    "usage-missing",
    "http-401",
    "http-429",
    "http-500",
    "malformed-json",
)
OLLAMA_SCENARIOS = (
    "ollama-usage",
    "usage-missing",
    "cache-details-missing",
    "reasoning-only",
    "http-401",
    "http-429",
    "http-500",
    "interrupted-stream",
    "malformed-json",
)
GET_SCENARIOS = ("http-401", "http-429", "http-500", "malformed-json")

SCENARIOS_BY_ENDPOINT = {
    "openai-chat": OPENAI_CHAT_SCENARIOS,
    "embeddings": EMBEDDING_SCENARIOS,
    "ollama": OLLAMA_SCENARIOS,
    "models": GET_SCENARIOS,
    "tags": GET_SCENARIOS,
}
ALL_SCENARIOS = tuple(
    dict.fromkeys(OPENAI_CHAT_SCENARIOS + EMBEDDING_SCENARIOS + OLLAMA_SCENARIOS)
)


@dataclass(frozen=True)
class ScenarioResolution:
    name: str | None
    error: dict[str, Any] | None = None


def load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def load_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def resolve_scenario(
    request: Request,
    endpoint: str,
    payload: dict[str, Any] | None = None,
    default: str | None = None,
) -> ScenarioResolution:
    header_name = request.headers.get("X-Mock-Scenario")
    model = payload.get("model") if payload else None
    model_name = model[5:] if isinstance(model, str) and model.startswith("mock/") else None
    selected = header_name or model_name or default
    if selected is None:
        return ScenarioResolution(None)
    supported = SCENARIOS_BY_ENDPOINT[endpoint]
    if selected not in supported:
        return ScenarioResolution(
            selected,
            {
                "error": {
                    "message": f"Unknown mock scenario: {selected}",
                    "type": "invalid_mock_scenario",
                    "unknown_scenario": selected,
                    "supported_scenarios": list(supported),
                }
            },
        )
    return ScenarioResolution(selected)
