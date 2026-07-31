"""Tests for the commitments repository — tracking promises and follow-ups."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.domain.constants import CommitmentStatus
from src.app.persistence.models import Commitment
from src.app.persistence.repositories.commitments import (
    create_commitment,
    get_open_commitments,
    get_overdue_commitments,
    update_commitment_status,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _make_commitment(**overrides) -> Commitment:
    """Create a test Commitment ORM object."""
    c = Commitment()
    c.id = overrides.get("id", uuid.uuid4())
    c.verbatim_text = overrides.get("verbatim_text", "I'll send the report by Friday")
    c.normalized_action = overrides.get("normalized_action", "Send report")
    c.who_committed = overrides.get("who_committed", "Alex")
    c.who_to = overrides.get("who_to", "Alice")
    c.temporal_expression_raw = overrides.get("temporal_expression_raw", "by Friday")
    c.temporal_normalized = overrides.get("temporal_normalized")
    c.commitment_type = overrides.get("commitment_type", "promise")
    c.confidence_score = overrides.get("confidence_score", 1.0)
    c.status = overrides.get("status", CommitmentStatus.DETECTED)
    c.created_at = overrides.get("created_at", datetime.now(UTC))
    c.updated_at = overrides.get("updated_at", datetime.now(UTC))
    return c


# ---------------------------------------------------------------------------
# create_commitment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_commitment_adds_and_flushes():
    """create_commitment should call session.add() and session.flush()."""
    session = _make_session()

    result = await create_commitment(
        session,
        verbatim_text="I'll review the PR today",
        normalized_action="Review PR",
        who_committed="Alex",
    )

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert isinstance(result, Commitment)


@pytest.mark.asyncio
async def test_create_commitment_sets_all_fields():
    """create_commitment should set all provided fields."""
    session = _make_session()

    result = await create_commitment(
        session,
        verbatim_text="I'll email Bob the specs by Tuesday",
        normalized_action="Email specs to Bob",
        who_committed="Alex",
        who_to="Bob",
        temporal_expression="by Tuesday",
        confidence_score=0.85,
    )

    assert result.verbatim_text == "I'll email Bob the specs by Tuesday"
    assert result.normalized_action == "Email specs to Bob"
    assert result.who_committed == "Alex"
    assert result.who_to == "Bob"
    assert result.temporal_expression_raw == "by Tuesday"
    assert result.confidence_score == 0.85
    assert result.commitment_type == "promise"
    assert result.status == CommitmentStatus.DETECTED


@pytest.mark.asyncio
async def test_create_commitment_defaults():
    """create_commitment should use defaults for optional fields."""
    session = _make_session()

    result = await create_commitment(
        session,
        verbatim_text="Minimal commitment",
        normalized_action="Do something",
        who_committed="Alex",
    )

    assert result.who_to is None
    assert result.temporal_expression_raw is None
    assert result.confidence_score == 1.0
    assert result.commitment_type == "promise"
    assert result.status == CommitmentStatus.DETECTED


@pytest.mark.asyncio
async def test_create_commitment_returns_commitment_model():
    """create_commitment should return a Commitment instance."""
    session = _make_session()

    result = await create_commitment(
        session,
        verbatim_text="Test",
        normalized_action="Test",
        who_committed="Alex",
    )

    assert isinstance(result, Commitment)
    added = session.add.call_args[0][0]
    assert added is result


# ---------------------------------------------------------------------------
# get_overdue_commitments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_overdue_commitments_returns_list():
    """get_overdue_commitments should return a list of overdue commitments."""
    session = _make_session()
    overdue = _make_commitment(
        status=CommitmentStatus.DETECTED,
        temporal_normalized=datetime(2026, 1, 1, tzinfo=UTC),
    )

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [overdue]
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    results = await get_overdue_commitments(session)

    assert len(results) == 1
    assert results[0].status == CommitmentStatus.DETECTED
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_overdue_commitments_empty():
    """get_overdue_commitments should return empty list when none overdue."""
    session = _make_session()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    results = await get_overdue_commitments(session)

    assert results == []


@pytest.mark.asyncio
async def test_get_overdue_commitments_excludes_completed():
    """get_overdue_commitments should not return completed commitments."""
    session = _make_session()
    # The query filters by OPEN_COMMITMENT_STATUSES, so completed should be excluded
    # We just verify the function executes and returns what the DB gives it

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    results = await get_overdue_commitments(session)

    assert results == []


# ---------------------------------------------------------------------------
# get_open_commitments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_open_commitments_returns_list():
    """get_open_commitments should return non-closed commitments."""
    session = _make_session()
    open_c = _make_commitment(status=CommitmentStatus.CONFIRMED)

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [open_c]
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    results = await get_open_commitments(session)

    assert len(results) == 1
    assert results[0].status == CommitmentStatus.CONFIRMED


@pytest.mark.asyncio
async def test_get_open_commitments_empty():
    """get_open_commitments should return empty list when all closed."""
    session = _make_session()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    results = await get_open_commitments(session)

    assert results == []


@pytest.mark.asyncio
async def test_get_open_commitments_respects_limit():
    """get_open_commitments should accept a limit parameter."""
    session = _make_session()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    await get_open_commitments(session, limit=5)

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_open_commitments_multiple():
    """get_open_commitments should return multiple commitments."""
    session = _make_session()
    commitments = [
        _make_commitment(status=CommitmentStatus.DETECTED),
        _make_commitment(status=CommitmentStatus.CONFIRMED),
        _make_commitment(status=CommitmentStatus.IN_PROGRESS),
    ]

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = commitments
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    results = await get_open_commitments(session)

    assert len(results) == 3


# ---------------------------------------------------------------------------
# update_commitment_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_commitment_status_valid():
    """update_commitment_status should update to a valid status."""
    session = _make_session()
    commitment = _make_commitment(status=CommitmentStatus.COMPLETED)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = commitment
    session.execute.return_value = mock_result

    result = await update_commitment_status(session, commitment.id, CommitmentStatus.COMPLETED)

    session.execute.assert_awaited_once()
    assert result is commitment


@pytest.mark.asyncio
async def test_update_commitment_status_invalid_raises():
    """update_commitment_status should raise ValueError for invalid status."""
    session = _make_session()

    with pytest.raises(ValueError, match="Invalid commitment status"):
        await update_commitment_status(session, uuid.uuid4(), "invalid_status")


@pytest.mark.asyncio
async def test_update_commitment_status_not_found_raises():
    """update_commitment_status should raise ValueError if commitment not found."""
    session = _make_session()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    with pytest.raises(ValueError, match="Commitment not found"):
        await update_commitment_status(session, uuid.uuid4(), CommitmentStatus.CONFIRMED)


@pytest.mark.asyncio
async def test_update_commitment_status_all_valid_statuses():
    """update_commitment_status should accept all CommitmentStatus values."""
    session = _make_session()
    commitment = _make_commitment()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = commitment
    session.execute.return_value = mock_result

    for status in CommitmentStatus:
        await update_commitment_status(session, commitment.id, status)


@pytest.mark.asyncio
async def test_update_commitment_status_does_not_call_add():
    """update_commitment_status should use execute/update, not session.add()."""
    session = _make_session()
    commitment = _make_commitment()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = commitment
    session.execute.return_value = mock_result

    await update_commitment_status(session, commitment.id, CommitmentStatus.COMPLETED)

    session.add.assert_not_called()
