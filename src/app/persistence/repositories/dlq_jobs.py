"""Repository for the ARQ dead-letter queue (Phase 7.1).

All writes are intentionally best-effort at the caller site. If the DLQ
insert itself fails (e.g. DB unreachable), the worker logs and swallows
the error — losing a DLQ row is better than killing the worker.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import DLQJob

logger = structlog.get_logger()


async def create_dlq_job(
    session: AsyncSession,
    *,
    function: str,
    exception_class: str,
    exception_message: str | None = None,
    traceback_text: str | None = None,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    job_id: str | None = None,
    retry_count: int = 0,
    enqueued_at: datetime | None = None,
    failed_at: datetime | None = None,
) -> DLQJob:
    """Insert one DLQ row. Caller owns the session transaction (commit/rollback)."""
    record = DLQJob(
        job_id=job_id,
        function=function,
        args=args,
        kwargs=kwargs,
        exception_class=exception_class,
        exception_message=exception_message,
        traceback=traceback_text,
        retry_count=retry_count,
        enqueued_at=enqueued_at,
        failed_at=failed_at or datetime.now(UTC),
    )
    session.add(record)
    await session.flush()
    return record


async def list_dlq_jobs(
    session: AsyncSession,
    *,
    function: str | None = None,
    include_replayed: bool = True,
    max_age_hours: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[DLQJob]:
    """List DLQ rows filtered by function / age / replay status.

    Rows are returned newest-first (by ``failed_at``).
    """
    stmt = select(DLQJob)
    if function is not None:
        stmt = stmt.where(DLQJob.function == function)
    if not include_replayed:
        stmt = stmt.where(DLQJob.replayed_at.is_(None))
    if max_age_hours is not None:
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        stmt = stmt.where(DLQJob.failed_at >= cutoff)
    stmt = stmt.order_by(DLQJob.failed_at.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_unreplayed_older_than(
    session: AsyncSession,
    *,
    hours: int,
) -> dict[str, int]:
    """Return counts of unreplayed DLQ rows older than ``hours``, keyed by function.

    Used by ``run_dlq_alerts`` to decide whether to fire a Telegram alert.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    stmt = (
        select(DLQJob.function, func.count(DLQJob.id))
        .where(DLQJob.replayed_at.is_(None))
        .where(DLQJob.failed_at <= cutoff)
        .group_by(DLQJob.function)
    )
    result = await session.execute(stmt)
    return {row[0]: int(row[1]) for row in result.all()}


async def get_dlq_job_by_id(
    session: AsyncSession,
    dlq_id: uuid.UUID,
) -> DLQJob | None:
    """Fetch one DLQ row by primary key."""
    return await session.get(DLQJob, dlq_id)


async def mark_replayed(
    session: AsyncSession,
    *,
    dlq_id: uuid.UUID,
    replay_result: str,
    replayed_at: datetime | None = None,
) -> bool:
    """Stamp a DLQ row as replayed. Returns True when the row was updated."""
    now = replayed_at or datetime.now(UTC)
    result = await session.execute(
        update(DLQJob)
        .where(DLQJob.id == dlq_id)
        .values(replayed_at=now, replay_result=replay_result)
    )
    await session.flush()
    return (result.rowcount or 0) > 0


async def delete_replayed_older_than(
    session: AsyncSession,
    *,
    days: int,
) -> int:
    """Hard-delete replayed DLQ rows older than ``days``. Returns rows removed."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    from sqlalchemy import delete as sql_delete

    result = await session.execute(
        sql_delete(DLQJob).where(DLQJob.replayed_at.is_not(None)).where(DLQJob.failed_at <= cutoff)
    )
    await session.flush()
    return int(result.rowcount or 0)
