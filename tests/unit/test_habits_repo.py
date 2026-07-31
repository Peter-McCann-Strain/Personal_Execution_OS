"""Tests for habits repository — create, get, log, streaks, broken streaks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from src.app.persistence.models import Habit, HabitLog
from src.app.persistence.repositories.habits import (
    check_broken_streaks,
    create_habit,
    get_active_habits,
    get_habit_by_id,
    get_habit_logs,
    log_habit_completion,
    reset_streak,
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
    return session


def _make_habit(
    *,
    name: str = "Morning meditation",
    frequency: str = "daily",
    frequency_days: int = 1,
    current_streak: int = 0,
    longest_streak: int = 0,
    total_completions: int = 0,
    last_completed_at: datetime | None = None,
    active: bool = True,
) -> Habit:
    """Create a Habit ORM object for testing."""
    habit = Habit()
    habit.id = uuid.uuid4()
    habit.name = name
    habit.description = None
    habit.frequency = frequency
    habit.frequency_days = frequency_days
    habit.current_streak = current_streak
    habit.longest_streak = longest_streak
    habit.total_completions = total_completions
    habit.last_completed_at = last_completed_at
    habit.active = active
    habit.tags = None
    habit.created_at = datetime.now(UTC)
    habit.updated_at = datetime.now(UTC)
    return habit


def _make_scalars_result(items: list) -> MagicMock:
    """Create a mock result with .scalars().all() returning items."""
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = items
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    return mock_result


# ---------------------------------------------------------------------------
# create_habit
# ---------------------------------------------------------------------------


class TestCreateHabit:
    async def test_creates_and_flushes(self):
        """create_habit should add the Habit and flush the session."""
        session = _make_session()

        result = await create_habit(session, name="Exercise")

        assert isinstance(result, Habit)
        assert result.name == "Exercise"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    async def test_with_all_fields(self):
        """All optional fields should be passed through."""
        session = _make_session()

        result = await create_habit(
            session,
            name="Read",
            description="Read for 30 minutes",
            frequency="daily",
            frequency_days=1,
            tags=["learning", "habit"],
        )

        assert result.name == "Read"
        assert result.description == "Read for 30 minutes"
        assert result.frequency == "daily"
        assert result.frequency_days == 1
        assert result.tags == ["learning", "habit"]

    async def test_default_values(self):
        """Default frequency and frequency_days are applied."""
        session = _make_session()

        result = await create_habit(session, name="Stretch")

        assert result.frequency == "daily"
        assert result.frequency_days == 1
        assert result.description is None
        assert result.tags is None


# ---------------------------------------------------------------------------
# get_active_habits
# ---------------------------------------------------------------------------


class TestGetActiveHabits:
    async def test_returns_active_habits(self):
        """Should return list of active habits."""
        session = _make_session()
        habits = [_make_habit(name="A"), _make_habit(name="B")]
        session.execute.return_value = _make_scalars_result(habits)

        result = await get_active_habits(session)

        assert len(result) == 2
        assert result[0].name == "A"
        assert result[1].name == "B"
        session.execute.assert_awaited_once()

    async def test_returns_empty_list(self):
        """Should return empty list when no active habits exist."""
        session = _make_session()
        session.execute.return_value = _make_scalars_result([])

        result = await get_active_habits(session)

        assert result == []


# ---------------------------------------------------------------------------
# get_habit_by_id
# ---------------------------------------------------------------------------


class TestGetHabitById:
    async def test_found(self):
        """Returns the Habit when it exists."""
        session = _make_session()
        habit = _make_habit()
        session.get.return_value = habit

        result = await get_habit_by_id(session, habit.id)

        assert result is habit
        session.get.assert_awaited_once_with(Habit, habit.id)

    async def test_not_found(self):
        """Returns None when the Habit does not exist."""
        session = _make_session()
        session.get.return_value = None

        result = await get_habit_by_id(session, uuid.uuid4())

        assert result is None


# ---------------------------------------------------------------------------
# log_habit_completion
# ---------------------------------------------------------------------------


class TestLogHabitCompletion:
    async def test_first_completion_streak_zero_to_one(self):
        """First completion: streak goes from 0 to 1."""
        session = _make_session()
        habit = _make_habit(current_streak=0, longest_streak=0, total_completions=0)
        session.get.return_value = habit

        log = await log_habit_completion(session, habit_id=habit.id, note="Done!")

        assert isinstance(log, HabitLog)
        assert habit.current_streak == 1
        assert habit.longest_streak == 1
        assert habit.total_completions == 1
        assert habit.last_completed_at is not None
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    async def test_continuing_streak(self):
        """Continuing streak increments current_streak."""
        session = _make_session()
        habit = _make_habit(
            current_streak=5,
            longest_streak=10,
            total_completions=20,
        )
        session.get.return_value = habit

        await log_habit_completion(session, habit_id=habit.id)

        assert habit.current_streak == 6
        assert habit.total_completions == 21
        # longest_streak unchanged since 6 < 10
        assert habit.longest_streak == 10

    async def test_new_longest_streak(self):
        """When current_streak exceeds longest_streak, update it."""
        session = _make_session()
        habit = _make_habit(
            current_streak=9,
            longest_streak=9,
            total_completions=50,
        )
        session.get.return_value = habit

        await log_habit_completion(session, habit_id=habit.id)

        assert habit.current_streak == 10
        assert habit.longest_streak == 10
        assert habit.total_completions == 51

    async def test_habit_not_found(self):
        """When habit does not exist, log is still created but no streak update."""
        session = _make_session()
        session.get.return_value = None
        fake_id = uuid.uuid4()

        log = await log_habit_completion(session, habit_id=fake_id)

        assert isinstance(log, HabitLog)
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    async def test_custom_source(self):
        """Custom source is passed to the HabitLog."""
        session = _make_session()
        habit = _make_habit()
        session.get.return_value = habit

        log = await log_habit_completion(session, habit_id=habit.id, source="auto_detected")

        assert log.source == "auto_detected"


# ---------------------------------------------------------------------------
# check_broken_streaks
# ---------------------------------------------------------------------------


class TestCheckBrokenStreaks:
    async def test_returns_broken_habits(self):
        """Habits past their frequency deadline are returned."""
        old_time = datetime.now(tz=UTC) - timedelta(days=5)
        habit = _make_habit(
            current_streak=3,
            frequency_days=1,
            last_completed_at=old_time,
            active=True,
        )
        session = _make_session()
        session.execute.return_value = _make_scalars_result([habit])

        result = await check_broken_streaks(session)

        assert len(result) == 1
        assert result[0] is habit

    async def test_no_broken_streaks(self):
        """Habits completed recently are not returned."""
        recent_time = datetime.now(tz=UTC) - timedelta(hours=1)
        habit = _make_habit(
            current_streak=5,
            frequency_days=1,
            last_completed_at=recent_time,
            active=True,
        )
        session = _make_session()
        session.execute.return_value = _make_scalars_result([habit])

        result = await check_broken_streaks(session)

        assert len(result) == 0

    async def test_habit_without_last_completed_at(self):
        """Habits with None last_completed_at are not broken."""
        habit = _make_habit(
            current_streak=1,
            frequency_days=1,
            last_completed_at=None,
            active=True,
        )
        session = _make_session()
        session.execute.return_value = _make_scalars_result([habit])

        result = await check_broken_streaks(session)

        assert len(result) == 0

    async def test_empty_active_habits(self):
        """No active habits with streaks returns empty."""
        session = _make_session()
        session.execute.return_value = _make_scalars_result([])

        result = await check_broken_streaks(session)

        assert result == []


# ---------------------------------------------------------------------------
# reset_streak
# ---------------------------------------------------------------------------


class TestResetStreak:
    async def test_executes_update(self):
        """reset_streak should execute an update statement."""
        session = _make_session()
        habit_id = uuid.uuid4()

        await reset_streak(session, habit_id)

        session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_habit_logs
# ---------------------------------------------------------------------------


class TestGetHabitLogs:
    async def test_returns_logs(self):
        """Should return habit logs within the time window."""
        session = _make_session()
        log1 = HabitLog(
            habit_id=uuid.uuid4(),
            completed_at=datetime.now(UTC),
            note="Done",
            source="manual",
        )
        log2 = HabitLog(
            habit_id=uuid.uuid4(),
            completed_at=datetime.now(UTC),
            note=None,
            source="manual",
        )
        session.execute.return_value = _make_scalars_result([log1, log2])

        result = await get_habit_logs(session, uuid.uuid4(), days=30)

        assert len(result) == 2
        session.execute.assert_awaited_once()

    async def test_returns_empty(self):
        """Should return empty list when no logs exist."""
        session = _make_session()
        session.execute.return_value = _make_scalars_result([])

        result = await get_habit_logs(session, uuid.uuid4(), days=7)

        assert result == []

    async def test_custom_days_parameter(self):
        """Custom days parameter should be accepted."""
        session = _make_session()
        session.execute.return_value = _make_scalars_result([])

        result = await get_habit_logs(session, uuid.uuid4(), days=90)

        assert result == []
        session.execute.assert_awaited_once()
