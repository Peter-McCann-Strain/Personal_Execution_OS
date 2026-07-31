"""Tests for plan my day handler."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.exceptions import DatabaseError, LLMError
from src.app.domain.models import (
    ChatResponse,
    DayPlanArtifact,
    DayPlanTask,
    Intent,
    IntentType,
    MessageInput,
    PendingPlanningSession,
    Specialist,
)
from src.app.domain.services.day_plans import StoredDayPlan
from src.app.domain.services.handlers.plan_day import (
    EveningCloseoutTask,
    EveningCloseoutTurn,
    MorningPlanningTurn,
    _fetch_commitments,
    _fetch_goals,
    _fetch_tasks,
    handle_plan_day,
)


def _make_message(content: str = "plan my day") -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _make_intent() -> Intent:
    return Intent(
        intent_type=IntentType.COMMAND,
        confidence=0.95,
        specialist=Specialist.TOOLS,
        reasoning="Plan day request",
    )


def _mock_commitments():
    """Return mock commitment rows."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "normalized_action": "Team standup meeting",
        "temporal_normalized": datetime(2026, 3, 16, 10, 0, tzinfo=UTC),
    }[key]
    row.keys = lambda: ["normalized_action", "temporal_normalized"]
    return [row]


def _mock_goals():
    """Return mock goal rows."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "title": "Launch MVP",
        "progress": 0.65,
        "priority": 1,
    }[key]
    row.keys = lambda: ["title", "progress", "priority"]
    return [row]


def _mock_tasks():
    """Return mock task rows."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "title": "Write integration tests",
        "status": "in_progress",
        "complexity": "high",
        "context_tags": ["testing", "backend"],
    }[key]
    row.keys = lambda: ["title", "status", "complexity", "context_tags"]
    return [row]


def _make_mock_result(rows):
    """Create a mock SQLAlchemy result with mappings().all() returning rows."""
    mapping_objs = []
    for row in rows:
        mapping = {k: row[k] for k in row.keys()}  # noqa: SIM118 — .keys() needed for MagicMock
        mapping_objs.append(mapping)

    mappings_mock = MagicMock()
    mappings_mock.all.return_value = mapping_objs

    result = MagicMock()
    result.mappings.return_value = mappings_mock
    return result


def _make_empty_result():
    """Create a mock SQLAlchemy result with empty mappings."""
    return _make_mock_result([])


class TestHandlePlanDay:
    async def test_plan_day_success(self):
        """Full pipeline: fetch commitments, goals, tasks -> generate plan."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        # Set up session.execute to return different results for each query
        commitment_result = _make_mock_result(_mock_commitments())
        goal_result = _make_mock_result(_mock_goals())
        task_result = _make_mock_result(_mock_tasks())

        mock_session.execute = AsyncMock(side_effect=[commitment_result, goal_result, task_result])

        expected_plan = (
            "# Today's Plan\n\n"
            "## 9:00-10:00 - Deep Work\n"
            "- Write integration tests (high complexity)\n\n"
            "## 10:00-10:30 - Team standup meeting\n\n"
            "## Key Priorities\n"
            "1. Make progress on integration tests\n"
            "2. Advance MVP toward 70% completion"
        )

        with patch(
            "src.app.domain.services.handlers.plan_day.call_and_extract_text",
            new_callable=AsyncMock,
            return_value=expected_plan,
        ):
            result = await handle_plan_day(message, mock_client, mock_session, _make_intent())

        assert isinstance(result, ChatResponse)
        assert result.agent == "plan_day"
        assert result.content == expected_plan
        assert result.metadata["commitment_count"] == 1
        assert result.metadata["goal_count"] == 1
        assert result.metadata["task_count"] == 1

    async def test_plan_day_no_data(self):
        """When no commitments, goals, or tasks exist, still generates a plan."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        # All queries return empty results
        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        with patch(
            "src.app.domain.services.handlers.plan_day.call_and_extract_text",
            new_callable=AsyncMock,
            return_value="You have a clear day! Here's a suggested plan based on your energy...",
        ):
            result = await handle_plan_day(message, mock_client, mock_session, _make_intent())

        assert isinstance(result, ChatResponse)
        assert result.agent == "plan_day"
        assert len(result.content) > 0
        assert result.metadata["commitment_count"] == 0
        assert result.metadata["goal_count"] == 0
        assert result.metadata["task_count"] == 0

    async def test_plan_day_llm_failure_propagates(self):
        """When LLM call fails, the error should propagate."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        # Return some data so we can verify fallback includes it
        commitment_result = _make_mock_result(_mock_commitments())
        mock_session.execute = AsyncMock(
            side_effect=[
                commitment_result,
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        with (
            patch(
                "src.app.domain.services.handlers.plan_day.call_and_extract_text",
                new_callable=AsyncMock,
                side_effect=LLMError("API unavailable"),
            ),
            pytest.raises(LLMError, match="API unavailable"),
        ):
            await handle_plan_day(message, mock_client, mock_session, _make_intent())

    async def test_plan_day_db_failure_propagates(self):
        """When DB queries fail, the error should propagate."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        # All DB queries raise exceptions
        mock_session.execute = AsyncMock(side_effect=Exception("Connection refused"))

        with pytest.raises(DatabaseError, match="plan_day data fetch failed"):
            await handle_plan_day(message, mock_client, mock_session, _make_intent())

    async def test_plan_day_passes_energy_schedule(self):
        """Verify the energy schedule is included in the LLM prompt."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        with patch(
            "src.app.domain.services.handlers.plan_day.call_and_extract_text",
            new_callable=AsyncMock,
            return_value="Plan with energy blocks...",
        ) as mock_llm:
            await handle_plan_day(message, mock_client, mock_session, _make_intent())

        # Check that the user message sent to LLM contains energy schedule info
        call_kwargs = mock_llm.call_args
        messages = call_kwargs.kwargs["messages"]
        user_content = messages[0]["content"]
        assert "Energy Schedule" in user_content
        assert "deep_work" in user_content

    async def test_plan_day_custom_message(self):
        """Additional user instructions are appended to the LLM prompt."""
        message = _make_message("Plan my day but focus on the MVP launch")
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        with patch(
            "src.app.domain.services.handlers.plan_day.call_and_extract_text",
            new_callable=AsyncMock,
            return_value="Focused MVP plan...",
        ) as mock_llm:
            result = await handle_plan_day(message, mock_client, mock_session, _make_intent())

        call_kwargs = mock_llm.call_args
        messages = call_kwargs.kwargs["messages"]
        user_content = messages[0]["content"]
        assert "MVP launch" in user_content
        assert result.content == "Focused MVP plan..."

    async def test_plan_day_formats_tbd_zero_progress_and_default_task_fields(self):
        """The context builder falls back cleanly for missing timestamps and task metadata."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        commitment_result = _make_mock_result(
            [
                {
                    "normalized_action": "Follow up with Alex",
                    "temporal_normalized": None,
                }
            ]
        )
        goal_result = _make_mock_result(
            [
                {
                    "title": "Refine launch plan",
                    "progress": None,
                    "priority": 2,
                }
            ]
        )
        task_result = _make_mock_result(
            [
                {
                    "title": "Draft launch checklist",
                    "status": "backlog",
                    "complexity": None,
                    "context_tags": [],
                }
            ]
        )
        mock_session.execute = AsyncMock(side_effect=[commitment_result, goal_result, task_result])

        with patch(
            "src.app.domain.services.handlers.plan_day.call_and_extract_text",
            new_callable=AsyncMock,
            return_value="Fallback-aware plan",
        ) as mock_llm:
            result = await handle_plan_day(message, mock_client, mock_session, _make_intent())

        user_content = mock_llm.call_args.kwargs["messages"][0]["content"]
        assert "[TBD] Follow up with Alex" in user_content
        assert "Refine launch plan (0% complete, priority 2)" in user_content
        assert "Draft launch checklist [backlog] (complexity: medium, tags: none)" in user_content
        assert result.content == "Fallback-aware plan"

    async def test_interactive_morning_plan_requests_more_input(self):
        """Pending morning planning sessions should keep the loop open when details are vague."""
        message = MessageInput(
            content="I need a sensible day",
            source="test",
            user_id="user-1",
            metadata={
                "pending_planning_session": PendingPlanningSession(
                    session_type="morning_plan",
                    source_date="2026-04-13",
                    stage="invited",
                    expires_at=datetime(2026, 4, 13, 10, 0, tzinfo=UTC),
                ).model_dump(mode="json")
            },
        )
        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        with (
            patch(
                "src.app.domain.services.handlers.plan_day.load_carry_over_tasks",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.domain.services.handlers.plan_day.call_and_parse",
                new_callable=AsyncMock,
                return_value=MorningPlanningTurn(
                    outcome="needs_input",
                    assistant_reply="What are the two outcomes you most want by tonight?",
                ),
            ),
        ):
            result = await handle_plan_day(message, mock_client, mock_session, _make_intent())

        assert result.agent == "plan_day"
        assert "two outcomes" in result.content
        assert "pending_planning_session" in result.metadata
        assert result.metadata.get("pending_planning_session_cleared") is None

    async def test_interactive_morning_plan_confirmation_persists_artifact(self):
        """A confirmed morning draft should finalize and clear the planning session."""
        draft_plan = DayPlanArtifact(
            source_date="2026-04-13",
            status="draft",
            plan_summary="Finish the key launch work and admin cleanup.",
            plan_text="- Finish launch checklist\n- Reply to Alice",
            tasks=[
                DayPlanTask(title="Finish launch checklist"),
                DayPlanTask(title="Reply to Alice"),
            ],
        )
        message = MessageInput(
            content="yes",
            source="test",
            user_id="user-1",
            metadata={
                "pending_planning_session": PendingPlanningSession(
                    session_type="morning_plan",
                    source_date="2026-04-13",
                    stage="confirming",
                    expires_at=datetime(2026, 4, 13, 10, 0, tzinfo=UTC),
                    draft_plan=draft_plan,
                ).model_dump(mode="json")
            },
        )

        with patch(
            "src.app.domain.services.handlers.plan_day.persist_day_plan_artifact",
            new_callable=AsyncMock,
            return_value="artifact-1",
        ):
            result = await handle_plan_day(message, AsyncMock(), AsyncMock(), _make_intent())

        assert result.metadata["day_plan_artifact_id"] == "artifact-1"
        assert result.metadata["pending_planning_session_cleared"] is True
        assert "Locked in for today" in result.content

    async def test_evening_closeout_session_persists_reviewed_plan(self):
        """Evening closeout should store a reviewed plan and clear the session."""
        current_plan = DayPlanArtifact(
            source_date="2026-04-13",
            status="active",
            plan_summary="Close the loop on launch work.",
            tasks=[
                DayPlanTask(title="Finish launch checklist"),
                DayPlanTask(title="Reply to Alice"),
            ],
        )
        message = MessageInput(
            content="Checklist is done. Move Alice to tomorrow.",
            source="test",
            user_id="user-1",
            metadata={
                "pending_planning_session": PendingPlanningSession(
                    session_type="evening_review",
                    source_date="2026-04-13",
                    stage="collecting",
                    expires_at=datetime(2026, 4, 13, 22, 0, tzinfo=UTC),
                    plan_artifact_id="artifact-0",
                    unresolved_tasks=["Finish launch checklist", "Reply to Alice"],
                ).model_dump(mode="json")
            },
        )

        with (
            patch(
                "src.app.domain.services.handlers.plan_day.load_latest_day_plan",
                new_callable=AsyncMock,
                return_value=StoredDayPlan(
                    artifact_id="artifact-0",
                    created_at=datetime(2026, 4, 13, 8, 0, tzinfo=UTC),
                    plan=current_plan,
                ),
            ),
            patch(
                "src.app.domain.services.handlers.plan_day.call_and_parse",
                new_callable=AsyncMock,
                return_value=EveningCloseoutTurn(
                    outcome="review_complete",
                    assistant_reply="Closed. I moved Alice to tomorrow.",
                    summary="Checklist done, Alice moved to tomorrow.",
                    tasks=[
                        EveningCloseoutTask(
                            title="Finish launch checklist",
                            status="completed",
                        ),
                        EveningCloseoutTask(
                            title="Reply to Alice",
                            status="moved_to_day",
                            rescheduled_for="2026-04-14",
                        ),
                    ],
                ),
            ),
            patch(
                "src.app.domain.services.handlers.plan_day.persist_day_plan_artifact",
                new_callable=AsyncMock,
                return_value="artifact-1",
            ),
        ):
            result = await handle_plan_day(message, AsyncMock(), AsyncMock(), _make_intent())

        assert result.metadata["day_plan_artifact_id"] == "artifact-1"
        assert result.metadata["pending_planning_session_cleared"] is True
        assert "moved Alice to tomorrow" in result.content


class TestPlanDayFetchHelpers:
    async def test_fetch_commitments_raises_on_query_failure(self):
        """Commitment helper re-raises database failures after logging."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("db boom"))

        with (
            patch("src.app.domain.services.handlers.plan_day.logger") as mock_logger,
            pytest.raises(RuntimeError, match="db boom"),
        ):
            await _fetch_commitments(mock_session)

        mock_logger.exception.assert_called_once_with("plan_day_commitments_fetch_failed")

    async def test_fetch_goals_raises_on_query_failure(self):
        """Goals helper re-raises database failures after logging."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("db boom"))

        with (
            patch("src.app.domain.services.handlers.plan_day.logger") as mock_logger,
            pytest.raises(RuntimeError, match="db boom"),
        ):
            await _fetch_goals(mock_session)

        mock_logger.exception.assert_called_once_with("plan_day_goals_fetch_failed")

    async def test_fetch_tasks_raises_on_query_failure(self):
        """Tasks helper re-raises database failures after logging."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("db boom"))

        with (
            patch("src.app.domain.services.handlers.plan_day.logger") as mock_logger,
            pytest.raises(RuntimeError, match="db boom"),
        ):
            await _fetch_tasks(mock_session)

        mock_logger.exception.assert_called_once_with("plan_day_tasks_fetch_failed")
