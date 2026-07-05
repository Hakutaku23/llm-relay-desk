from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


class TaskType(str, Enum):
    PLAYER_NPC_DIALOGUE = "player_npc_dialogue"
    PLAYER_NPC_ACTION_DIALOGUE = "player_npc_action_dialogue"
    NPC_INITIATED_PLAYER_DIALOGUE = "npc_initiated_player_dialogue"
    NPC_TO_NPC_DIALOGUE = "npc_to_npc_dialogue"
    DIPLOMACY_STATEMENT = "diplomacy_statement"
    DIPLOMACY_DECISION = "diplomacy_decision"
    DYNAMIC_EVENT_DIALOGUE_ANALYSIS = "dynamic_event_dialogue_analysis"
    DYNAMIC_EVENT_WORLD_STATE = "dynamic_event_world_state"
    CHARACTER_GENERATION = "character_generation"
    MEMORY_PROCESSING = "memory_processing"
    IMAGE_PROMPT = "image_prompt"
    ROUTING_OR_CLASSIFICATION = "routing_or_classification"
    SYSTEM_UTILITY = "system_utility"
    UNKNOWN = "unknown"


ALLOWED_TASK_TYPES = frozenset(
    {
        TaskType.PLAYER_NPC_DIALOGUE,
        TaskType.PLAYER_NPC_ACTION_DIALOGUE,
        TaskType.NPC_INITIATED_PLAYER_DIALOGUE,
    }
)

PROFILE_ID = "player_friendly_npc"
PROFILE_VERSION = 2
PROFILE_MARKER = f"[LLM_RELAY_PROFILE:{PROFILE_ID}:v{PROFILE_VERSION}]"

_EXPLICIT_BODY_KEYS = ("relay_task_type", "_relay_task_type")
_EXPLICIT_HEADER_KEYS = ("x-relay-task-type", "relay-task-type")

_NEGATIVE_RULES: tuple[tuple[TaskType, str, re.Pattern[str]], ...] = (
    (TaskType.DIPLOMACY_STATEMENT, "# DIPLOMATIC STATEMENT GENERATION", re.compile(r"#\s*DIPLOMATIC\s+STATEMENT\s+GENERATION", re.I)),
    (TaskType.DIPLOMACY_DECISION, "diplomacy decision", re.compile(r"\b(war|peace|alliance|diplomacy)\s+(decision|evaluation|analysis)\b|王国.{0,10}(战争|和平|联盟).{0,10}(决策|判断)", re.I | re.S)),
    (TaskType.DYNAMIC_EVENT_WORLD_STATE, "WORLD STATE ANALYSIS", re.compile(r"(?:##\s*MODE\s*:\s*)?WORLD\s+STATE\s+ANALYSIS", re.I)),
    (TaskType.DYNAMIC_EVENT_DIALOGUE_ANALYSIS, "DIALOGUE ANALYSIS", re.compile(r"(?:##\s*MODE\s*:\s*)?DIALOGUE\s+ANALYSIS|动态事件.{0,20}对话分析", re.I | re.S)),
    (TaskType.DYNAMIC_EVENT_WORLD_STATE, "DYNAMIC EVENT GENERATION", re.compile(r"#?\s*(?:TASK\s*:\s*)?DYNAMIC\s+(?:WORLD\s+)?EVENT\s+GENERATION", re.I)),
    (TaskType.CHARACTER_GENERATION, "CHARACTER CREATION", re.compile(r"CHARACTER\s+(?:CREATION|GENERATION)|角色.{0,8}(创建|生成|背景生成|人格生成)", re.I | re.S)),
    (TaskType.MEMORY_PROCESSING, "MEMORY PROCESSING", re.compile(r"MEMORY\s+(?:CONSOLIDATION|EVENT|SUMMARY|PROCESSING)|记忆.{0,8}(整理|压缩|摘要|合并)", re.I | re.S)),
    (TaskType.IMAGE_PROMPT, "IMAGE PROMPT", re.compile(r"SCENE\s+IMAGE|IMAGE\s+PROMPT|图像.{0,8}(提示词|描述|生成)", re.I | re.S)),
    (TaskType.ROUTING_OR_CLASSIFICATION, "ROUTING/CLASSIFICATION", re.compile(r"\b(?:PROMPT\s+MODULE|ROUTING|CLASSIFICATION|JSON\s+REPAIR)\b|路由.{0,8}分类|格式修复", re.I | re.S)),
    (TaskType.SYSTEM_UTILITY, "SYSTEM UTILITY", re.compile(r"\b(?:HEALTH\s*CHECK|MODEL\s*CHECK|PING|SYSTEM\s*CHECK)\b|健康检查|模型检查", re.I)),
    (TaskType.NPC_TO_NPC_DIALOGUE, "NPC TO NPC", re.compile(r"NPC\s*(?:TO|[-—>]\s*)\s*NPC|NPC\s+与\s+NPC|玩家(?:仅|只是)?旁观|player\s+is\s+(?:only\s+)?observing", re.I)),
)

_ROLEPLAY_PATTERNS = (
    re.compile(r"role[- ]?play\s+(?:as\s+)?a?\s*character", re.I),
    re.compile(r"\{\{?\s*character\s*\}?\}\s*=\s*YOU", re.I),
    re.compile(r"stay\s+in\s+character", re.I),
    re.compile(r"conversation\s+partner", re.I),
    re.compile(r"new\s+dialogue\s+with", re.I),
    re.compile(r"扮演.{0,16}(角色|NPC)|保持角色设定|以角色身份", re.I | re.S),
)
_PLAYER_PATTERNS = (
    re.compile(r"\bmain_hero\b", re.I),
    re.compile(r"conversation\s+with\s+the\s+player", re.I),
    re.compile(r"directly\s+(?:to|addressing)\s+the\s+player", re.I),
    re.compile(r"(?:对话对象|交谈对象).{0,12}(玩家|main_hero)", re.I | re.S),
    re.compile(r"\bplayer\b|玩家", re.I),
)
_OUTPUT_PATTERNS = (
    re.compile(r'"response"', re.I),
    re.compile(r'"actions?"', re.I),
    re.compile(r"JSON\s+Output\s+Format", re.I),
    re.compile(r"in[- ]character\s+(?:speech|actions?)", re.I),
    re.compile(r"角色内.{0,8}(发言|动作)|对话回复", re.I | re.S),
)
_ACTION_PATTERNS = (
    re.compile(r'"actions?"', re.I),
    re.compile(r"\b(?:trade|buy|sell|follow|patrol|recruit|release|exchange|pay|command|request|task)\b", re.I),
    re.compile(r"交易|购买|出售|跟随|前往|巡逻|招募|释放|交换|支付|命令|请求|任务协商|行动要求"),
)
_NPC_INITIATED_PATTERNS = (
    re.compile(r"NPC\s+(?:initiates|approaches|reports|writes|sends|returns)", re.I),
    re.compile(r"主动.{0,8}(接近|交谈|汇报|来信|写信|报告|提出)|向玩家汇报|玩家收到.{0,8}(信件|消息)", re.I | re.S),
)


def _normalized_task_type(value: Any) -> TaskType | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_")
    aliases = {
        "player_dialogue": TaskType.PLAYER_NPC_DIALOGUE,
        "npc_dialogue": TaskType.PLAYER_NPC_DIALOGUE,
        "action_dialogue": TaskType.PLAYER_NPC_ACTION_DIALOGUE,
        "npc_initiated_dialogue": TaskType.NPC_INITIATED_PLAYER_DIALOGUE,
        "world_state": TaskType.DYNAMIC_EVENT_WORLD_STATE,
        "dialogue_analysis": TaskType.DYNAMIC_EVENT_DIALOGUE_ANALYSIS,
        "diplomacy": TaskType.DIPLOMACY_STATEMENT,
    }
    if text in aliases:
        return aliases[text]
    try:
        return TaskType(text)
    except ValueError:
        return None


def extract_explicit_task_type(
    payload: Mapping[str, Any] | None,
    headers: Mapping[str, Any] | None,
) -> tuple[TaskType | None, str | None, str | None]:
    """Return normalized task type, source and invalid raw value.

    Body metadata wins over headers. Invalid explicit values are not ignored: the
    classifier returns unknown and injection remains disabled.
    """

    if payload:
        for key in _EXPLICIT_BODY_KEYS:
            if key in payload:
                raw = payload.get(key)
                task_type = _normalized_task_type(raw)
                return task_type, f"explicit_body:{key}", None if task_type else str(raw)
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping) and "relay_task_type" in metadata:
            raw = metadata.get("relay_task_type")
            task_type = _normalized_task_type(raw)
            return task_type, "explicit_body:metadata.relay_task_type", None if task_type else str(raw)

    if headers:
        lowered = {str(key).lower(): value for key, value in headers.items()}
        for key in _EXPLICIT_HEADER_KEYS:
            if key in lowered:
                raw = lowered[key]
                task_type = _normalized_task_type(raw)
                return task_type, f"explicit_header:{key}", None if task_type else str(raw)
    return None, None, None


def strip_relay_metadata(payload: dict[str, Any]) -> None:
    for key in _EXPLICIT_BODY_KEYS:
        payload.pop(key, None)
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("relay_task_type", None)
        if not metadata:
            payload.pop("metadata", None)


def _text_from_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                for key in ("text", "content", "input_text"):
                    if isinstance(item.get(key), str):
                        parts.append(str(item[key]))
                        break
        return "\n".join(parts)
    return "" if value is None else str(value)


def classification_text(
    *,
    messages: Sequence[Mapping[str, Any]] | None = None,
    payload: Mapping[str, Any] | None = None,
    limit: int = 200_000,
) -> str:
    parts: list[str] = []
    if messages:
        for message in messages:
            role = str(message.get("role", ""))
            content = _text_from_content(message.get("content"))
            if content:
                parts.append(f"[{role}]\n{content}")
    if payload:
        for key in ("system", "prompt", "template", "context"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                parts.append(f"[{key}]\n{value}")
    return "\n\n".join(parts)[:limit]


def _matching_labels(patterns: Iterable[re.Pattern[str]], text: str) -> list[str]:
    labels: list[str] = []
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            labels.append(match.group(0)[:120])
    return labels


@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    task_type: TaskType
    source: str
    confidence: float
    matched_positive_markers: tuple[str, ...] = ()
    matched_negative_markers: tuple[str, ...] = ()
    explicit_value_invalid: str | None = None


@dataclass(frozen=True, slots=True)
class InjectionDecision:
    task_type: TaskType
    classification_source: str
    classification_confidence: float
    matched_positive_markers: tuple[str, ...] = ()
    matched_negative_markers: tuple[str, ...] = ()
    selected_profile: str = "passthrough"
    profile_version: int | None = None
    active_prompt_name: str | None = None
    injection_enabled: bool = False
    injection_deduplicated: bool = False
    original_system_hash: str = ""
    final_system_hash: str = ""
    reason: str = ""
    explicit_value_invalid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected_task_type": self.task_type.value,
            "classification_source": self.classification_source,
            "classification_confidence": self.classification_confidence,
            "matched_positive_markers": list(self.matched_positive_markers),
            "matched_negative_markers": list(self.matched_negative_markers),
            "selected_profile": self.selected_profile,
            "profile_version": self.profile_version,
            "active_prompt_name": self.active_prompt_name,
            "injection_enabled": self.injection_enabled,
            "injection_deduplicated": self.injection_deduplicated,
            "original_system_hash": self.original_system_hash,
            "final_system_hash": self.final_system_hash,
            "reason": self.reason,
            "explicit_value_invalid": self.explicit_value_invalid,
        }


@dataclass(slots=True)
class MessageInjectionResult:
    messages: list[dict[str, Any]]
    decision: InjectionDecision


def classify_task(
    *,
    messages: Sequence[Mapping[str, Any]] | None,
    payload: Mapping[str, Any] | None,
    headers: Mapping[str, Any] | None,
    endpoint: str,
) -> ClassificationDecision:
    explicit, source, invalid = extract_explicit_task_type(payload, headers)
    if source:
        if explicit is None:
            return ClassificationDecision(
                task_type=TaskType.UNKNOWN,
                source=f"{source}:invalid",
                confidence=1.0,
                explicit_value_invalid=invalid,
            )
        return ClassificationDecision(explicit, source, 1.0)

    text = classification_text(messages=messages, payload=payload)
    for task_type, label, pattern in _NEGATIVE_RULES:
        match = pattern.search(text)
        if match:
            return ClassificationDecision(
                task_type=task_type,
                source=f"negative_marker:{label}",
                confidence=0.99,
                matched_negative_markers=(match.group(0)[:120],),
            )

    roleplay = _matching_labels(_ROLEPLAY_PATTERNS, text)
    player = _matching_labels(_PLAYER_PATTERNS, text)
    output = _matching_labels(_OUTPUT_PATTERNS, text)
    positives = tuple(roleplay + player + output)

    # /api/generate has no structured roles and therefore requires all three
    # marker families. Chat endpoints require role-play + player; output markers
    # strengthen confidence but are not mandatory.
    is_generate = endpoint.rstrip("/").endswith("/generate")
    eligible = bool(roleplay and player and (output or not is_generate))
    if not eligible:
        return ClassificationDecision(
            task_type=TaskType.UNKNOWN,
            source="fallback:unknown",
            confidence=0.2,
            matched_positive_markers=positives,
        )

    action = _matching_labels(_ACTION_PATTERNS, text)
    initiated = _matching_labels(_NPC_INITIATED_PATTERNS, text)
    if initiated:
        task_type = TaskType.NPC_INITIATED_PLAYER_DIALOGUE
        source_name = "positive_markers:npc_initiated_player_dialogue"
    elif action:
        task_type = TaskType.PLAYER_NPC_ACTION_DIALOGUE
        source_name = "positive_markers:player_npc_action_dialogue"
    else:
        task_type = TaskType.PLAYER_NPC_DIALOGUE
        source_name = "positive_markers:player_npc_dialogue"
    return ClassificationDecision(
        task_type=task_type,
        source=source_name,
        confidence=0.9 if output else 0.82,
        matched_positive_markers=tuple(dict.fromkeys((*positives, *action, *initiated))),
    )


def system_hash(messages: Sequence[Mapping[str, Any]]) -> str:
    content = "\n\n".join(
        _text_from_content(item.get("content"))
        for item in messages
        if str(item.get("role", "")).lower() == "system"
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
