"""Tests for recency-weighted retrieval with access boosting.

Covers:
- record_episode_access / record_note_access with mock session
- Decay factor calculation (pure math verification)
- Access boost calculation (pure math verification)
"""

import math
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.persistence.repositories.episodes import record_episode_access
from src.app.persistence.repositories.notes import record_note_access

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    return session


def recency_boost(days_old: float, decay_rate: float = 0.01) -> float:
    """Pure-function equivalent of the SQL recency decay calculation.

    recency_boost = 1.0 / (1.0 + days_old * decay_rate)
    """
    return 1.0 / (1.0 + days_old * decay_rate)


def access_boost(access_count: int) -> float:
    """Pure-function equivalent of the SQL access boost calculation.

    access_boost = 1.0 + LN(1 + access_count) * 0.1
    """
    return 1.0 + math.log(1 + access_count) * 0.1


# ---------------------------------------------------------------------------
# record_episode_access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_episode_access_updates_session():
    """record_episode_access should execute an UPDATE on the session."""
    session = _make_session()
    ids = [uuid.uuid4(), uuid.uuid4()]

    await record_episode_access(session, ids)

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_episode_access_empty_list_skips():
    """record_episode_access with empty list should not execute anything."""
    session = _make_session()

    await record_episode_access(session, [])

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_episode_access_single_id():
    """record_episode_access should work with a single episode ID."""
    session = _make_session()
    ids = [uuid.uuid4()]

    await record_episode_access(session, ids)

    session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# record_note_access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_note_access_updates_session():
    """record_note_access should execute an UPDATE on the session."""
    session = _make_session()
    ids = [uuid.uuid4(), uuid.uuid4()]

    await record_note_access(session, ids)

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_note_access_empty_list_skips():
    """record_note_access with empty list should not execute anything."""
    session = _make_session()

    await record_note_access(session, [])

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_note_access_single_id():
    """record_note_access should work with a single note ID."""
    session = _make_session()
    ids = [uuid.uuid4()]

    await record_note_access(session, ids)

    session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Decay factor calculation (pure function tests)
# ---------------------------------------------------------------------------


def test_recency_boost_zero_days():
    """A brand-new item (0 days old) should have recency_boost = 1.0."""
    assert recency_boost(0.0) == 1.0


def test_recency_boost_one_day():
    """An item 1 day old should have a slightly reduced boost."""
    boost = recency_boost(1.0, decay_rate=0.01)
    assert boost == pytest.approx(1.0 / 1.01)


def test_recency_boost_100_days():
    """An item 100 days old should have recency_boost = 1/(1 + 1.0) = 0.5."""
    boost = recency_boost(100.0, decay_rate=0.01)
    assert boost == pytest.approx(0.5)


def test_recency_boost_365_days():
    """An item 1 year old should still have a meaningful boost (slow decay)."""
    boost = recency_boost(365.0, decay_rate=0.01)
    assert boost == pytest.approx(1.0 / 4.65)
    # With decay_rate=0.01, a year-old item retains ~21% of its score


def test_recency_boost_fast_decay():
    """With decay_rate=0.1, items decay 10x faster."""
    boost = recency_boost(10.0, decay_rate=0.1)
    assert boost == pytest.approx(0.5)


def test_recency_boost_always_positive():
    """Recency boost should always be > 0 (items never fully disappear)."""
    for days in [0, 1, 10, 100, 1000, 10000]:
        assert recency_boost(float(days)) > 0


def test_recency_boost_monotonically_decreasing():
    """Older items should always have lower boosts than newer items."""
    boosts = [recency_boost(float(d)) for d in range(0, 365, 30)]
    for i in range(len(boosts) - 1):
        assert boosts[i] > boosts[i + 1]


# ---------------------------------------------------------------------------
# Access boost calculation (pure function tests)
# ---------------------------------------------------------------------------


def test_access_boost_zero_accesses():
    """An item never accessed should have access_boost = 1.0 + LN(1)*0.1 = 1.0."""
    assert access_boost(0) == pytest.approx(1.0)


def test_access_boost_one_access():
    """An item accessed once should have a small boost."""
    boost = access_boost(1)
    expected = 1.0 + math.log(2) * 0.1
    assert boost == pytest.approx(expected)


def test_access_boost_ten_accesses():
    """An item accessed 10 times should have a moderate boost."""
    boost = access_boost(10)
    expected = 1.0 + math.log(11) * 0.1
    assert boost == pytest.approx(expected)


def test_access_boost_100_accesses():
    """An item accessed 100 times should have a significant but bounded boost."""
    boost = access_boost(100)
    expected = 1.0 + math.log(101) * 0.1
    assert boost == pytest.approx(expected)
    # Should be roughly 1.46 — logarithmic growth prevents runaway boosting
    assert 1.4 < boost < 1.5


def test_access_boost_monotonically_increasing():
    """More accesses should always produce higher boosts."""
    boosts = [access_boost(n) for n in range(0, 100, 10)]
    for i in range(len(boosts) - 1):
        assert boosts[i] < boosts[i + 1]


def test_access_boost_always_at_least_one():
    """Access boost should never go below 1.0 (no penalty for access)."""
    for n in [0, 1, 5, 10, 50, 100]:
        assert access_boost(n) >= 1.0


# ---------------------------------------------------------------------------
# Combined score calculation
# ---------------------------------------------------------------------------


def test_combined_score_new_unaccessed():
    """A brand-new, never-accessed item should have combined multiplier = 1.0."""
    combined = recency_boost(0.0) * access_boost(0)
    assert combined == pytest.approx(1.0)


def test_combined_score_old_frequently_accessed():
    """An old but frequently accessed item should be partially rescued by access."""
    decay = recency_boost(365.0, decay_rate=0.01)
    access = access_boost(50)
    combined = decay * access
    # 365 days old with 50 accesses: decay ~0.215, access ~1.39
    # Combined ~0.30 — still meaningful, not lost
    assert combined > 0.25
    assert combined < 0.40


def test_combined_score_new_frequently_accessed():
    """A new, frequently accessed item should score highest."""
    decay = recency_boost(1.0, decay_rate=0.01)
    access = access_boost(20)
    combined = decay * access
    # 1 day old with 20 accesses: decay ~0.99, access ~1.30
    assert combined > 1.25
