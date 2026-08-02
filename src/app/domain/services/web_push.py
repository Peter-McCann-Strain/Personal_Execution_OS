"""Best-effort owner-scoped web push delivery."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import get_settings
from src.app.persistence.models import ApprovalRequest, NotificationRecord
from src.app.persistence.repositories.runtime_records import get_approval_request_by_id
from src.app.persistence.repositories.web_push_subscriptions import (
    list_web_push_subscriptions,
    mark_web_push_subscription_failure,
    mark_web_push_subscription_success,
)

logger = structlog.get_logger()


@runtime_checkable
class _WebPushSender(Protocol):
    def __call__(
        self,
        *,
        subscription_info: dict[str, object],
        data: str,
        vapid_private_key: str,
        vapid_claims: dict[str, str],
        ttl: int,
    ) -> object: ...


@dataclass(slots=True)
class WebPushDispatchSummary:
    """Small delivery summary for logs and tests."""

    attempted: int = 0
    delivered: int = 0
    failed: int = 0
    skipped: int = 0


def web_push_enabled() -> bool:
    """Return True when VAPID-backed web push is configured."""
    return get_settings().web_push_configured


def web_push_public_key() -> str:
    """Return the configured VAPID public key, if any."""
    return get_settings().web_push_public_key.strip()


def _load_webpush() -> tuple[_WebPushSender | None, type[Exception] | None]:
    try:
        from pywebpush import WebPushException, webpush
    except Exception:
        return None, None
    sender: object = webpush
    if not isinstance(sender, _WebPushSender):
        return None, None
    return sender, WebPushException


def _should_revoke_subscription(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in {404, 410}:
        return True

    message = str(exc).casefold()
    return (
        "410" in message
        or "404" in message
        or "expired" in message
        or "unsubscribed" in message
        or "not found" in message
        or "gone" in message
    )


def _serialize_payload(
    payload: dict[str, Any],
    *,
    include_content_preview: bool = False,
) -> str:
    body = {
        "title": (
            str(payload.get("title") or "Execution OS")
            if include_content_preview
            else "Execution OS"
        ),
        "body": (
            str(payload.get("body") or "Open Execution OS to view")
            if include_content_preview
            else "Open Execution OS to view"
        ),
        "tag": str(payload.get("tag") or "brain-update"),
        "data": payload.get("data") or {"url": payload.get("url") or "/pulse"},
    }
    return json.dumps(body, separators=(",", ":"))


async def dispatch_web_push_to_user(
    session: AsyncSession,
    *,
    user_id: str,
    payload: dict[str, Any],
) -> WebPushDispatchSummary:
    """Deliver one push payload to all active subscriptions for the owner.

    This function is intentionally best-effort and should be called only after
    the caller's main transaction has already committed successfully.
    """
    summary = WebPushDispatchSummary()
    settings = get_settings()
    if not settings.web_push_configured:
        summary.skipped += 1
        return summary

    subscriptions = await list_web_push_subscriptions(session, user_id=user_id)
    if not subscriptions:
        summary.skipped += 1
        return summary

    webpush, webpush_exc = _load_webpush()
    if not isinstance(webpush, _WebPushSender):
        logger.warning("web_push_library_unavailable")
        summary.skipped += len(subscriptions)
        return summary

    data = _serialize_payload(
        payload,
        include_content_preview=settings.web_push_content_preview_enabled,
    )
    for subscription in subscriptions:
        summary.attempted += 1
        try:
            await asyncio.to_thread(
                webpush,
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "auth": subscription.auth_key,
                        "p256dh": subscription.p256dh_key,
                    },
                },
                data=data,
                vapid_private_key=settings.web_push_private_key.get_secret_value(),
                vapid_claims={"sub": settings.web_push_subject},
                ttl=60,
            )
            await mark_web_push_subscription_success(
                session,
                subscription_id=subscription.id,
            )
            summary.delivered += 1
        except Exception as exc:
            is_webpush_exc = webpush_exc is not None and isinstance(exc, webpush_exc)
            revoke = _should_revoke_subscription(exc)
            await mark_web_push_subscription_failure(
                session,
                subscription_id=subscription.id,
                error_message=str(exc),
                revoke=revoke,
            )
            logger.warning(
                "web_push_delivery_failed",
                subscription_id=str(subscription.id),
                revoke=revoke,
                webpush_exception=is_webpush_exc,
                error_class=type(exc).__name__,
            )
            summary.failed += 1

    if summary.attempted:
        try:
            await session.commit()
        except Exception:
            logger.warning("web_push_delivery_status_commit_failed", exc_info=True)
            await session.rollback()
    return summary


async def dispatch_web_push_for_notification(
    session: AsyncSession,
    *,
    user_id: str,
    notification: NotificationRecord,
    url: str = "/pulse",
) -> WebPushDispatchSummary:
    """Send one proactive-notification push."""
    return await dispatch_web_push_to_user(
        session,
        user_id=user_id,
        payload={
            "title": "Pulse update",
            "body": notification.message,
            "tag": f"notification:{notification.id}",
            "data": {"url": url, "notification_id": str(notification.id)},
        },
    )


async def dispatch_web_push_for_approval(
    session: AsyncSession,
    *,
    user_id: str,
    approval_id: str,
    url: str = "/pulse",
) -> WebPushDispatchSummary:
    """Send one approval-required push if the approval is still pending."""
    approval = await get_approval_request_by_id(session, approval_id)
    if approval is None or approval.status != "pending":
        return WebPushDispatchSummary(skipped=1)

    return await dispatch_web_push_to_user(
        session,
        user_id=user_id,
        payload=_approval_payload(approval, url=url),
    )


def _approval_payload(approval: ApprovalRequest, *, url: str) -> dict[str, Any]:
    description = approval.description or "The assistant is waiting for confirmation."
    return {
        "title": approval.title or "Approval needed",
        "body": description[:180],
        "tag": f"approval:{approval.id}",
        "data": {
            "url": url,
            "approval_id": str(approval.id),
            "workflow_id": str(approval.workflow_id),
        },
    }
