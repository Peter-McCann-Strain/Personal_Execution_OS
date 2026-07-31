"""Owner-scoped web push config and subscription routes."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import Principal, get_current_principal, get_db
from src.app.core.exceptions import NotFoundError
from src.app.domain.services.web_push import web_push_enabled, web_push_public_key
from src.app.persistence.models import AuditEvent, WebPushSubscription
from src.app.persistence.repositories.web_push_subscriptions import (
    count_active_web_push_subscriptions,
    list_web_push_subscriptions,
    revoke_web_push_subscription,
    upsert_web_push_subscription,
)

router = APIRouter()


class WebPushConfigDTO(BaseModel):
    enabled: bool
    public_key: str | None
    active_subscription_count: int


class WebPushKeysBody(BaseModel):
    auth: str
    p256dh: str


class RegisterWebPushSubscriptionBody(BaseModel):
    endpoint: str
    keys: WebPushKeysBody
    expiration_time: int | None = None
    metadata: dict[str, Any] | None = None


class WebPushSubscriptionDTO(BaseModel):
    id: str
    status: str
    endpoint_preview: str
    endpoint_host: str | None
    expiration_time: str | None
    user_agent: str | None
    failure_count: int
    last_seen_at: str | None
    last_success_at: str | None
    last_failure_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str


def _coerce_expiration_time(raw: int | None) -> datetime | None:
    if raw is None:
        return None
    if raw <= 0:
        return None
    return datetime.fromtimestamp(raw / 1000, tz=UTC)


def _endpoint_preview(endpoint: str) -> str:
    trimmed = endpoint.strip()
    if len(trimmed) <= 42:
        return trimmed
    return f"{trimmed[:28]}...{trimmed[-10:]}"


def _endpoint_host(endpoint: str) -> str | None:
    try:
        return urlparse(endpoint).netloc or None
    except Exception:
        return None


def _to_dto(record: WebPushSubscription) -> WebPushSubscriptionDTO:
    return WebPushSubscriptionDTO(
        id=str(record.id),
        status=record.status,
        endpoint_preview=_endpoint_preview(record.endpoint),
        endpoint_host=_endpoint_host(record.endpoint),
        expiration_time=record.expiration_time.isoformat() if record.expiration_time else None,
        user_agent=record.user_agent,
        failure_count=int(record.failure_count or 0),
        last_seen_at=record.last_seen_at.isoformat() if record.last_seen_at else None,
        last_success_at=record.last_success_at.isoformat() if record.last_success_at else None,
        last_failure_at=record.last_failure_at.isoformat() if record.last_failure_at else None,
        last_error=record.last_error,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


async def _session_add(session: AsyncSession, instance: object) -> None:
    result = session.add(instance)
    if inspect.isawaitable(result):
        await result


def _principal_user_ref(principal: Principal) -> str:
    return principal.external_subject or principal.subject


async def _record_web_push_audit_event(
    session: AsyncSession,
    *,
    principal: Principal,
    event_type: str,
    subscription_id: uuid.UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    await _session_add(
        session,
        AuditEvent(
            account_id=principal.account_id,
            user_id=principal.user_id,
            event_type=event_type,
            actor_type="user",
            resource_type="web_push_subscription",
            resource_id=str(subscription_id),
            metadata_=metadata or {},
        ),
    )


@router.get("/notifications/push/config", response_model=WebPushConfigDTO)
async def get_web_push_config(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> WebPushConfigDTO:
    """Return public config needed for browser push registration."""
    user_id = _principal_user_ref(principal)
    enabled = web_push_enabled()
    return WebPushConfigDTO(
        enabled=enabled,
        public_key=web_push_public_key() if enabled else None,
        active_subscription_count=(
            await count_active_web_push_subscriptions(session, user_id=user_id) if enabled else 0
        ),
    )


@router.get(
    "/notifications/push/subscriptions",
    response_model=list[WebPushSubscriptionDTO],
)
async def get_web_push_subscriptions(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> list[WebPushSubscriptionDTO]:
    """List active owner-scoped web push subscriptions."""
    user_id = _principal_user_ref(principal)
    rows = await list_web_push_subscriptions(session, user_id=user_id)
    return [_to_dto(row) for row in rows]


@router.post(
    "/notifications/push/subscriptions",
    response_model=WebPushSubscriptionDTO,
)
async def register_web_push_subscription(
    body: RegisterWebPushSubscriptionBody,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> WebPushSubscriptionDTO:
    """Create or refresh one browser push subscription."""
    user_id = _principal_user_ref(principal)
    record = await upsert_web_push_subscription(
        session,
        user_id=user_id,
        endpoint=body.endpoint,
        auth_key=body.keys.auth,
        p256dh_key=body.keys.p256dh,
        expiration_time=_coerce_expiration_time(body.expiration_time),
        user_agent=request.headers.get("user-agent"),
        metadata=body.metadata,
    )
    await _record_web_push_audit_event(
        session,
        principal=principal,
        event_type="web_push.subscription_registered",
        subscription_id=record.id,
        metadata={
            "endpoint_host": _endpoint_host(record.endpoint),
            "user_agent": request.headers.get("user-agent"),
            "metadata_keys": sorted((body.metadata or {}).keys()),
        },
    )
    await session.commit()
    return _to_dto(record)


@router.delete("/notifications/push/subscriptions/{subscription_id}", status_code=204)
async def delete_web_push_subscription(
    subscription_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke one browser push subscription."""
    user_id = _principal_user_ref(principal)
    revoked = await revoke_web_push_subscription(
        session,
        subscription_id=subscription_id,
        user_id=user_id,
    )
    if not revoked:
        raise NotFoundError(f"Web push subscription not found: {subscription_id}")
    await _record_web_push_audit_event(
        session,
        principal=principal,
        event_type="web_push.subscription_revoked",
        subscription_id=subscription_id,
    )
    await session.commit()
    return Response(status_code=204)
