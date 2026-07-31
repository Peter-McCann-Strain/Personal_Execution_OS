"""LangGraph-backed shadow workflow for read-only runtime comparisons."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from functools import lru_cache
from typing import Any, TypedDict

import structlog
from anthropic import AsyncAnthropic
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from src.app.agents.specialists.communications import triage_email
from src.app.agents.specialists.diary import process_diary_entry
from src.app.agents.specialists.memory import answer_from_memory
from src.app.agents.specialists.project import ai_breakdown_project
from src.app.agents.specialists.review import generate_weekly_review
from src.app.config import Settings, get_settings
from src.app.core.trace import TraceRecorder
from src.app.domain.constants import TraceSpanKind, TraceSpanStatus
from src.app.domain.models import Intent, Specialist
from src.app.domain.services.orchestrator import classify_intent

logger = structlog.get_logger()

_READ_ONLY_SPECIALISTS = frozenset(
    {
        Specialist.DIARY.value,
        Specialist.MEMORY.value,
        Specialist.REVIEW.value,
        Specialist.PROJECT.value,
        Specialist.COMMUNICATIONS.value,
    }
)


class ShadowWorkflowOutcome(BaseModel):
    """Shadow execution summary persisted for operator inspection."""

    workflow_id: str
    live_workflow_id: str
    live_specialist: str
    shadow_specialist: str | None = None
    route_match: bool | None = None
    executed: bool = False
    status: str = "skipped"
    skipped_reason: str | None = None
    confidence: float | None = None
    result_preview: str | None = None
    latency_ms: int | None = None


class ShadowWorkflowState(TypedDict, total=False):
    """Minimal graph state for read-only shadow execution."""

    route_message: str
    message: str
    client: AsyncAnthropic
    context_chunks: list[dict[str, Any]]
    trace_recorder: TraceRecorder
    parent_span_id: str | None
    allowed_specialists: list[str]
    intent: Intent
    specialist: str
    result: dict[str, Any]
    executed: bool
    skip_reason: str


async def _classify_node(state: ShadowWorkflowState) -> ShadowWorkflowState:
    recorder = state["trace_recorder"]
    with recorder.timed_span(
        name="shadow.classify",
        span_kind=TraceSpanKind.ROUTING,
        parent_span_id=state.get("parent_span_id"),
    ) as span:
        intent = await classify_intent(state["route_message"], state["client"])
        span["details"] = {
            "specialist": str(intent.specialist),
            "confidence": intent.confidence,
        }
    return {
        **state,
        "intent": intent,
        "specialist": str(intent.specialist),
    }


def _route_to_specialist(state: ShadowWorkflowState) -> str:
    specialist = str(state.get("specialist") or "").strip()
    allowed = {value.strip() for value in state.get("allowed_specialists", []) if value.strip()}
    if not specialist:
        return "unsupported"
    if allowed and specialist not in allowed:
        return "unsupported"
    if specialist not in _READ_ONLY_SPECIALISTS:
        return "unsupported"
    return specialist


async def _unsupported_node(state: ShadowWorkflowState) -> ShadowWorkflowState:
    recorder = state["trace_recorder"]
    specialist = str(state.get("specialist") or "")
    allowed = set(state.get("allowed_specialists", []))
    if specialist and specialist not in _READ_ONLY_SPECIALISTS:
        reason = f"shadow_execution_not_supported_for_{specialist}"
    elif specialist and specialist not in allowed:
        reason = f"shadow_specialist_disabled_{specialist}"
    else:
        reason = "shadow_specialist_missing"

    with recorder.timed_span(
        name="shadow.execute.unsupported",
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
        "executed": False,
        "skip_reason": reason,
    }


async def _execute_specialist(
    state: ShadowWorkflowState,
    *,
    specialist: str,
) -> ShadowWorkflowState:
    recorder = state["trace_recorder"]
    client = state["client"]
    message = state["message"]

    with recorder.timed_span(
        name=f"shadow.execute.{specialist}",
        span_kind=TraceSpanKind.SPECIALIST,
        parent_span_id=state.get("parent_span_id"),
        specialist=specialist,
    ) as span:
        if specialist == Specialist.DIARY.value:
            result = (await process_diary_entry(message, client)).model_dump()
        elif specialist == Specialist.MEMORY.value:
            result = (
                await answer_from_memory(
                    message,
                    state.get("context_chunks", []),
                    client,
                )
            ).model_dump()
        elif specialist == Specialist.REVIEW.value:
            result = (await generate_weekly_review(message, client)).model_dump()
        elif specialist == Specialist.PROJECT.value:
            result = (await ai_breakdown_project(message, client)).model_dump()
        elif specialist == Specialist.COMMUNICATIONS.value:
            result = (await triage_email(message, client)).model_dump()
        else:
            raise RuntimeError(f"Unsupported shadow specialist: {specialist}")

        span["details"] = {
            "specialist": specialist,
            "result_preview": _preview_shadow_result(result),
        }

    return {
        **state,
        "result": result,
        "executed": True,
    }


async def _diary_node(state: ShadowWorkflowState) -> ShadowWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.DIARY.value)


async def _memory_node(state: ShadowWorkflowState) -> ShadowWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.MEMORY.value)


async def _review_node(state: ShadowWorkflowState) -> ShadowWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.REVIEW.value)


async def _project_node(state: ShadowWorkflowState) -> ShadowWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.PROJECT.value)


async def _communications_node(state: ShadowWorkflowState) -> ShadowWorkflowState:
    return await _execute_specialist(state, specialist=Specialist.COMMUNICATIONS.value)


@lru_cache(maxsize=1)
def _compiled_shadow_graph():
    graph = StateGraph(ShadowWorkflowState)
    graph.add_node("classify", _classify_node)
    graph.add_node("unsupported", _unsupported_node)
    graph.add_node(Specialist.DIARY.value, _diary_node)
    graph.add_node(Specialist.MEMORY.value, _memory_node)
    graph.add_node(Specialist.REVIEW.value, _review_node)
    graph.add_node(Specialist.PROJECT.value, _project_node)
    graph.add_node(Specialist.COMMUNICATIONS.value, _communications_node)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        _route_to_specialist,
        {
            Specialist.DIARY.value: Specialist.DIARY.value,
            Specialist.MEMORY.value: Specialist.MEMORY.value,
            Specialist.REVIEW.value: Specialist.REVIEW.value,
            Specialist.PROJECT.value: Specialist.PROJECT.value,
            Specialist.COMMUNICATIONS.value: Specialist.COMMUNICATIONS.value,
            "unsupported": "unsupported",
        },
    )
    graph.add_edge(Specialist.DIARY.value, END)
    graph.add_edge(Specialist.MEMORY.value, END)
    graph.add_edge(Specialist.REVIEW.value, END)
    graph.add_edge(Specialist.PROJECT.value, END)
    graph.add_edge(Specialist.COMMUNICATIONS.value, END)
    graph.add_edge("unsupported", END)
    return graph.compile()


def _should_sample(trace_id: str, sample_rate: float) -> bool:
    if sample_rate <= 0.0:
        return False
    if sample_rate >= 1.0:
        return True
    digest = hashlib.blake2s(trace_id.encode("utf-8"), digest_size=4).digest()
    bucket = int.from_bytes(digest, "big") / 0xFFFFFFFF
    return bucket < sample_rate


def _preview_shadow_result(result: dict[str, Any] | None) -> str | None:
    if not isinstance(result, dict):
        return None

    for key in (
        "answer",
        "user_reply",
        "summary",
        "review",
        "message",
        "recommendation",
        "decision",
        "subject",
        "body",
    ):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]

    for key in ("tasks", "action_items", "follow_up_suggestions", "labels"):
        value = result.get(key)
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
            if items:
                return "; ".join(items)[:500]

    rendered = str(result).strip()
    return rendered[:500] if rendered else None


async def maybe_run_shadow_workflow(
    *,
    live_workflow_id: str,
    live_specialist: str,
    route_message: str,
    specialist_message: str,
    context_chunks: list[dict[str, Any]],
    client: AsyncAnthropic,
    trace_recorder: TraceRecorder,
    parent_span_id: str | None,
    settings: Settings | None = None,
) -> ShadowWorkflowOutcome | None:
    """Run one read-only LangGraph shadow workflow when enabled.

    The shadow path never raises into the live request path.
    """
    try:
        settings = settings or get_settings()
    except Exception:
        logger.warning("workflow_shadow_settings_unavailable", exc_info=True)
        return None

    if not settings.workflow_shadow_mode_enabled:
        return None
    if not _should_sample(
        trace_recorder.trace_id,
        settings.workflow_shadow_mode_sample_rate,
    ):
        return None

    workflow_id = str(uuid.uuid4())
    outcome = ShadowWorkflowOutcome(
        workflow_id=workflow_id,
        live_workflow_id=live_workflow_id,
        live_specialist=live_specialist,
    )
    allowed_specialists = list(settings.workflow_shadow_specialist_names)
    start = time.monotonic()
    timeout_seconds = max(settings.workflow_shadow_mode_timeout_ms, 100) / 1000
    graph = _compiled_shadow_graph()

    try:
        result = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "route_message": route_message,
                    "message": specialist_message,
                    "client": client,
                    "context_chunks": context_chunks,
                    "trace_recorder": trace_recorder,
                    "parent_span_id": parent_span_id,
                    "allowed_specialists": allowed_specialists,
                }
            ),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        outcome.status = "timeout"
        outcome.skipped_reason = "shadow_timeout"
        outcome.latency_ms = int((time.monotonic() - start) * 1000)
        trace_recorder.add_span(
            name="shadow.timeout",
            span_kind=TraceSpanKind.EVALUATION,
            parent_span_id=parent_span_id,
            specialist=live_specialist,
            status=TraceSpanStatus.DEGRADED,
            latency_ms=outcome.latency_ms,
            details={"timeout_ms": settings.workflow_shadow_mode_timeout_ms},
        )
        return outcome
    except Exception as exc:
        outcome.status = "error"
        outcome.skipped_reason = type(exc).__name__
        outcome.latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning("workflow_shadow_failed", exc_info=True)
        trace_recorder.add_span(
            name="shadow.error",
            span_kind=TraceSpanKind.EVALUATION,
            parent_span_id=parent_span_id,
            specialist=live_specialist,
            status=TraceSpanStatus.DEGRADED,
            error_class=type(exc).__name__,
            latency_ms=outcome.latency_ms,
            details={"error": type(exc).__name__},
        )
        return outcome

    outcome.latency_ms = int((time.monotonic() - start) * 1000)
    shadow_specialist = str(result.get("specialist") or "")
    outcome.shadow_specialist = shadow_specialist or None
    if shadow_specialist:
        outcome.route_match = shadow_specialist == live_specialist

    intent = result.get("intent")
    confidence = getattr(intent, "confidence", None)
    if isinstance(confidence, float):
        outcome.confidence = confidence

    if result.get("executed"):
        outcome.executed = True
        outcome.status = "completed"
        outcome.result_preview = _preview_shadow_result(result.get("result"))
    else:
        outcome.status = "skipped"
        outcome.skipped_reason = str(result.get("skip_reason") or "shadow_skipped")

    return outcome
