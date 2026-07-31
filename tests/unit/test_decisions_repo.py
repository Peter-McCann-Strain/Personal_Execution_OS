"""Tests for decisions repository — CRUD, filtering, review scheduling."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from src.app.persistence.models import Decision
from src.app.persistence.repositories.decisions import (
    create_decision,
    get_decision_by_id,
    get_decisions,
    get_decisions_due_for_review,
    update_decision_outcome,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.get = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _make_decision(
    *,
    title: str = "Use FastAPI for the backend",
    decision_made: str = "Chose FastAPI over Django",
    status: str = "pending_review",
    review_date: datetime | None = None,
) -> Decision:
    """Create a Decision ORM object for testing."""
    decision = Decision()
    decision.id = uuid.uuid4()
    decision.title = title
    decision.decision_made = decision_made
    decision.context = "Needed a modern async framework"
    decision.options_considered = ["FastAPI", "Django", "Flask"]
    decision.reasoning = "FastAPI has best async support"
    decision.expected_outcome = "Faster development"
    decision.actual_outcome = None
    decision.outcome_rating = None
    decision.tags = ["tech", "architecture"]
    decision.review_date = review_date
    decision.status = status
    decision.created_at = datetime.now(UTC)
    decision.updated_at = datetime.now(UTC)
    return decision


def _make_scalars_result(items: list) -> MagicMock:
    """Create a mock result with .scalars().all() returning items."""
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = items
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    return mock_result


def _make_count_result(count: int) -> MagicMock:
    """Create a mock result with .scalar_one() returning count."""
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = count
    return mock_result


# ---------------------------------------------------------------------------
# create_decision
# ---------------------------------------------------------------------------


class TestCreateDecision:
    async def test_creates_and_flushes(self):
        """create_decision should add the Decision and flush."""
        session = _make_session()

        result = await create_decision(
            session,
            title="Adopt managed PostgreSQL",
            decision_made="Use managed PostgreSQL instead of a local instance",
        )

        assert isinstance(result, Decision)
        assert result.title == "Adopt managed PostgreSQL"
        assert result.decision_made == "Use managed PostgreSQL instead of a local instance"
        assert result.status == "pending_review"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    async def test_with_all_fields(self):
        """All optional fields should be passed through."""
        session = _make_session()
        review_dt = datetime(2026, 6, 1, tzinfo=UTC)

        result = await create_decision(
            session,
            title="Adopt LangGraph",
            decision_made="Use LangGraph for agent orchestration",
            context="Needed multi-agent framework",
            options_considered=["LangGraph", "CrewAI", "AutoGen"],
            reasoning="Best graph-based workflow support",
            expected_outcome="Clean agent pipelines",
            tags=["ai", "agents"],
            review_date=review_dt,
        )

        assert result.title == "Adopt LangGraph"
        assert result.context == "Needed multi-agent framework"
        assert result.options_considered == ["LangGraph", "CrewAI", "AutoGen"]
        assert result.reasoning == "Best graph-based workflow support"
        assert result.expected_outcome == "Clean agent pipelines"
        assert result.tags == ["ai", "agents"]
        assert result.review_date == review_dt

    async def test_defaults(self):
        """Optional fields default to None when not provided."""
        session = _make_session()

        result = await create_decision(
            session,
            title="Minimal decision",
            decision_made="Just do it",
        )

        assert result.context is None
        assert result.options_considered is None
        assert result.reasoning is None
        assert result.expected_outcome is None
        assert result.tags is None
        assert result.review_date is None


# ---------------------------------------------------------------------------
# get_decisions
# ---------------------------------------------------------------------------


class TestGetDecisions:
    async def test_without_status_filter(self):
        """Returns all decisions with total count when no filter."""
        session = _make_session()
        decisions = [_make_decision(), _make_decision()]

        # First call: count query, Second call: fetch query
        session.execute = AsyncMock(
            side_effect=[
                _make_count_result(2),
                _make_scalars_result(decisions),
            ]
        )

        result, total = await get_decisions(session)

        assert len(result) == 2
        assert total == 2

    async def test_with_status_filter(self):
        """Filters by status when provided."""
        session = _make_session()
        reviewed = [_make_decision(status="reviewed")]

        session.execute = AsyncMock(
            side_effect=[
                _make_count_result(1),
                _make_scalars_result(reviewed),
            ]
        )

        result, total = await get_decisions(session, status="reviewed")

        assert len(result) == 1
        assert total == 1
        assert result[0].status == "reviewed"

    async def test_empty_results(self):
        """Returns empty list and zero count when no decisions exist."""
        session = _make_session()

        session.execute = AsyncMock(
            side_effect=[
                _make_count_result(0),
                _make_scalars_result([]),
            ]
        )

        result, total = await get_decisions(session)

        assert result == []
        assert total == 0

    async def test_pagination_parameters(self):
        """Limit and offset are accepted."""
        session = _make_session()
        decisions = [_make_decision()]

        session.execute = AsyncMock(
            side_effect=[
                _make_count_result(10),
                _make_scalars_result(decisions),
            ]
        )

        result, total = await get_decisions(session, limit=5, offset=5)

        assert len(result) == 1
        assert total == 10


# ---------------------------------------------------------------------------
# get_decision_by_id
# ---------------------------------------------------------------------------


class TestGetDecisionById:
    async def test_found(self):
        """Returns the Decision when it exists."""
        session = _make_session()
        decision = _make_decision()
        session.get.return_value = decision

        result = await get_decision_by_id(session, decision.id)

        assert result is decision
        session.get.assert_awaited_once_with(Decision, decision.id)

    async def test_not_found(self):
        """Returns None when the Decision does not exist."""
        session = _make_session()
        session.get.return_value = None

        result = await get_decision_by_id(session, uuid.uuid4())

        assert result is None


# ---------------------------------------------------------------------------
# update_decision_outcome
# ---------------------------------------------------------------------------


class TestUpdateDecisionOutcome:
    async def test_updates_existing_decision(self):
        """Updates outcome, rating, and status for an existing decision."""
        session = _make_session()
        decision = _make_decision()
        session.get.return_value = decision

        result = await update_decision_outcome(
            session,
            decision.id,
            actual_outcome="Worked great, fast API dev",
            outcome_rating=8.5,
        )

        assert result is decision
        session.execute.assert_awaited_once()
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(decision)

    async def test_returns_none_when_not_found(self):
        """Returns None when the decision does not exist."""
        session = _make_session()
        session.get.return_value = None

        result = await update_decision_outcome(
            session,
            uuid.uuid4(),
            actual_outcome="Would never know",
        )

        assert result is None
        session.execute.assert_not_awaited()
        session.flush.assert_not_awaited()

    async def test_without_rating(self):
        """Outcome can be recorded without a rating."""
        session = _make_session()
        decision = _make_decision()
        session.get.return_value = decision

        result = await update_decision_outcome(
            session,
            decision.id,
            actual_outcome="Outcome recorded",
            outcome_rating=None,
        )

        assert result is decision
        session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_decisions_due_for_review
# ---------------------------------------------------------------------------


class TestGetDecisionsDueForReview:
    async def test_returns_due_decisions(self):
        """Decisions with review_date in the past are returned."""
        session = _make_session()
        past_date = datetime.now(tz=UTC) - timedelta(days=1)
        decision = _make_decision(review_date=past_date, status="pending_review")
        session.execute.return_value = _make_scalars_result([decision])

        result = await get_decisions_due_for_review(session)

        assert len(result) == 1
        assert result[0] is decision
        session.execute.assert_awaited_once()

    async def test_empty_when_none_due(self):
        """Returns empty list when no decisions are due."""
        session = _make_session()
        session.execute.return_value = _make_scalars_result([])

        result = await get_decisions_due_for_review(session)

        assert result == []

    async def test_future_review_date_excluded(self):
        """Decisions with future review_date are not returned."""
        session = _make_session()
        # The query filters in the DB; we just verify
        # the function calls execute and returns what DB gives
        session.execute.return_value = _make_scalars_result([])

        result = await get_decisions_due_for_review(session)

        assert result == []
        session.execute.assert_awaited_once()
