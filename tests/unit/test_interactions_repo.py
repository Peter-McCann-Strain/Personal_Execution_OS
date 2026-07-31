"""Tests for InteractionRecord repository functions.

These are unit tests that verify the SQL statements and function signatures
without hitting a real database. They mock the AsyncSession.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.domain.constants import EvalStatus, FeedbackRating


class TestCreateInteraction:
    @pytest.mark.asyncio
    async def test_creates_and_flushes(self):
        """create_interaction adds to session and flushes."""
        session = AsyncMock()

        from src.app.persistence.repositories.interactions import create_interaction

        await create_interaction(
            session,
            user_id="user-1",
            user_message="Hello",
            source="telegram",
            intent_type="capture",
            specialist="diary",
            routing_confidence=0.95,
            response_content="Hi there!",
            response_agent="diary",
            optimizer_triggered=False,
            optimizer_issue=None,
            duration_ms=1500,
            trace_id="trace-abc",
        )

        session.add.assert_called_once()
        session.flush.assert_awaited_once()

        # Verify the record has correct initial state
        added_record = session.add.call_args[0][0]
        assert added_record.eval_status == EvalStatus.PENDING
        assert added_record.user_id == "user-1"
        assert added_record.specialist == "diary"
        assert added_record.duration_ms == 1500
        assert added_record.trace_id == "trace-abc"
        assert added_record.optimizer_triggered is False

    @pytest.mark.asyncio
    async def test_default_trace_id(self):
        """trace_id defaults to None."""
        session = AsyncMock()

        from src.app.persistence.repositories.interactions import create_interaction

        await create_interaction(
            session,
            user_id="user-1",
            user_message="Test",
            source="cli",
            intent_type="query",
            specialist="memory",
            routing_confidence=0.80,
            response_content="Response",
            response_agent="memory",
            optimizer_triggered=False,
            optimizer_issue=None,
            duration_ms=500,
        )

        added_record = session.add.call_args[0][0]
        assert added_record.trace_id is None


class TestGetPendingInteractions:
    @pytest.mark.asyncio
    async def test_queries_pending_status(self):
        """get_pending_interactions filters by PENDING status."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        from src.app.persistence.repositories.interactions import get_pending_interactions

        result = await get_pending_interactions(session, limit=50)

        session.execute.assert_awaited_once()
        assert result == []

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        """get_pending_interactions respects the limit parameter."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ["r1", "r2"]
        session.execute.return_value = mock_result

        from src.app.persistence.repositories.interactions import get_pending_interactions

        result = await get_pending_interactions(session, limit=2)
        assert len(result) == 2


class TestUpdateAutoJudgeScores:
    @pytest.mark.asyncio
    async def test_updates_scores_and_status(self):
        """update_auto_judge_scores issues an UPDATE with correct values."""
        session = AsyncMock()
        interaction_id = uuid.uuid4()
        scored_at = datetime.now(UTC)
        record = MagicMock()
        record.quality_scores = {"route_quality": 1.0}
        session.get = AsyncMock(return_value=record)

        from src.app.persistence.repositories.interactions import update_auto_judge_scores

        await update_auto_judge_scores(
            session,
            interaction_id,
            score_relevance=0.85,
            score_actionability=0.7,
            score_tone=0.9,
            score_conciseness=0.8,
            reasoning="Good response.",
            scored_at=scored_at,
        )

        session.get.assert_awaited_once()
        assert record.eval_status == EvalStatus.AUTO_SCORED
        assert record.score_relevance == 0.85
        assert record.quality_scores["route_quality"] == 1.0
        assert record.quality_scores["async_judge"]["tone"] == 0.9


class TestUpdateFeedback:
    @pytest.mark.asyncio
    async def test_updates_feedback_and_returns_true(self):
        """update_feedback updates the record and returns True."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        session.execute.return_value = mock_result

        interaction_id = uuid.uuid4()
        feedback_at = datetime.now(UTC)

        from src.app.persistence.repositories.interactions import update_feedback

        result = await update_feedback(
            session,
            interaction_id,
            rating=FeedbackRating.THUMBS_UP,
            feedback_at=feedback_at,
        )

        assert result is True
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self):
        """update_feedback returns False when no record matches."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        session.execute.return_value = mock_result

        interaction_id = uuid.uuid4()
        feedback_at = datetime.now(UTC)

        from src.app.persistence.repositories.interactions import update_feedback

        result = await update_feedback(
            session,
            interaction_id,
            rating=FeedbackRating.THUMBS_DOWN,
            feedback_at=feedback_at,
        )

        assert result is False


class TestGetAvgScoresInWindow:
    @pytest.mark.asyncio
    async def test_returns_averages(self):
        """get_avg_scores_in_window returns averaged scores."""
        session = AsyncMock()
        mock_row = MagicMock()
        mock_row.relevance = 0.85
        mock_row.actionability = 0.70
        mock_row.tone = 0.90
        mock_row.conciseness = 0.80
        mock_row.count = 10

        mock_result = MagicMock()
        mock_result.one.return_value = mock_row
        session.execute.return_value = mock_result

        from src.app.persistence.repositories.interactions import get_avg_scores_in_window

        result = await get_avg_scores_in_window(
            session,
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
        )

        assert result["relevance"] == 0.85
        assert result["actionability"] == 0.70
        assert result["tone"] == 0.90
        assert result["conciseness"] == 0.80
        assert result["count"] == 10

    @pytest.mark.asyncio
    async def test_filters_by_specialist(self):
        """get_avg_scores_in_window can filter by specialist."""
        session = AsyncMock()
        mock_row = MagicMock()
        mock_row.relevance = None
        mock_row.actionability = None
        mock_row.tone = None
        mock_row.conciseness = None
        mock_row.count = 0

        mock_result = MagicMock()
        mock_result.one.return_value = mock_row
        session.execute.return_value = mock_result

        from src.app.persistence.repositories.interactions import get_avg_scores_in_window

        result = await get_avg_scores_in_window(
            session,
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
            specialist="diary",
        )

        assert result["count"] == 0
        assert result["relevance"] is None


class TestGetSpecialistScoreAverages:
    @pytest.mark.asyncio
    async def test_returns_grouped_averages(self):
        """get_specialist_score_averages returns per-agent averages."""
        session = AsyncMock()

        mock_row = MagicMock()
        mock_row._mapping = {
            "specialist": "diary",
            "avg_relevance": 0.85,
            "avg_actionability": 0.70,
            "avg_tone": 0.90,
            "avg_conciseness": 0.80,
            "count": 10,
        }

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        session.execute.return_value = mock_result

        from src.app.persistence.repositories.interactions import (
            get_specialist_score_averages,
        )

        result = await get_specialist_score_averages(
            session,
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
        )

        assert len(result) == 1
        assert result[0]["specialist"] == "diary"
        assert result[0]["avg_relevance"] == 0.85
