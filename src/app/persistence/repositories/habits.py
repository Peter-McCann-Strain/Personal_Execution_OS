"""Repository functions for habit tracking.

All functions require the caller to manage session.commit(). Use
``async with session.begin():`` for automatic transaction management.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import Habit, HabitLog

logger = structlog.get_logger()


async def create_habit(
    session: AsyncSession,
    *,
    name: str,
    description: str | None = None,
    frequency: str = "daily",
    frequency_days: int = 1,
    tags: list[str] | None = None,
) -> Habit:
    """Create a new habit. Returns the ORM model instance."""
    habit = Habit(
        name=name,
        description=description,
        frequency=frequency,
        frequency_days=frequency_days,
        tags=tags,
    )
    session.add(habit)
    await session.flush()
    logger.info("habit_created", habit_id=str(habit.id))
    return habit


async def get_active_habits(session: AsyncSession) -> list[Habit]:
    """Return all active habits, ordered by name."""
    result = await session.execute(select(Habit).where(Habit.active.is_(True)).order_by(Habit.name))
    return list(result.scalars().all())


async def get_habit_by_id(session: AsyncSession, habit_id: uuid.UUID) -> Habit | None:
    """Get a single habit by ID, or None if not found."""
    return await session.get(Habit, habit_id)


async def log_habit_completion(
    session: AsyncSession,
    *,
    habit_id: uuid.UUID,
    note: str | None = None,
    source: str = "manual",
) -> HabitLog:
    """Log a habit completion and update streak counters."""
    now = datetime.now(tz=UTC)
    log = HabitLog(habit_id=habit_id, completed_at=now, note=note, source=source)
    session.add(log)

    # Update streak
    habit = await session.get(Habit, habit_id)
    if habit:
        habit.total_completions += 1
        habit.last_completed_at = now

        # Check if streak is maintained (completed within frequency window)
        if habit.current_streak == 0:
            habit.current_streak = 1
        else:
            habit.current_streak += 1

        if habit.current_streak > habit.longest_streak:
            habit.longest_streak = habit.current_streak

    await session.flush()
    logger.info(
        "habit_completed",
        habit_id=str(habit_id),
        streak=habit.current_streak if habit else 0,
    )
    return log


async def check_broken_streaks(session: AsyncSession) -> list[Habit]:
    """Find habits whose streak should be broken (missed their frequency window)."""
    now = datetime.now(tz=UTC)
    result = await session.execute(
        select(Habit).where(
            Habit.active.is_(True),
            Habit.current_streak > 0,
            Habit.last_completed_at.isnot(None),
        )
    )
    return [
        habit
        for habit in result.scalars().all()
        if habit.last_completed_at
        and now > habit.last_completed_at + timedelta(days=habit.frequency_days + 1)
    ]


async def reset_streak(session: AsyncSession, habit_id: uuid.UUID) -> None:
    """Reset a habit's current streak to zero."""
    await session.execute(update(Habit).where(Habit.id == habit_id).values(current_streak=0))


async def get_habit_logs(
    session: AsyncSession,
    habit_id: uuid.UUID,
    *,
    days: int = 30,
) -> list[HabitLog]:
    """Get completion logs for a habit within the last N days."""
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    result = await session.execute(
        select(HabitLog)
        .where(HabitLog.habit_id == habit_id, HabitLog.completed_at >= cutoff)
        .order_by(HabitLog.completed_at.desc())
    )
    return list(result.scalars().all())
