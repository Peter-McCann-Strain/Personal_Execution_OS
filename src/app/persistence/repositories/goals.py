"""Goals repository -- full CRUD for the goals hierarchy.

All functions require the caller to manage session.commit(). Use
``async with session.begin():`` for automatic transaction management.
"""

import uuid
from datetime import datetime

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.domain.constants import GoalStatus
from src.app.persistence.models import Goal

logger = structlog.get_logger()


async def create_goal(
    session: AsyncSession,
    title: str,
    goal_type: str | None = None,
    parent_id: uuid.UUID | None = None,
    priority: int = 5,
    deadline: datetime | None = None,
    evidence: list[str] | None = None,
) -> Goal:
    """Create a new goal. Returns the ORM model instance."""
    if deadline is not None and not isinstance(deadline, datetime):
        msg = f"deadline must be a datetime, got {type(deadline).__name__}"
        raise TypeError(msg)

    goal = Goal(
        title=title,
        goal_type=goal_type,
        parent_id=parent_id,
        priority=priority,
        status=GoalStatus.ACTIVE,
        progress=0.0,
        deadline=deadline,
        evidence=evidence,
    )
    session.add(goal)
    await session.flush()
    logger.info("goal_created", goal_id=str(goal.id))
    return goal


async def get_goal_by_id(
    session: AsyncSession,
    goal_id: uuid.UUID,
) -> Goal | None:
    """Get a single goal by ID, or None if not found."""
    result = await session.execute(
        select(Goal).where(Goal.id == goal_id, Goal.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def list_goals(
    session: AsyncSession,
    status: str | None = None,
    goal_type: str | None = None,
    parent_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[Goal]:
    """List goals with optional filters."""
    stmt = select(Goal).where(Goal.deleted_at.is_(None))

    if status is not None:
        stmt = stmt.where(Goal.status == status)
    if goal_type is not None:
        stmt = stmt.where(Goal.goal_type == goal_type)
    if parent_id is not None:
        stmt = stmt.where(Goal.parent_id == parent_id)

    stmt = stmt.order_by(Goal.priority.asc(), Goal.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_child_goals(
    session: AsyncSession,
    parent_id: uuid.UUID,
) -> list[Goal]:
    """Get all direct child goals of a parent goal."""
    stmt = (
        select(Goal)
        .where(Goal.parent_id == parent_id, Goal.deleted_at.is_(None))
        .order_by(Goal.priority.asc(), Goal.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_goal(
    session: AsyncSession,
    goal_id: uuid.UUID,
    **kwargs: str | int | float | list[str] | None,
) -> Goal:
    """Update goal fields. Only provided kwargs are updated.

    Raises ValueError if the goal is not found.
    """
    allowed = {
        "title",
        "goal_type",
        "parent_id",
        "priority",
        "status",
        "progress",
        "deadline",
        "evidence",
    }
    updates: dict[str, object] = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        goal = await get_goal_by_id(session, goal_id)
        if goal is None:
            msg = f"Goal not found: {goal_id}"
            raise ValueError(msg)
        return goal

    updates["updated_at"] = func.now()

    stmt = (
        update(Goal)
        .where(Goal.id == goal_id, Goal.deleted_at.is_(None))
        .values(**updates)
        .returning(Goal)
    )
    result = await session.execute(stmt)
    goal = result.scalar_one_or_none()
    if goal is None:
        msg = f"Goal not found: {goal_id}"
        raise ValueError(msg)
    logger.info("goal_updated", goal_id=str(goal_id), fields=list(updates.keys()))
    return goal


async def delete_goal(
    session: AsyncSession,
    goal_id: uuid.UUID,
) -> bool:
    """Delete a goal by ID. Returns True if deleted, False if not found.

    Child goals are cascade-deleted via FK constraint.
    """
    stmt = delete(Goal).where(Goal.id == goal_id)
    result = await session.execute(stmt)
    deleted = result.rowcount > 0
    if deleted:
        logger.info("goal_deleted", goal_id=str(goal_id))
    return deleted
