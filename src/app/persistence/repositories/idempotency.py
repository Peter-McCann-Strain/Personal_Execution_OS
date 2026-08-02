"""Persistence helpers for the HTTP idempotency table.

Used by :mod:`src.app.api.idempotency` to cache completed HTTP responses
against a client-supplied ``Idempotency-Key`` header.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.async_utils import affected_rows
from src.app.persistence.models import IdempotencyKey


async def get_active_key(
    session: AsyncSession,
    *,
    key: str,
) -> IdempotencyKey | None:
    """Return the live idempotency row for ``key`` (expired rows are ignored).

    A row with ``expires_at <= now()`` is treated as absent so the caller can
    re-use the key as if it were new. The cleanup cron eventually removes the
    stale row; this method is forward-safe in the meantime.
    """
    now = datetime.now(UTC)
    stmt = (
        select(IdempotencyKey)
        .where(
            and_(
                IdempotencyKey.key == key,
                IdempotencyKey.expires_at > now,
            )
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_key(
    session: AsyncSession,
    *,
    key: str,
    for_update: bool = False,
) -> IdempotencyKey | None:
    """Return a key regardless of expiry, optionally locking it."""
    stmt = select(IdempotencyKey).where(IdempotencyKey.key == key).limit(1)
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def reset_started(
    session: AsyncSession,
    *,
    record: IdempotencyKey,
    request_fingerprint: str,
    method: str,
    route: str,
) -> IdempotencyKey:
    """Reuse an expired completed row or a legacy failed row."""
    now = datetime.now(UTC)
    record.request_fingerprint = request_fingerprint
    record.recovery_point = "started"
    record.response_status = None
    record.response_body = None
    record.response_headers = None
    record.method = method
    record.route = route
    record.created_at = now
    record.expires_at = now + timedelta(hours=24)
    await session.flush()
    return record


async def insert_started(
    session: AsyncSession,
    *,
    key: str,
    request_fingerprint: str,
    method: str,
    route: str,
) -> IdempotencyKey:
    """Insert a fresh row with ``recovery_point='started'``.

    Raises :class:`sqlalchemy.exc.IntegrityError` if another request inserted
    the same key concurrently — the caller catches that and re-reads the row.
    """
    record = IdempotencyKey(
        key=key,
        request_fingerprint=request_fingerprint,
        recovery_point="started",
        method=method,
        route=route,
    )
    session.add(record)
    await session.flush()
    return record


async def mark_completed(
    session: AsyncSession,
    *,
    key: str,
    response_status: int,
    response_body: Any,
    response_headers: dict[str, str] | None = None,
) -> IdempotencyKey | None:
    """Write the cached response back to the row and flip the recovery point.

    All completed responses are cached to preserve at-most-once execution
    across ambiguous downstream failures.
    """
    record = await get_active_key(session, key=key)
    if record is None:
        return None
    record.recovery_point = "completed"
    record.response_status = response_status
    record.response_body = _as_json_safe(response_body)
    record.response_headers = dict(response_headers) if response_headers else None
    await session.flush()
    return record


async def mark_failed(
    session: AsyncSession,
    *,
    key: str,
) -> IdempotencyKey | None:
    """Flip the row to ``recovery_point='failed'`` without caching a body.

    Lets us distinguish handler crashes from completed 2xx/4xx responses —
    on the next request the client can retry without a 409 collision.
    """
    record = await get_active_key(session, key=key)
    if record is None:
        return None
    record.recovery_point = "failed"
    await session.flush()
    return record


async def delete_expired(session: AsyncSession) -> int:
    """Remove all rows past their TTL. Called by the daily cron."""
    now = datetime.now(UTC)
    # A started row may represent a slow or externally committed operation.
    # Never delete it automatically: that could let the same key execute twice.
    stmt = delete(IdempotencyKey).where(
        IdempotencyKey.expires_at < now,
        IdempotencyKey.recovery_point != "started",
    )
    result = await session.execute(stmt)
    return affected_rows(result)


def _as_json_safe(value: Any) -> Any:
    """Coerce common response payloads into JSON-serialisable form.

    FastAPI response bodies arrive as ``bytes``; we decode those to UTF-8 and
    then try to parse them as JSON so repeat callers see the same structure
    instead of a base64 blob. Dictionaries/lists/primitives pass through.
    """
    if isinstance(value, bytes | bytearray):
        try:
            import json

            return json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return {"__raw__": value.decode("utf-8", errors="replace")}
    return value
