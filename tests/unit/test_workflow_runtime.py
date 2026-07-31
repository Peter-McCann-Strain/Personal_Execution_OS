"""Tests for the live LangGraph workflow runtime."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.trace import TraceRecorder
from src.app.core.workflow_runtime import LiveWorkflowOutcome, maybe_execute_live_workflow
from src.app.domain.models import ChatResponse, Intent, IntentType, MessageInput, Specialist


def _runtime_settings(*, specialists: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        workflow_live_runtime_enabled=True,
        workflow_live_runtime_timeout_ms=3_000,
        workflow_live_runtime_specialist_names=specialists
        or [
            "review",
            "memory",
            "project",
            "notification",
            "plan_day",
            "research",
            "tools",
            "save",
            "socratic",
        ],
    )


def _message(content: str) -> MessageInput:
    return MessageInput(
        content=content,
        source="test",
        user_id="user-1",
    )


@pytest.mark.asyncio
async def test_live_workflow_executes_supported_specialist() -> None:
    """Supported specialists should return the graph-produced response."""
    intent = Intent(
        intent_type=IntentType.REVIEW,
        confidence=0.93,
        specialist=Specialist.REVIEW,
        reasoning="weekly review request",
    )
    response = ChatResponse(content="Workflow review", agent="review", metadata={})
    recorder = TraceRecorder.create(channel="test", user_id="user-1", trace_id="trace-live")

    with patch(
        "src.app.core.workflow_runtime.handle_review",
        new_callable=AsyncMock,
        return_value=response,
    ) as mock_handler:
        outcome = await maybe_execute_live_workflow(
            message=_message("Can you review my week?"),
            intent=intent,
            client=AsyncMock(),
            session=AsyncMock(),
            trace_recorder=recorder,
            parent_span_id="parent-span",
            settings=_runtime_settings(),
        )

    assert outcome == LiveWorkflowOutcome(
        specialist=Specialist.REVIEW.value,
        status="completed",
        executed=True,
        latency_ms=outcome.latency_ms,
        response_agent="review",
        response_preview="Workflow review",
        response=response,
    )
    mock_handler.assert_awaited_once()
    span_names = [span.name for span in recorder.spans]
    assert "workflow.live.dispatch" in span_names
    assert "workflow.live.execute.review" in span_names


@pytest.mark.asyncio
async def test_live_workflow_skips_disabled_specialist() -> None:
    """Disabled specialists should fall back without raising into chat."""
    intent = Intent(
        intent_type=IntentType.QUERY,
        confidence=0.81,
        specialist=Specialist.MEMORY,
        reasoning="memory lookup",
    )
    recorder = TraceRecorder.create(channel="telegram", user_id="user-1", trace_id="trace-skip")

    outcome = await maybe_execute_live_workflow(
        message=_message("What was I working on yesterday?"),
        intent=intent,
        client=AsyncMock(),
        session=AsyncMock(),
        trace_recorder=recorder,
        parent_span_id="parent-span",
        settings=_runtime_settings(specialists=["review"]),
    )

    assert outcome is not None
    assert outcome.status == "skipped"
    assert outcome.fallback_used is True
    assert outcome.reason == "workflow_runtime_disabled_memory"
    assert outcome.response is None


@pytest.mark.asyncio
async def test_live_workflow_timeout_is_fail_open() -> None:
    """Timeouts should produce a fallback outcome instead of raising."""
    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(side_effect=TimeoutError())
    recorder = TraceRecorder.create(channel="api", user_id="user-1", trace_id="trace-timeout")
    intent = Intent(
        intent_type=IntentType.QUERY,
        confidence=0.82,
        specialist=Specialist.MEMORY,
        reasoning="memory lookup",
    )

    with patch(
        "src.app.core.workflow_runtime._compiled_live_workflow_graph",
        return_value=fake_graph,
    ):
        outcome = await maybe_execute_live_workflow(
            message=_message("What was I working on yesterday?"),
            intent=intent,
            client=AsyncMock(),
            session=AsyncMock(),
            trace_recorder=recorder,
            parent_span_id="parent-span",
            settings=_runtime_settings(specialists=["memory"]),
        )

    assert outcome == LiveWorkflowOutcome(
        specialist=Specialist.MEMORY.value,
        status="timeout",
        fallback_used=True,
        reason="workflow_runtime_timeout",
        latency_ms=outcome.latency_ms,
    )
    assert any(span.name == "workflow.live.timeout" for span in recorder.spans)


@pytest.mark.asyncio
async def test_live_workflow_executes_plan_day_specialist() -> None:
    """Plan-day specialist should execute through the live runtime graph."""
    intent = Intent(
        intent_type=IntentType.PLAN_DAY,
        confidence=0.88,
        specialist=Specialist.PLAN_DAY,
        reasoning="daily planning request",
    )
    response = ChatResponse(content="09:00-11:00 - Deep work", agent="plan_day", metadata={})
    recorder = TraceRecorder.create(channel="api", user_id="user-1", trace_id="trace-plan-day")

    with patch(
        "src.app.core.workflow_runtime.handle_plan_day",
        new_callable=AsyncMock,
        return_value=response,
    ) as mock_handler:
        outcome = await maybe_execute_live_workflow(
            message=_message("Plan my day"),
            intent=intent,
            client=AsyncMock(),
            session=AsyncMock(),
            trace_recorder=recorder,
            parent_span_id="parent-span",
            settings=_runtime_settings(),
        )

    assert outcome is not None
    assert outcome.status == "completed"
    assert outcome.executed is True
    assert outcome.response_agent == "plan_day"
    assert outcome.response_preview == "09:00-11:00 - Deep work"
    mock_handler.assert_awaited_once()
    assert any(span.name == "workflow.live.execute.plan_day" for span in recorder.spans)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_type", "specialist", "handler_path", "agent", "content"),
    [
        (
            IntentType.RESEARCH,
            Specialist.RESEARCH,
            "src.app.core.workflow_runtime.handle_research",
            "research",
            "Research summary",
        ),
        (
            IntentType.COMMAND,
            Specialist.TOOLS,
            "src.app.core.workflow_runtime.handle_tools",
            "tools",
            "Tool execution summary",
        ),
        (
            IntentType.SAVE,
            Specialist.SAVE,
            "src.app.core.workflow_runtime.handle_save",
            "save",
            "Saved that URL",
        ),
        (
            IntentType.TUTORIAL,
            Specialist.SOCRATIC,
            "src.app.core.workflow_runtime.handle_socratic",
            "socratic",
            "Let's explore that step by step",
        ),
    ],
)
async def test_live_workflow_executes_extended_specialists(
    intent_type: IntentType,
    specialist: Specialist,
    handler_path: str,
    agent: str,
    content: str,
) -> None:
    """Additional specialists should execute via the live workflow runtime."""
    intent = Intent(
        intent_type=intent_type,
        confidence=0.89,
        specialist=specialist,
        reasoning="extended workflow test",
    )
    response = ChatResponse(content=content, agent=agent, metadata={})
    recorder = TraceRecorder.create(
        channel="api",
        user_id="user-1",
        trace_id=f"trace-{specialist.value}",
    )

    with patch(
        handler_path,
        new_callable=AsyncMock,
        return_value=response,
    ) as mock_handler:
        outcome = await maybe_execute_live_workflow(
            message=_message(f"Run {specialist.value}"),
            intent=intent,
            client=AsyncMock(),
            session=AsyncMock(),
            trace_recorder=recorder,
            parent_span_id="parent-span",
            settings=_runtime_settings(),
        )

    assert outcome is not None
    assert outcome.status == "completed"
    assert outcome.executed is True
    assert outcome.response_agent == agent
    assert outcome.response_preview == content
    mock_handler.assert_awaited_once()
    assert any(span.name == f"workflow.live.execute.{specialist.value}" for span in recorder.spans)
