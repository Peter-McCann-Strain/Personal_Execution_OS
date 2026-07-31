"""Shared API utility helpers — deduplicated from route modules."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import get_settings


def format_datetime(dt: datetime | None) -> str | None:
    """Format a datetime to ISO-8601, or return ``None``."""
    if dt is None:
        return None
    return dt.isoformat()


async def paginated_count(session: AsyncSession, query) -> int:
    """Return the total row count for an arbitrary SELECT query."""
    count_query = select(func.count()).select_from(query.subquery())
    return (await session.execute(count_query)).scalar_one()


def check_google_configured() -> None:
    """Raise 503 if Google OAuth credentials are not set."""
    settings = get_settings()
    if not settings.google_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "Google is not configured. "
                "Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REFRESH_TOKEN."
            ),
        )
