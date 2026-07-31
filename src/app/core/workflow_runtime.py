"""LangGraph-backed live workflow runtime for supported specialist execution."""

from __future__ import annotations

import asyncio
import time
from functools import lru_cache
from typing import TypedDict

import structlog
from anthropic import AsyncAnthropic
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import Settings, get_settings
from src.app.core.trace import TraceRecorder
from src.app.domain.constants import TraceSpanKind, TraceSpanStatus
from src.app.domain.models import ChatResponse, Intent, MessageInput, Specialist
from src.app.domain.services.handlers import (
    handle_communications,
    handle_diary,
    handle_memory,
    handle_notification,
    handle_plan_day,
    handle_project,
    handle_research,
    handle_review,
    handle_save,
    handle_socratic,
    handle_tools,
)

logger = structlog.get_logger()

_SUPPORTED_SPECIALISTS = frozenset(
    {
        Specialist.DIARY.value,
        Specialist.MEMORY.value,
        Specialist.REVIEW.value,
        Specialist.PROJECT.value,
        Specialist.COMMUNICATIONS.value,
        Specialist.NOTIFICATION.value,
        Specialist.PLAN_DAY.value,
        Specialist.RESEARCH.value,
        Specialist.TOOLS.value,
        Specialist.SAVE.value,
        Specialist.SOCRATIC.value,
    }
)


def _flag_enabled(value: object) -> bool:
    """Treat only an explicit boolean True as enabled."""
    return isinstance(value, bool) and value


def _timeout_ms(value: object, *, default: int) -> int:
    """Return a sane timeout for partially mocked settings objects."""
    if isinstance(value, int) and not isinstance(value, bool):
        return max(value, 100)
    return default


def _specialist_names(value: object) -> list[str]:
    """Normalize configured specialist allowlists and ignore invalid doubles."""
    if not isinstance(value, list):
        return []
    return [item.strip().lower() for item in value if isinstance(item, str) and item.strip()]


class LiveWorkflowOutcome(BaseModel):
    """Execution outcome for the live workflow runtime."""

    mode: str = "live"
    specialist: str
    status: str = "skipped"
    executed: bool = False
    fallback_used: bool = False
    reason: str | None = None
    latency_ms: int | None = None
    response_agent: str | None = None
    response_preview: str | None = None
    response: ChatResponse | None = None


class LiveWorkflowState(TypedDict, total=False):
    """Minimal graph state for supported live specialist execution."""

    message: MessageInput
    client: AsyncAnthropic
    session: AsyncSession
    intent: Intent
    trace_recorder: TraceRecorder
    parent_span_id: str | None
    allowed_specialists: list[str]
    specialist: str
    response: ChatResponse
    skip_reason: str
    # Correlation ID propagated end-to-end — mirrors the middleware-bound
    # structlog contextvar so every LLM call, tool span, and enqueued ARQ
    # job from this turn carries the same ID.
    request_id: str


def _handler_for_specialist(specialist: str):
    return {
        Specialist.DIARY.value: handle_diary,
        Specialist.MEMORY.value: handle_memory,
        Specialist.REVIEW.value: handle_review,
        Specialist.PROJECT.value: handle_project,
        Specialist.COMMUNICATIONS.value: handle_communications,
        Specialist.NOTIFICATION.value: handle_notification,
        Specialist.PLAN_DAY.value: handle_plan_day,
        Specialist.RESEARCH.value: handle_research,
        Specialist.TOOLS.value: handle_tools,
        Specialist.SAVE.value: handle_save,
        Specialist.SOCRATIC.value: handle_socratic,
    }[specialist]


async def _dispatch_node(state: LiveWorkflowState) -> LiveWorkflowState:
    """Lift the already-classified specialist into graph state."""
    specialist = str(state["intent"].specialist)
    recorder = state["trace_recorder"]
    with recorder.timed_span(
        name="workflow.live.dispatch",
        span_kind=TraceSpanKind.ROUTING,
        parent_span_id=state.get("parent_span_id"),
        specialist=specialist,
    ) as span:
        span["details"] = {
            "specialist": specialist,
            "allowed_specialists": list(state.get("allowed_specialists", [])),
        }
    return {
        **state,
        "specialist": specialist,
    }


def _route_to_specialist(state: LiveWorkflowState) -> str:
    specialist = str(state.get("specialist") or "").strip()
    allowed = {value.strip() for value in state.get("allowed_specialists", []) if value.strip()}
    if not specialist:
        return "unsupported"
    if allowed and specialist not in allowed:
        return "unsupported"
    if specialist not in _SUPPORTED_SPECIALISTS:
        return "unsupported"
    return specialist


async def _unsupported_node(state: LiveWorkflowState) -> LiveWorkflowState:
    """Return a skip reason when the live runtime should not execute this specialist."""
    recorder = state["trace_recorder"]
    specialist = str(state.get("specialist") or "")
    allowed = set(state.get("allowed_specialists", []))
    if specialist and specialist not in _SUPPORTED_SPECIALISTS:
        reason = f"workflow_runtime_not_supported_for_{specialist}"
    elif specialist and specialist not in allowed:
        reason = f"workflow_runtime_disabled_{specialist}"
    else:
        reason = "workflow_runtime_specialist_missing"

    with recorder.timed_span(
        name="workflow.live.unsupported",
        span_kind=TraceSpanKind.SPECIALIST,
        parent_span_id=state.get("parent_span_id"),
        specialist=specialist or None,
    ) as span:
        span["status"] = TraceSpanStatus.DEGRADED
        span["details"] = {
            "specialist": specialist,
            "skip_reason": reason,
        }

    return {
        **state,
        "skip_reason": reason,
    }


async def _execute_specialist(
    state: LiveWorkflowState,
    *,
    specialist: str,
) -> LiveWorkflowState:
    """Run one supported specialist handler inside the graph."""
    recorder = state["trace_recorder"]
    handler = _handler_for_specialist(specialist)

    with recorder.timed_span(
        name=f"workflow.live.execute.{specialist}",
        span_kind=TraceSpanKind.SPECIALIST,
        parent_span_id=state.get("parent_span_id"),
        specialist=specialist,
    ) as span:
        response = await handler(
            state["message"],
            state["client"],
            state["session"],
            state["intent"],
        )
        span["model"] = response.metadata.get("model")
        span["tokens_in"] = response.metadata.get("input_tokens")
        span["tokens_out"] = response.metadata.get("output_tokens")
        span["details"] = {
            "agent": response.agent,
            "response_preview": _preview_response(response),
        }

    return {
        **state,
        "response": response,
    }


async def _diary_node(state: LiveWorkflowState) -> LiveWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.DIARY.value)


async def _memory_node(state: LiveWorkflowState) -> LiveWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.MEMORY.value)


async def _review_node(state: LiveWorkflowState) -> LiveWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.REVIEW.value)


async def _project_node(state: LiveWorkflowState) -> LiveWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.PROJECT.value)


async def _communications_node(state: LiveWorkflowState) -> LiveWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.COMMUNICATIONS.value)


async def _notification_node(state: LiveWorkflowState) -> LiveWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.NOTIFICATION.value)


async def _plan_day_node(state: LiveWorkflowState) -> LiveWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.PLAN_DAY.value)


async def _research_node(state: LiveWorkflowState) -> LiveWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.RESEARCH.value)


async def _tools_node(state: LiveWorkflowState) -> LiveWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.TOOLS.value)


async def _save_node(state: LiveWorkflowState) -> LiveWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.SAVE.value)


async def _socratic_node(state: LiveWorkflowState) -> LiveWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.SOCRATIC.value)


@lru_cache(maxsize=1)
def _compiled_live_workflow_graph():
    graph = StateGraph(LiveWorkflowState)
    graph.add_node("dispatch", _dispatch_node)
    graph.add_node("unsupported", _unsupported_node)
    graph.add_node(Specialist.DIARY.value, _diary_node)
    graph.add_node(Specialist.MEMORY.value, _memory_node)
    graph.add_node(Specialist.REVIEW.value, _review_node)
    graph.add_node(Specialist.PROJECT.value, _project_node)
    graph.add_node(Specialist.COMMUNICATIONS.value, _communications_node)
    graph.add_node(Specialist.NOTIFICATION.value, _notification_node)
    graph.add_node(Specialist.PLAN_DAY.value, _plan_day_node)
    graph.add_node(Specialist.RESEARCH.value, _research_node)
    graph.add_node(Specialist.TOOLS.value, _tools_node)
    graph.add_node(Specialist.SAVE.value, _save_node)
    graph.add_node(Specialist.SOCRATIC.value, _socratic_node)
    graph.add_edge(START, "dispatch")
    graph.add_conditional_edges(
        "dispatch",
        _route_to_specialist,
        {
            Specialist.DIARY.value: Specialist.DIARY.value,
            Specialist.MEMORY.value: Specialist.MEMORY.value,
            Specialist.REVIEW.value: Specialist.REVIEW.value,
            Specialist.PROJECT.value: Specialist.PROJECT.value,
            Specialist.COMMUNICATIONS.value: Specialist.COMMUNICATIONS.value,
            Specialist.NOTIFICATION.value: Specialist.NOTIFICATION.value,
            Specialist.PLAN_DAY.value: Specialist.PLAN_DAY.value,
            Specialist.RESEARCH.value: Specialist.RESEARCH.value,
            Specialist.TOOLS.value: Specialist.TOOLS.value,
            Specialist.SAVE.value: Specialist.SAVE.value,
            Specialist.SOCRATIC.value: Specialist.SOCRATIC.value,
            "unsupported": "unsupported",
        },
    )
    for specialist in _SUPPORTED_SPECIALISTS:
        graph.add_edge(specialist, END)
    graph.add_edge("unsupported", END)
    return graph.compile()


def _preview_response(response: ChatResponse | None) -> str | None:
    if response is None:
        return None
    rendered = response.content.strip()
    if rendered:
        return rendered[:500]
    return None


async def maybe_execute_live_workflow(
    *,
    message: MessageInput,
    intent: Intent,
    client: AsyncAnthropic,
    session: AsyncSession,
    trace_recorder: TraceRecorder,
    parent_span_id: str | None,
    settings: Settings | None = None,
) -> LiveWorkflowOutcome | None:
    """Execute a supported specialist through the live LangGraph runtime.

    Returns ``None`` only when the feature flag is disabled or settings are unavailable.
    All runtime failures are converted into a fallback outcome so the caller can
    continue on the legacy path.
    """
    try:
        settings = settings or get_settings()
    except Exception:
        logger.warning("workflow_live_runtime_settings_unavailable", exc_info=True)
        return None

    if not _flag_enabled(getattr(settings, "workflow_live_runtime_enabled", False)):
        return None

    specialist = str(intent.specialist)
    outcome = LiveWorkflowOutcome(specialist=specialist)
    timeout_ms = _timeout_ms(
        getattr(settings, "workflow_live_runtime_timeout_ms", 3_000),
        default=3_000,
    )
    timeout_seconds = timeout_ms / 1000
    allowed_specialists = _specialist_names(
        getattr(settings, "workflow_live_runtime_specialist_names", [])
    )
    start = time.monotonic()
    graph = _compiled_live_workflow_graph()

    try:
        result = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "message": message,
                    "client": client,
                    "session": session,
                    "intent": intent,
                    "trace_recorder": trace_recorder,
                    "parent_span_id": parent_span_id,
                    "allowed_specialists": allowed_specialists,
                    # TraceRecorder.trace_id already falls back to metadata
                    # "request_id" — propagate it explicitly so graph nodes
                    # and downstream helpers can read it from state.
                    "request_id": trace_recorder.trace_id,
                }
            ),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        outcome.status = "timeout"
        outcome.reason = "workflow_runtime_timeout"
        outcome.fallback_used = True
        outcome.latency_ms = int((time.monotonic() - start) * 1000)
        trace_recorder.add_span(
            name="workflow.live.timeout",
            span_kind=TraceSpanKind.SPECIALIST,
            parent_span_id=parent_span_id,
            specialist=specialist,
            status=TraceSpanStatus.DEGRADED,
            latency_ms=outcome.latency_ms,
            details={"timeout_ms": timeout_ms},
        )
        return outcome
    except Exception as exc:
        outcome.status = "error"
        outcome.reason = type(exc).__name__
        outcome.fallback_used = True
        outcome.latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning("workflow_live_runtime_failed", specialist=specialist, exc_info=True)
        trace_recorder.add_span(
            name="workflow.live.error",
            span_kind=TraceSpanKind.SPECIALIST,
            parent_span_id=parent_span_id,
            specialist=specialist,
            status=TraceSpanStatus.DEGRADED,
            error_class=type(exc).__name__,
            latency_ms=outcome.latency_ms,
            details={"error": type(exc).__name__},
        )
        return outcome

    outcome.latency_ms = int((time.monotonic() - start) * 1000)
    response = result.get("response")
    if isinstance(response, ChatResponse):
        outcome.status = "completed"
        outcome.executed = True
        outcome.response_agent = response.agent
        outcome.response_preview = _preview_response(response)
        outcome.response = response
        return outcome

    outcome.status = "skipped"
    outcome.reason = str(result.get("skip_reason") or "workflow_runtime_skipped")
    outcome.fallback_used = True
    return outcome
