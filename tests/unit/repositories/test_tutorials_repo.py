"""Tests for the tutorials repository — CRUD for Socratic tutorial sessions."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.persistence.models import TutorialSession
from src.app.persistence.repositories.tutorials import (
    create_tutorial_session,
    get_active_tutorial,
    get_past_tutorials,
    get_tutorial_session,
    store_preparation,
    store_tutorial_results,
    update_tutorial_phase,
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
    session.get = AsyncMock()
    session.execute = AsyncMock()
    return session


def _make_tutorial(**overrides) -> TutorialSession:
    """Create a test TutorialSession ORM object."""
    t = TutorialSession()
    t.id = overrides.get("id", uuid.uuid4())
    t.user_id = overrides.get("user_id", "user-1")
    t.topic = overrides.get("topic", "Caching strategies")
    t.work_type = overrides.get("work_type", "essay")
    t.submitted_work = overrides.get("submitted_work", "My essay about caching.")
    t.phase = overrides.get("phase", "submitted")
    t.propositions = overrides.get("propositions")
    t.preparation = overrides.get("preparation")
    t.transcript = overrides.get("transcript")
    t.assessor_log = overrides.get("assessor_log")
    t.analysis = overrides.get("analysis")
    t.bloom_start = overrides.get("bloom_start")
    t.bloom_end = overrides.get("bloom_end")
    t.turn_count = overrides.get("turn_count")
    t.speaking_ratio_student_pct = overrides.get("speaking_ratio_student_pct")
    t.knowledge_gaps_found = overrides.get("knowledge_gaps_found")
    t.knowledge_gaps_addressed = overrides.get("knowledge_gaps_addressed")
    t.created_at = overrides.get("created_at", datetime.now(UTC))
    t.completed_at = overrides.get("completed_at")
    return t


# ---------------------------------------------------------------------------
# create_tutorial_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_tutorial_session_adds_and_flushes():
    """create_tutorial_session calls session.add() and session.flush()."""
    session = _make_session()

    result = await create_tutorial_session(
        session,
        user_id="user-1",
        topic="Caching",
        submitted_work="My essay...",
        work_type="essay",
    )

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert isinstance(result, TutorialSession)


@pytest.mark.asyncio
async def test_create_tutorial_session_sets_fields():
    """create_tutorial_session sets all provided fields."""
    session = _make_session()

    result = await create_tutorial_session(
        session,
        user_id="user-42",
        topic="Microservices",
        submitted_work="An argument about microservices.",
        work_type="argument",
    )

    assert result.user_id == "user-42"
    assert result.topic == "Microservices"
    assert result.submitted_work == "An argument about microservices."
    assert result.work_type == "argument"
    assert result.phase == "submitted"


@pytest.mark.asyncio
async def test_create_tutorial_session_defaults_work_type():
    """create_tutorial_session defaults work_type to 'other'."""
    session = _make_session()

    result = await create_tutorial_session(
        session,
        user_id="user-1",
        topic="Topic",
        submitted_work="Content",
    )

    assert result.work_type == "other"


# ---------------------------------------------------------------------------
# get_tutorial_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tutorial_session_found():
    """get_tutorial_session returns the tutorial when it exists."""
    session = _make_session()
    tutorial = _make_tutorial(topic="Found")
    session.get.return_value = tutorial

    result = await get_tutorial_session(session, tutorial.id)

    session.get.assert_awaited_once_with(TutorialSession, tutorial.id)
    assert result is tutorial


@pytest.mark.asyncio
async def test_get_tutorial_session_not_found():
    """get_tutorial_session returns None when tutorial doesn't exist."""
    session = _make_session()
    session.get.return_value = None

    result = await get_tutorial_session(session, uuid.uuid4())

    assert result is None


# ---------------------------------------------------------------------------
# get_active_tutorial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_tutorial_found():
    """get_active_tutorial returns the user's active tutorial."""
    session = _make_session()
    tutorial = _make_tutorial(phase="dialogue")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = tutorial
    session.execute.return_value = mock_result

    result = await get_active_tutorial(session, "user-1")

    session.execute.assert_awaited_once()
    assert result is tutorial


@pytest.mark.asyncio
async def test_get_active_tutorial_none():
    """get_active_tutorial returns None when no active tutorial."""
    session = _make_session()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    result = await get_active_tutorial(session, "user-1")

    assert result is None


# ---------------------------------------------------------------------------
# update_tutorial_phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_tutorial_phase():
    """update_tutorial_phase executes the update statement."""
    session = _make_session()
    tid = uuid.uuid4()

    await update_tutorial_phase(session, tid, "ready")

    session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# store_preparation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_preparation():
    """store_preparation updates propositions, preparation, and phase."""
    session = _make_session()
    tid = uuid.uuid4()
    props = [{"index": 0, "text": "Claim 1"}]
    prep = {
        "tutor_prep": {"opening_question": "Explain."},
        "devils_advocate_prep": {},
        "clarifier_prep": {},
        "connector_prep": {},
    }

    await store_preparation(session, tid, propositions=props, preparation=prep)

    session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# store_tutorial_results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_tutorial_results():
    """store_tutorial_results stores transcript, analysis, and metrics."""
    session = _make_session()
    tid = uuid.uuid4()

    await store_tutorial_results(
        session,
        tid,
        transcript=[{"role": "tutor", "content": "Question?"}],
        assessor_log=[{"action": "tutor", "reasoning": "test"}],
        analysis={"summary": "Good session."},
        turn_count=5,
        speaking_ratio_student_pct=72.0,
        bloom_start="understand",
        bloom_end="analyse",
        knowledge_gaps_found=3,
        knowledge_gaps_addressed=2,
    )

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_store_tutorial_results_with_defaults():
    """store_tutorial_results works with minimal required args."""
    session = _make_session()
    tid = uuid.uuid4()

    await store_tutorial_results(
        session,
        tid,
        transcript=[],
        assessor_log=[],
        analysis={},
        turn_count=0,
    )

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_store_tutorial_results_logs_validation_failures():
    """Invalid transcript, assessor log, and analysis payloads should warn but still persist."""
    session = _make_session()
    tid = uuid.uuid4()

    with patch("src.app.persistence.repositories.tutorials.logger.warning") as mock_warning:
        await store_tutorial_results(
            session,
            tid,
            transcript=[{"role": "tutor"}],  # missing content
            assessor_log=[{"turn": "nope"}],
            analysis={"engagement_metrics": []},
            turn_count=1,
        )

    session.execute.assert_awaited_once()
    assert mock_warning.call_count == 3


# ---------------------------------------------------------------------------
# get_past_tutorials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_past_tutorials_returns_list():
    """get_past_tutorials returns a list of completed tutorials."""
    session = _make_session()
    tutorials = [
        _make_tutorial(phase="complete", topic="Tutorial A"),
        _make_tutorial(phase="complete", topic="Tutorial B"),
    ]

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = tutorials
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await get_past_tutorials(session, "user-1")

    assert len(result) == 2
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_past_tutorials_empty():
    """get_past_tutorials returns empty list when no completed tutorials."""
    session = _make_session()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await get_past_tutorials(session, "user-1")

    assert result == []


@pytest.mark.asyncio
async def test_get_past_tutorials_respects_limit():
    """get_past_tutorials passes the limit parameter."""
    session = _make_session()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    await get_past_tutorials(session, "user-1", limit=5)

    session.execute.assert_awaited_once()
