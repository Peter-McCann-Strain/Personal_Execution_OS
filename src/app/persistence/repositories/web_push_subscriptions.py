"""Persistence helpers for owner-scoped web push subscriptions."""

from __future__ import annotations

import hashlib
import inspect
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import WebPushSubscription, not_deleted


async def _session_add(session: AsyncSession, instance: object) -> None:
    result = session.add(instance)
    if inspect.isawaitable(result):
        await result


def _endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.strip().encode("utf-8")).hexdigest()


async def list_web_push_subscriptions(
    session: AsyncSession,
    *,
    user_id: str,
    include_revoked: bool = False,
) -> list[WebPushSubscription]:
    """List web push subscriptions for one owner."""
    stmt = select(WebPushSubscription).where(
        WebPushSubscription.user_id == user_id,
        not_deleted(WebPushSubscription),
    )
    if not include_revoked:
        stmt = stmt.where(WebPushSubscription.status != "revoked")
    stmt = stmt.order_by(
        WebPushSubscription.updated_at.desc(), WebPushSubscription.created_at.desc()
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_web_push_subscription(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    user_id: str,
) -> WebPushSubscription | None:
    """Fetch one web push subscription for one owner."""
    stmt = select(WebPushSubscription).where(
        WebPushSubscription.id == subscription_id,
        WebPushSubscription.user_id == user_id,
        not_deleted(WebPushSubscription),
    )
    result = await session.execute(stmt.limit(1))
    return result.scalar_one_or_none()


async def upsert_web_push_subscription(
    session: AsyncSession,
    *,
    user_id: str,
    endpoint: str,
    auth_key: str,
    p256dh_key: str,
    expiration_time: datetime | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> WebPushSubscription:
    """Create or refresh one web push subscription for the owner."""
    endpoint = endpoint.strip()
    hashed_endpoint = _endpoint_hash(endpoint)
    stmt = select(WebPushSubscription).where(
        WebPushSubscription.user_id == user_id,
        WebPushSubscription.endpoint_hash == hashed_endpoint,
    )
    result = await session.execute(stmt.limit(1))
    record = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if record is None:
        record = WebPushSubscription(
            user_id=user_id,
            endpoint=endpoint,
            endpoint_hash=hashed_endpoint,
            auth_key=auth_key,
            p256dh_key=p256dh_key,
            expiration_time=expiration_time,
            user_agent=user_agent,
            status="active",
            failure_count=0,
            last_seen_at=now,
            metadata_=metadata or {},
        )
        await _session_add(session, record)
        await session.flush()
        return record

    record.endpoint = endpoint
    record.auth_key = auth_key
    record.p256dh_key = p256dh_key
    record.expiration_time = expiration_time
    record.user_agent = user_agent
    record.status = "active"
    record.deleted_at = None
    record.last_seen_at = now
    record.metadata_ = metadata or {}
    record.updated_at = now
    if record.failure_count:
        record.failure_count = 0
        record.last_error = None
    await session.flush()
    return record


async def revoke_web_push_subscription(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    user_id: str,
) -> bool:
    """Revoke one subscription without destroying delivery history."""
    record = await get_web_push_subscription(
        session,
        subscription_id=subscription_id,
        user_id=user_id,
    )
    if record is None:
        return False
    now = datetime.now(UTC)
    record.status = "revoked"
    record.deleted_at = now
    record.updated_at = now
    await session.flush()
    return True


async def mark_web_push_subscription_success(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
) -> None:
    """Mark one subscription delivery as successful."""
    record = await session.get(WebPushSubscription, subscription_id)
    if record is None:
        return
    now = datetime.now(UTC)
    record.status = "active"
    record.failure_count = 0
    record.last_error = None
    record.last_success_at = now
    record.last_seen_at = now
    record.updated_at = now
    await session.flush()


async def mark_web_push_subscription_failure(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    error_message: str,
    revoke: bool = False,
) -> None:
    """Record a failed delivery attempt for one subscription."""
    record = await session.get(WebPushSubscription, subscription_id)
    if record is None:
        return
    now = datetime.now(UTC)
    record.failure_count = int(record.failure_count or 0) + 1
    record.last_error = error_message[:500]
    record.last_failure_at = now
    record.updated_at = now
    if revoke:
        record.status = "revoked"
        record.deleted_at = now
    else:
        record.status = "error"
    await session.flush()


async def count_active_web_push_subscriptions(
    session: AsyncSession,
    *,
    user_id: str,
) -> int:
    """Count non-revoked subscriptions for the owner."""
    stmt = (
        select(func.count())
        .select_from(WebPushSubscription)
        .where(
            WebPushSubscription.user_id == user_id,
            not_deleted(WebPushSubscription),
            WebPushSubscription.status != "revoked",
        )
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)
