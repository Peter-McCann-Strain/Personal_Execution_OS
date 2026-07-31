"""Goals API routes — paginated listing, detail, and progress updates."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.api.transactions import session_transaction
from src.app.core.exceptions import NotFoundError
from src.app.domain.services.handlers._common import enqueue_reflection_pack_refresh
from src.app.persistence.models import Goal
from src.app.persistence.repositories.goals import (
    create_goal as repo_create_goal,
)
from src.app.persistence.repositories.goals import (
    get_child_goals as repo_get_child_goals,
)
from src.app.persistence.repositories.goals import get_goal_by_id as repo_get_goal_by_id
from src.app.persistence.repositories.goals import update_goal

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class GoalDTO(BaseModel):
    """Goal data transfer object matching the frontend Goal type."""

    id: str
    title: str
    goal_type: str | None
    parent_id: str | None
    priority: int
    status: str
    progress: float
    deadline: str | None
    evidence: list[str]
    created_at: str
    updated_at: str


class CreateGoalBody(BaseModel):
    """Body for POST /goals."""

    title: str
    goal_type: str | None = None
    parent_id: uuid.UUID | None = None
    priority: int = Field(default=5, ge=1, le=10)
    deadline: str | None = None
    evidence: list[str] | None = None

    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                datetime.fromisoformat(v)
            except (ValueError, TypeError) as e:
                msg = f"Invalid ISO 8601 datetime: {v!r}"
                raise ValueError(msg) from e
        return v


class UpdateGoalProgressBody(BaseModel):
    """Body for PATCH /goals/{goal_id}."""

    progress: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _goal_to_dto(goal: Goal) -> GoalDTO:
    """Convert an ORM Goal to a GoalDTO."""
    return GoalDTO(
        id=str(goal.id),
        title=goal.title,
        goal_type=goal.goal_type,
        parent_id=str(goal.parent_id) if goal.parent_id else None,
        priority=goal.priority,
        status=goal.status,
        progress=goal.progress,
        deadline=goal.deadline.isoformat() if goal.deadline else None,
        evidence=goal.evidence or [],
        created_at=goal.created_at.isoformat(),
        updated_at=goal.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/goals", response_model=PaginatedResponse[GoalDTO])
async def list_goals(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    goal_type: str | None = Query(None),
    sort: Literal["priority", "progress", "deadline", "created_at"] = Query("priority"),
    order: Literal["asc", "desc"] = Query("asc"),
) -> PaginatedResponse[GoalDTO]:
    """Paginated goals list with optional filters and sorting."""
    # Build base query — exclude soft-deleted goals
    stmt = select(Goal).where(Goal.deleted_at.is_(None))

    if status is not None:
        stmt = stmt.where(Goal.status == status)
    if goal_type is not None:
        stmt = stmt.where(Goal.goal_type == goal_type)

    # Count total before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    # Sorting
    sort_column = getattr(Goal, sort)
    if order == "desc":
        stmt = stmt.order_by(sort_column.desc().nulls_last())
    else:
        stmt = stmt.order_by(sort_column.asc().nulls_last())

    # Pagination
    stmt = stmt.offset(offset).limit(limit)

    result = await session.execute(stmt)
    goals = list(result.scalars().all())

    items = [_goal_to_dto(g) for g in goals]
    return paginate(items=items, total=total, offset=offset, limit=limit)


@router.get("/goals/{goal_id}", response_model=GoalDTO)
async def get_goal(
    goal_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> GoalDTO:
    """Get a single goal by ID."""
    goal = await repo_get_goal_by_id(session, goal_id)
    if goal is None:
        raise NotFoundError(f"Goal not found: {goal_id}")
    return _goal_to_dto(goal)


@router.post("/goals", response_model=GoalDTO, status_code=201)
async def create_goal(
    body: CreateGoalBody,
    session: AsyncSession = Depends(get_db),
) -> GoalDTO:
    """Create a new goal."""
    deadline_dt: datetime | None = None
    if body.deadline:
        deadline_dt = datetime.fromisoformat(body.deadline)

    async with session_transaction(session):
        goal = await repo_create_goal(
            session,
            title=body.title,
            goal_type=body.goal_type,
            parent_id=body.parent_id,
            priority=body.priority,
            deadline=deadline_dt,
            evidence=body.evidence,
        )
    await session.refresh(goal)
    try:
        await enqueue_reflection_pack_refresh("goal_created")
    except Exception:
        logger.warning("goal_reflection_pack_refresh_degraded", goal_id=str(goal.id), exc_info=True)
    logger.info("goal_created_via_api", goal_id=str(goal.id))
    return _goal_to_dto(goal)


@router.get("/goals/{goal_id}/children", response_model=list[GoalDTO])
async def get_child_goals(
    goal_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> list[GoalDTO]:
    """Get all direct child goals of a parent goal."""
    children = await repo_get_child_goals(session, parent_id=goal_id)
    return [_goal_to_dto(g) for g in children]


@router.patch("/goals/{goal_id}", response_model=GoalDTO)
async def update_goal_progress(
    goal_id: uuid.UUID,
    body: UpdateGoalProgressBody,
    session: AsyncSession = Depends(get_db),
) -> GoalDTO:
    """Update goal progress."""
    async with session_transaction(session):
        try:
            goal = await update_goal(session, goal_id, progress=body.progress)
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc
    await session.refresh(goal)
    try:
        await enqueue_reflection_pack_refresh("goal_progress_updated")
    except Exception:
        logger.warning("goal_reflection_pack_refresh_degraded", goal_id=str(goal.id), exc_info=True)
    logger.info("goal_progress_updated", goal_id=str(goal_id), progress=body.progress)
    return _goal_to_dto(goal)


@router.delete("/goals/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a goal by ID."""
    async with session_transaction(session):
        goal = await repo_get_goal_by_id(session, goal_id)
        if goal is None:
            raise NotFoundError(f"Goal not found: {goal_id}")
        goal.soft_delete()
    logger.info("goal_soft_deleted_via_api", goal_id=str(goal_id))
