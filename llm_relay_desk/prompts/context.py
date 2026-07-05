from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from .task_isolation import InjectionDecision


@dataclass(slots=True)
class RelayRequestContext:
    payload: dict[str, Any] | None
    headers: Mapping[str, Any] | None
    endpoint: str
    decision: InjectionDecision | None = None


_CURRENT_CONTEXT: ContextVar[RelayRequestContext | None] = ContextVar(
    "llm_relay_request_context",
    default=None,
)


@contextmanager
def bind_relay_request_context(
    *,
    payload: dict[str, Any] | None,
    headers: Mapping[str, Any] | None,
    endpoint: str,
) -> Iterator[RelayRequestContext]:
    """Bind task metadata to the current async request only.

    The context is local to the current coroutine and is reset as soon as the
    proxy response object has been constructed. No classification state leaks
    into the next request.
    """

    context = RelayRequestContext(
        payload=payload,
        headers=headers,
        endpoint=endpoint,
    )
    token = _CURRENT_CONTEXT.set(context)
    try:
        yield context
    finally:
        _CURRENT_CONTEXT.reset(token)


def current_relay_request_context() -> RelayRequestContext | None:
    return _CURRENT_CONTEXT.get()


def set_current_injection_decision(decision: InjectionDecision) -> None:
    context = _CURRENT_CONTEXT.get()
    if context is not None:
        context.decision = decision


def current_injection_decision() -> InjectionDecision | None:
    context = _CURRENT_CONTEXT.get()
    return context.decision if context is not None else None
