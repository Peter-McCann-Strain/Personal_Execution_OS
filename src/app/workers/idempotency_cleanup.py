"""Daily cleanup of expired idempotency_keys rows.

The idempotency table grows at ~1 row per mutating POST. Rows past their
24-hour TTL are safe to drop — any future request with the same header value
will just insert a fresh row.

Runs once a day from ``WorkerSettings.cron_jobs``. Skipping the cron or
running it twice is harmless: the DELETE is idempotent.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.app.persistence.repositories import idempotency as idempotency_repo

logger = structlog.get_logger()


async def run_idempotency_cleanup(ctx: dict) -> None:
    """Delete all idempotency_keys rows whose expires_at is in the past."""
    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    if session_factory is None:
        logger.error("idempotency_cleanup_no_session_factory")
        return

    async with session_factory() as session:
        try:
            deleted = await idempotency_repo.delete_expired(session)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("idempotency_cleanup_failed")
            raise

    logger.info("idempotency_cleanup_completed", rows_deleted=deleted)
