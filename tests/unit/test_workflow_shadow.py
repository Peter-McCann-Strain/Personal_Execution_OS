"""Tests for LangGraph-backed workflow shadow execution."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.trace import TraceRecorder
from src.app.core.workflow_shadow import ShadowWorkflowOutcome, maybe_run_shadow_workflow
from src.app.domain.models import Intent, IntentType, Specialist


def _shadow_settings(*, specialists: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        workflow_shadow_mode_enabled=True,
        workflow_shadow_mode_sample_rate=1.0,
        workflow_shadow_mode_timeout_ms=1_500,
        workflow_shadow_specialist_names=specialists or ["review", "memory", "project"],
    )


@pytest.mark.asyncio
async def test_shadow_workflow_executes_supported_specialist() -> None:
    """Shadow workflow should classify and execute one supported specialist."""
    intent = Intent(
        intent_type=IntentType.REVIEW,
        confidence=0.91,
        specialist=Specialist.REVIEW,
        reasoning="weekly review request",
    )
    fake_review = MagicMock()
    fake_review.model_dump.return_value = {"review": "Shadow review output"}
    recorder = TraceRecorder.create(channel="test", user_id="user-1", trace_id="trace-review")

    with (
        patch(
            "src.app.core.workflow_shadow.classify_intent",
            new_callable=AsyncMock,
            return_value=intent,
        ),
        patch(
            "src.app.core.workflow_shadow.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=fake_review,
        ) as mock_review,
    ):
        outcome = await maybe_run_shadow_workflow(
            live_workflow_id=str(uuid.uuid4()),
            live_specialist=Specialist.REVIEW.value,
            route_message="Can you review my week?",
            specialist_message="Can you review my week?",
            context_chunks=[],
            client=AsyncMock(),
            trace_recorder=recorder,
            parent_span_id="parent-span",
            settings=_shadow_settings(),
        )

    assert outcome is not None
    assert outcome.status == "completed"
    assert outcome.executed is True
    assert outcome.shadow_specialist == Specialist.REVIEW.value
    assert outcome.route_match is True
    assert outcome.result_preview == "Shadow review output"
    mock_review.assert_awaited_once()
    span_names = [span.name for span in recorder.spans]
    assert "shadow.classify" in span_names
    assert "shadow.execute.review" in span_names


@pytest.mark.asyncio
async def test_shadow_workflow_skips_unsupported_specialist() -> None:
    """Shadow workflow should still compare routing but skip unsafe specialists."""
    intent = Intent(
        intent_type=IntentType.RESEARCH,
        confidence=0.88,
        specialist=Specialist.RESEARCH,
        reasoning="research request",
    )
    recorder = TraceRecorder.create(
        channel="telegram",
        user_id="user-1",
        trace_id="trace-research",
    )

    with patch(
        "src.app.core.workflow_shadow.classify_intent",
        new_callable=AsyncMock,
        return_value=intent,
    ):
        outcome = await maybe_run_shadow_workflow(
            live_workflow_id=str(uuid.uuid4()),
            live_specialist=Specialist.REVIEW.value,
            route_message="Research the latest CPU releases",
            specialist_message="Research the latest CPU releases",
            context_chunks=[],
            client=AsyncMock(),
            trace_recorder=recorder,
            parent_span_id="parent-span",
            settings=_shadow_settings(),
        )

    assert outcome is not None
    assert outcome.status == "skipped"
    assert outcome.executed is False
    assert outcome.shadow_specialist == Specialist.RESEARCH.value
    assert outcome.route_match is False
    assert outcome.skipped_reason == "shadow_execution_not_supported_for_research"


@pytest.mark.asyncio
async def test_shadow_workflow_timeout_is_fail_open() -> None:
    """Timeouts should return a shadow outcome without raising into the caller."""
    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(side_effect=TimeoutError())
    recorder = TraceRecorder.create(channel="api", user_id="user-1", trace_id="trace-timeout")

    with patch(
        "src.app.core.workflow_shadow._compiled_shadow_graph",
        return_value=fake_graph,
    ):
        outcome = await maybe_run_shadow_workflow(
            live_workflow_id=str(uuid.uuid4()),
            live_specialist=Specialist.MEMORY.value,
            route_message="What was I working on yesterday?",
            specialist_message="What was I working on yesterday?",
            context_chunks=[],
            client=AsyncMock(),
            trace_recorder=recorder,
            parent_span_id="parent-span",
            settings=_shadow_settings(specialists=["memory"]),
        )

    assert outcome == ShadowWorkflowOutcome(
        workflow_id=outcome.workflow_id,
        live_workflow_id=outcome.live_workflow_id,
        live_specialist=Specialist.MEMORY.value,
        status="timeout",
        skipped_reason="shadow_timeout",
        latency_ms=outcome.latency_ms,
    )
    assert any(span.name == "shadow.timeout" for span in recorder.spans)
