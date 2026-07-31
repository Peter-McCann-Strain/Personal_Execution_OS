"""Persistence helpers for user-facing scheduled actions."""

from __future__ import annotations

import inspect
import uuid
from calendar import monthrange
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import (
    ScheduledAction,
    ScheduledActionRun,
    not_deleted,
)

_WEEKDAY_LOOKUP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


async def _session_add(session: AsyncSession, instance: object) -> None:
    result = session.add(instance)
    if inspect.isawaitable(result):
        await result


def _tz(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def _coerce_weekday(value: object) -> int:
    if isinstance(value, int):
        return min(max(value, 0), 6)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in _WEEKDAY_LOOKUP:
            return _WEEKDAY_LOOKUP[normalized]
        if normalized.isdigit():
            return min(max(int(normalized), 0), 6)
    return 0


def _coerce_int(value: object, default: int, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return min(max(value, minimum), maximum)
    if isinstance(value, float):
        return min(max(int(value), minimum), maximum)
    if isinstance(value, str) and value.strip().isdigit():
        return min(max(int(value.strip()), minimum), maximum)
    return default


def _next_daily_run(now_local: datetime, *, hour: int, minute: int) -> datetime:
    candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now_local:
        candidate += timedelta(days=1)
    return candidate


def _next_weekly_run(now_local: datetime, *, weekday: int, hour: int, minute: int) -> datetime:
    candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_ahead = (weekday - candidate.weekday()) % 7
    if days_ahead == 0 and candidate <= now_local:
        days_ahead = 7
    candidate += timedelta(days=days_ahead)
    return candidate


def _next_monthly_run(now_local: datetime, *, day: int, hour: int, minute: int) -> datetime:
    year = now_local.year
    month = now_local.month
    for _ in range(14):
        last_day = monthrange(year, month)[1]
        safe_day = min(max(day, 1), last_day)
        candidate = now_local.replace(
            year=year,
            month=month,
            day=safe_day,
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if candidate > now_local:
            return candidate
        month += 1
        if month > 12:
            month = 1
            year += 1
    return now_local + timedelta(days=30)


def compute_next_run_at(
    *,
    schedule_type: str,
    schedule_config: dict[str, Any] | None,
    timezone: str,
    now: datetime | None = None,
) -> datetime | None:
    """Compute the next UTC run time for a scheduled action."""
    config = schedule_config or {}
    tz = _tz(timezone)
    current_utc = now or datetime.now(UTC)
    now_local = current_utc.astimezone(tz)

    if schedule_type == "once":
        raw = config.get("run_at")
        if isinstance(raw, str) and raw:
            run_at = datetime.fromisoformat(raw)
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=tz)
            return run_at.astimezone(UTC)
        return None

    hour = _coerce_int(config.get("hour"), 9, minimum=0, maximum=23)
    minute = _coerce_int(config.get("minute"), 0, minimum=0, maximum=59)

    if schedule_type == "daily":
        return _next_daily_run(now_local, hour=hour, minute=minute).astimezone(UTC)
    if schedule_type == "weekly":
        weekday = _coerce_weekday(config.get("weekday"))
        return _next_weekly_run(
            now_local,
            weekday=weekday,
            hour=hour,
            minute=minute,
        ).astimezone(UTC)
    if schedule_type == "monthly":
        day = _coerce_int(config.get("day"), 1, minimum=1, maximum=31)
        return _next_monthly_run(
            now_local,
            day=day,
            hour=hour,
            minute=minute,
        ).astimezone(UTC)
    return None


async def create_scheduled_action(
    session: AsyncSession,
    *,
    user_id: str,
    title: str,
    prompt: str,
    schedule_type: str,
    schedule_config: dict[str, Any] | None,
    timezone: str,
    status: str = "active",
    delivery_channel: str = "web",
    metadata: dict[str, Any] | None = None,
) -> ScheduledAction:
    """Create one scheduled action."""
    record = ScheduledAction(
        user_id=user_id,
        title=title,
        prompt=prompt,
        schedule_type=schedule_type,
        schedule_config=schedule_config or {},
        timezone=timezone,
        status=status,
        delivery_channel=delivery_channel,
        next_run_at=(
            compute_next_run_at(
                schedule_type=schedule_type,
                schedule_config=schedule_config,
                timezone=timezone,
            )
            if status == "active"
            else None
        ),
        metadata_=metadata or {},
    )
    await _session_add(session, record)
    await session.flush()
    return record


async def get_scheduled_action(
    session: AsyncSession,
    *,
    action_id: uuid.UUID,
    user_id: str,
) -> ScheduledAction | None:
    """Fetch one scheduled action for one user."""
    stmt = select(ScheduledAction).where(
        ScheduledAction.id == action_id,
        ScheduledAction.user_id == user_id,
        not_deleted(ScheduledAction),
    )
    result = await session.execute(stmt.limit(1))
    return result.scalar_one_or_none()


async def list_scheduled_actions(
    session: AsyncSession,
    *,
    user_id: str,
    limit: int = 25,
    offset: int = 0,
    status: str | None = None,
) -> tuple[list[ScheduledAction], int]:
    """List scheduled actions for one user."""
    stmt = select(ScheduledAction).where(
        ScheduledAction.user_id == user_id,
        not_deleted(ScheduledAction),
    )
    if status:
        stmt = stmt.where(ScheduledAction.status == status)
    count_result = await session.execute(select(func.count()).select_from(stmt.subquery()))
    total = int(count_result.scalar_one())
    result = await session.execute(
        stmt.order_by(ScheduledAction.next_run_at.asc(), ScheduledAction.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def update_scheduled_action(
    session: AsyncSession,
    *,
    action_id: uuid.UUID,
    user_id: str,
    title: str | None = None,
    prompt: str | None = None,
    schedule_type: str | None = None,
    schedule_config: dict[str, Any] | None = None,
    timezone: str | None = None,
    status: str | None = None,
    delivery_channel: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ScheduledAction | None:
    """Update one scheduled action."""
    record = await get_scheduled_action(session, action_id=action_id, user_id=user_id)
    if record is None:
        return None

    if title is not None:
        record.title = title
    if prompt is not None:
        record.prompt = prompt
    if schedule_type is not None:
        record.schedule_type = schedule_type
    if schedule_config is not None:
        record.schedule_config = schedule_config
    if timezone is not None:
        record.timezone = timezone
    if status is not None:
        record.status = status
    if delivery_channel is not None:
        record.delivery_channel = delivery_channel
    if metadata is not None:
        record.metadata_ = metadata

    record.next_run_at = (
        compute_next_run_at(
            schedule_type=record.schedule_type,
            schedule_config=record.schedule_config,
            timezone=record.timezone,
        )
        if record.status == "active"
        else None
    )
    record.updated_at = datetime.now(UTC)
    await session.flush()
    return record


async def soft_delete_scheduled_action(
    session: AsyncSession,
    *,
    action_id: uuid.UUID,
    user_id: str,
) -> bool:
    """Soft-delete one scheduled action."""
    record = await get_scheduled_action(session, action_id=action_id, user_id=user_id)
    if record is None:
        return False
    record.soft_delete()
    record.updated_at = datetime.now(UTC)
    await session.flush()
    return True


async def create_scheduled_action_run(
    session: AsyncSession,
    *,
    action_id: uuid.UUID,
    workflow_id: uuid.UUID | None = None,
    status: str = "queued",
    payload: dict[str, Any] | None = None,
) -> ScheduledActionRun:
    """Create one execution record for a scheduled action."""
    record = ScheduledActionRun(
        action_id=action_id,
        workflow_id=workflow_id,
        status=status,
        payload=payload or {},
    )
    await _session_add(session, record)
    await session.flush()
    return record


async def update_scheduled_action_run(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    status: str,
    result_summary: str | None = None,
    error_message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ScheduledActionRun | None:
    """Update one scheduled action run."""
    record = await session.get(ScheduledActionRun, run_id)
    if record is None:
        return None
    record.status = status
    if result_summary is not None:
        record.result_summary = result_summary
    if error_message is not None:
        record.error_message = error_message
    if payload is not None:
        record.payload = payload
    if status in {"completed", "failed"}:
        record.completed_at = datetime.now(UTC)
    await session.flush()
    return record


async def list_scheduled_action_runs(
    session: AsyncSession,
    *,
    user_id: str,
    action_id: uuid.UUID | None = None,
    limit: int = 25,
) -> list[ScheduledActionRun]:
    """List execution history for scheduled actions."""
    stmt = (
        select(ScheduledActionRun)
        .join(
            ScheduledAction,
            ScheduledActionRun.action_id == ScheduledAction.id,
        )
        .where(
            ScheduledAction.user_id == user_id,
            not_deleted(ScheduledAction),
        )
    )
    if action_id is not None:
        stmt = stmt.where(ScheduledActionRun.action_id == action_id)
    result = await session.execute(
        stmt.order_by(ScheduledActionRun.triggered_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def list_due_scheduled_actions(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 25,
) -> list[ScheduledAction]:
    """Return active actions that are due now."""
    current = now or datetime.now(UTC)
    stmt = (
        select(ScheduledAction)
        .where(
            ScheduledAction.status == "active",
            ScheduledAction.next_run_at.is_not(None),
            ScheduledAction.next_run_at <= current,
            not_deleted(ScheduledAction),
        )
        .order_by(ScheduledAction.next_run_at.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def mark_scheduled_action_executed(
    session: AsyncSession,
    *,
    action: ScheduledAction,
    result_summary: str,
    now: datetime | None = None,
) -> ScheduledAction:
    """Advance a scheduled action after a successful or user-visible run."""
    current = now or datetime.now(UTC)
    action.last_run_at = current
    action.last_result_summary = result_summary
    if action.schedule_type == "once":
        action.status = "archived"
        action.next_run_at = None
    else:
        action.next_run_at = compute_next_run_at(
            schedule_type=action.schedule_type,
            schedule_config=action.schedule_config or {},
            timezone=action.timezone,
            now=current + timedelta(seconds=1),
        )
    action.updated_at = current
    await session.flush()
    return action
