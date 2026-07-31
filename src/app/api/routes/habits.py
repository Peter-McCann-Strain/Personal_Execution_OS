"""Habit tracking endpoints — CRUD habits and log completions."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_principal, get_db
from src.app.api.transactions import session_transaction
from src.app.api.utils import format_datetime
from src.app.core.exceptions import NotFoundError
from src.app.persistence.repositories.habits import (
    create_habit as repo_create_habit,
)
from src.app.persistence.repositories.habits import (
    get_active_habits as repo_get_active_habits,
)
from src.app.persistence.repositories.habits import (
    get_habit_by_id as repo_get_habit_by_id,
)
from src.app.persistence.repositories.habits import (
    get_habit_logs as repo_get_habit_logs,
)
from src.app.persistence.repositories.habits import (
    log_habit_completion as repo_log_habit_completion,
)

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class HabitDTO(BaseModel):
    id: str
    name: str
    description: str | None
    frequency: str
    frequency_days: int
    current_streak: int
    longest_streak: int
    total_completions: int
    last_completed_at: str | None
    active: bool
    tags: list[str]
    created_at: str


class HabitLogDTO(BaseModel):
    id: str
    habit_id: str
    completed_at: str
    note: str | None
    source: str


class CreateHabitBody(BaseModel):
    name: str
    description: str | None = None
    frequency: str = "daily"
    frequency_days: int = Field(default=1, ge=1)
    tags: list[str] | None = None


class LogCompletionBody(BaseModel):
    note: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Keep module-level alias so existing test imports continue to work.
_fmt_dt = format_datetime


def _habit_to_dto(h) -> HabitDTO:
    return HabitDTO(
        id=str(h.id),
        name=h.name,
        description=h.description,
        frequency=h.frequency,
        frequency_days=h.frequency_days,
        current_streak=h.current_streak,
        longest_streak=h.longest_streak,
        total_completions=h.total_completions,
        last_completed_at=_fmt_dt(h.last_completed_at),
        active=h.active,
        tags=h.tags or [],
        created_at=h.created_at.isoformat(),
    )


def _log_to_dto(log) -> HabitLogDTO:
    return HabitLogDTO(
        id=str(log.id),
        habit_id=str(log.habit_id),
        completed_at=log.completed_at.isoformat(),
        note=log.note,
        source=log.source,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/habits", response_model=list[HabitDTO])
async def list_habits(
    session: AsyncSession = Depends(get_db),
) -> list[HabitDTO]:
    """List all active habits."""
    habits = await repo_get_active_habits(session)
    return [_habit_to_dto(h) for h in habits]


@router.post("/habits", response_model=HabitDTO, status_code=201)
async def create_habit(
    body: CreateHabitBody,
    session: AsyncSession = Depends(get_db),
) -> HabitDTO:
    """Create a new habit."""
    async with session_transaction(session):
        habit = await repo_create_habit(
            session,
            name=body.name,
            description=body.description,
            frequency=body.frequency,
            frequency_days=body.frequency_days,
            tags=body.tags,
        )
    await session.refresh(habit)
    logger.info("habit_created_via_api", habit_id=str(habit.id))
    return _habit_to_dto(habit)


@router.get("/habits/{habit_id}", response_model=HabitDTO)
async def get_habit(
    habit_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> HabitDTO:
    """Get a single habit by ID."""
    habit = await repo_get_habit_by_id(session, habit_id)
    if habit is None:
        raise NotFoundError(f"Habit {habit_id} not found")
    return _habit_to_dto(habit)


@router.post("/habits/{habit_id}/complete", response_model=HabitLogDTO, status_code=201)
async def complete_habit(
    habit_id: uuid.UUID,
    body: LogCompletionBody | None = None,
    session: AsyncSession = Depends(get_db),
) -> HabitLogDTO:
    """Log a habit completion."""
    habit = await repo_get_habit_by_id(session, habit_id)
    if habit is None:
        raise NotFoundError(f"Habit {habit_id} not found")

    async with session_transaction(session):
        log = await repo_log_habit_completion(
            session,
            habit_id=habit_id,
            note=body.note if body else None,
        )
    await session.refresh(log)
    logger.info(
        "habit_completed_via_api",
        habit_id=str(habit_id),
        log_id=str(log.id),
    )
    return _log_to_dto(log)


@router.get("/habits/{habit_id}/logs", response_model=list[HabitLogDTO])
async def list_habit_logs(
    habit_id: uuid.UUID,
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_db),
) -> list[HabitLogDTO]:
    """List completion logs for a habit within the last N days."""
    habit = await repo_get_habit_by_id(session, habit_id)
    if habit is None:
        raise NotFoundError(f"Habit {habit_id} not found")

    logs = await repo_get_habit_logs(session, habit_id, days=days)
    return [_log_to_dto(log) for log in logs]
