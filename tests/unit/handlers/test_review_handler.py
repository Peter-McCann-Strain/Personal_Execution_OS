"""Tests for review handler — weekly and quarterly reviews."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.specialists.review import (
    PatternNoticed,
    Recommendation,
)
from src.app.domain.models import (
    ChatResponse,
    Intent,
    IntentType,
    MessageInput,
    Specialist,
)


def _make_message(content: str = "Give me my weekly review") -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _make_intent() -> Intent:
    return Intent(
        intent_type=IntentType.REVIEW,
        confidence=0.9,
        specialist=Specialist.REVIEW,
        reasoning="review request",
    )


def _make_weekly_review():
    """Build a mock WeeklyReview."""
    review = MagicMock()
    review.period = "2026-03-09 to 2026-03-16"
    review.key_insight = "Productivity peaked mid-week"
    review.mood_summary = "Generally positive with a dip on Wednesday"
    review.average_mood = 7.2
    review.accomplishments = ["Completed API migration", "Shipped new feature"]
    review.patterns_noticed = [
        PatternNoticed(pattern="Energy drops after lunch"),
        PatternNoticed(pattern="Best focus before 10am"),
    ]
    review.open_commitments = [
        {"action": "Reply to client email"},
        {"normalized_action": "Submit report"},
    ]
    review.recommendations = [
        Recommendation(action="Try afternoon walks"),
        Recommendation(action="Block focus time mornings"),
    ]
    return review


@pytest.mark.asyncio
async def test_handle_review_happy_path():
    """handle_review aggregates data and returns formatted weekly review."""
    message = _make_message()
    intent = _make_intent()
    review = _make_weekly_review()

    mock_session = AsyncMock()

    with (
        patch(
            "src.app.domain.services.handlers.review._aggregate_week_data",
            new_callable=AsyncMock,
            return_value="Week data text...",
        ) as mock_aggregate,
        patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ) as mock_generate,
    ):
        from src.app.domain.services.handlers.review import handle_review

        result = await handle_review(message, AsyncMock(), mock_session, intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "review"
    assert "Weekly Review" in result.content
    assert "2026-03-09 to 2026-03-16" in result.content
    assert "Productivity peaked mid-week" in result.content
    assert "Generally positive" in result.content
    assert "7.2" in result.content
    assert "Completed API migration" in result.content
    assert "Energy drops after lunch" in result.content
    assert "Reply to client email" in result.content
    assert "Try afternoon walks" in result.content
    assert result.metadata["period"] == "2026-03-09 to 2026-03-16"
    assert result.metadata["average_mood"] == 7.2
    assert result.metadata["accomplishment_count"] == 2
    assert result.metadata["recommendation_count"] == 2
    mock_aggregate.assert_awaited_once_with(mock_session)
    mock_generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_review_minimal_data():
    """handle_review handles a review with minimal/empty fields."""
    message = _make_message()
    intent = _make_intent()

    review = MagicMock()
    review.period = "2026-03-09 to 2026-03-16"
    review.key_insight = None
    review.mood_summary = None
    review.average_mood = None
    review.accomplishments = []
    review.patterns_noticed = []
    review.open_commitments = []
    review.recommendations = []

    with (
        patch(
            "src.app.domain.services.handlers.review._aggregate_week_data",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ),
    ):
        from src.app.domain.services.handlers.review import handle_review

        result = await handle_review(message, AsyncMock(), AsyncMock(), intent)

    assert result.agent == "review"
    assert "Weekly Review" in result.content
    assert result.metadata["accomplishment_count"] == 0
    assert result.metadata["recommendation_count"] == 0


@pytest.mark.asyncio
async def test_handle_review_llm_failure_propagates():
    """handle_review propagates LLM errors from generate_weekly_review."""
    message = _make_message()
    intent = _make_intent()

    with (
        patch(
            "src.app.domain.services.handlers.review._aggregate_week_data",
            new_callable=AsyncMock,
            return_value="Week data",
        ),
        patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Opus unavailable"),
        ),
        pytest.raises(RuntimeError, match="Opus unavailable"),
    ):
        from src.app.domain.services.handlers.review import handle_review

        await handle_review(message, AsyncMock(), AsyncMock(), intent)


@pytest.mark.asyncio
async def test_handle_review_db_failure_propagates():
    """handle_review propagates database errors from _aggregate_week_data."""
    message = _make_message()
    intent = _make_intent()

    with (
        patch(
            "src.app.domain.services.handlers.review._aggregate_week_data",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB connection lost"),
        ),
        pytest.raises(RuntimeError, match="DB connection lost"),
    ):
        from src.app.domain.services.handlers.review import handle_review

        await handle_review(message, AsyncMock(), AsyncMock(), intent)


@pytest.mark.asyncio
async def test_handle_review_open_commitments_format():
    """handle_review formats open commitments with both 'action' and 'normalized_action' keys."""
    message = _make_message()
    intent = _make_intent()
    review = _make_weekly_review()

    with (
        patch(
            "src.app.domain.services.handlers.review._aggregate_week_data",
            new_callable=AsyncMock,
            return_value="data",
        ),
        patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ),
    ):
        from src.app.domain.services.handlers.review import handle_review

        result = await handle_review(message, AsyncMock(), AsyncMock(), intent)

    # Both commitment formats should appear
    assert "Reply to client email" in result.content
    assert "Submit report" in result.content
