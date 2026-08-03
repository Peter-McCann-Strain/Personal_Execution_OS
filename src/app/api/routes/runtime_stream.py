"""Authenticated runtime stream for live workflow and pulse updates."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import Principal, get_current_principal, get_db
from src.app.domain.constants import NotificationCategory, NotificationStatus, WorkflowStatus
from src.app.persistence.models import (
    ApprovalRequest,
    NotificationRecord,
    ScheduledAction,
    ScheduledActionRun,
    WebPushSubscription,
    WorkflowRun,
    not_deleted,
)

logger = structlog.get_logger()
router = APIRouter()


class RuntimeStreamSnapshot(BaseModel):
    generated_at: str
    workflow_revision: str | None
    workflow_total: int
    active_workflow_count: int
    approval_revision: str | None
    pending_approval_count: int
    notification_revision: str | None
    unread_notification_count: int
    proactive_unread_count: int
    scheduled_action_revision: str | None
    scheduled_action_count: int
    scheduled_action_run_revision: str | None
    scheduled_action_run_count: int
    web_push_revision: str | None
    web_push_subscription_count: int


def _as_iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _sse_event(event: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), default=str)
    return f"event: {event}\ndata: {body}\n\n".encode()


def _normalize_interval(
    raw_value: int, *, default_ms: int, minimum_ms: int, maximum_ms: int
) -> int:
    return max(min(raw_value or default_ms, maximum_ms), minimum_ms)


def _principal_user_ref(principal: Principal) -> str:
    return principal.external_subject or principal.subject


async def _build_runtime_stream_snapshot(
    session: AsyncSession,
    *,
    user_id: str,
) -> RuntimeStreamSnapshot:
    workflow_result = await session.execute(
        select(
            func.max(WorkflowRun.updated_at),
            func.count(WorkflowRun.id),
            func.count(WorkflowRun.id).filter(
                WorkflowRun.status.in_(
                    [
                        str(WorkflowStatus.RUNNING),
                        str(WorkflowStatus.INTERRUPTED),
                    ]
                )
            ),
        ).where(WorkflowRun.user_id == user_id)
    )
    workflow_revision, workflow_total, active_workflow_count = workflow_result.one()

    approval_result = await session.execute(
        select(
            func.max(ApprovalRequest.updated_at),
            func.count(ApprovalRequest.id).filter(ApprovalRequest.status == "pending"),
        )
        .select_from(ApprovalRequest)
        .join(WorkflowRun, ApprovalRequest.workflow_id == WorkflowRun.id)
        .where(WorkflowRun.user_id == user_id)
    )
    approval_revision, pending_approval_count = approval_result.one()

    notification_result = await session.execute(
        select(
            func.max(NotificationRecord.created_at),
            func.count(NotificationRecord.id).filter(
                NotificationRecord.status == str(NotificationStatus.UNREAD)
            ),
            func.count(NotificationRecord.id).filter(
                NotificationRecord.status == str(NotificationStatus.UNREAD),
                NotificationRecord.category == str(NotificationCategory.PROACTIVE),
            ),
        )
    )
    (
        notification_revision,
        unread_notification_count,
        proactive_unread_count,
    ) = notification_result.one()

    scheduled_action_result = await session.execute(
        select(
            func.max(ScheduledAction.updated_at),
            func.count(ScheduledAction.id),
        ).where(
            ScheduledAction.user_id == user_id,
            not_deleted(ScheduledAction),
        )
    )
    scheduled_action_revision, scheduled_action_count = scheduled_action_result.one()

    scheduled_action_run_result = await session.execute(
        select(
            func.max(ScheduledActionRun.created_at),
            func.count(ScheduledActionRun.id),
        )
        .select_from(ScheduledActionRun)
        .join(ScheduledAction, ScheduledActionRun.action_id == ScheduledAction.id)
        .where(
            ScheduledAction.user_id == user_id,
            not_deleted(ScheduledAction),
        )
    )
    scheduled_action_run_revision, scheduled_action_run_count = scheduled_action_run_result.one()

    web_push_result = await session.execute(
        select(
            func.max(WebPushSubscription.updated_at),
            func.count(WebPushSubscription.id),
        ).where(
            WebPushSubscription.user_id == user_id,
            not_deleted(WebPushSubscription),
            WebPushSubscription.status != "revoked",
        )
    )
    web_push_revision, web_push_subscription_count = web_push_result.one()

    return RuntimeStreamSnapshot(
        generated_at=datetime.now(UTC).isoformat(),
        workflow_revision=_as_iso(workflow_revision),
        workflow_total=int(workflow_total or 0),
        active_workflow_count=int(active_workflow_count or 0),
        approval_revision=_as_iso(approval_revision),
        pending_approval_count=int(pending_approval_count or 0),
        notification_revision=_as_iso(notification_revision),
        unread_notification_count=int(unread_notification_count or 0),
        proactive_unread_count=int(proactive_unread_count or 0),
        scheduled_action_revision=_as_iso(scheduled_action_revision),
        scheduled_action_count=int(scheduled_action_count or 0),
        scheduled_action_run_revision=_as_iso(scheduled_action_run_revision),
        scheduled_action_run_count=int(scheduled_action_run_count or 0),
        web_push_revision=_as_iso(web_push_revision),
        web_push_subscription_count=int(web_push_subscription_count or 0),
    )


@router.get("/runtime/stream")
async def runtime_stream(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    poll_interval_ms: int = Query(1_500, ge=250, le=10_000),
    heartbeat_interval_ms: int = Query(15_000, ge=2_000, le=60_000),
    max_events: int | None = Query(None, ge=1, le=100),
) -> StreamingResponse:
    """Stream small runtime snapshots when workflow or pulse state changes."""
    user_id = _principal_user_ref(principal)
    poll_interval_ms = _normalize_interval(
        poll_interval_ms,
        default_ms=1_500,
        minimum_ms=250,
        maximum_ms=10_000,
    )
    heartbeat_interval_ms = _normalize_interval(
        heartbeat_interval_ms,
        default_ms=15_000,
        minimum_ms=2_000,
        maximum_ms=60_000,
    )

    async def event_stream():
        last_signature: str | None = None
        elapsed_since_heartbeat_ms = 0
        emitted_events = 0

        yield _sse_event(
            "runtime_open",
            {
                "user_id": user_id,
                "poll_interval_ms": poll_interval_ms,
                "heartbeat_interval_ms": heartbeat_interval_ms,
            },
        )
        emitted_events += 1

        while True:
            if max_events is not None and emitted_events >= max_events:
                break
            if await request.is_disconnected():
                break

            try:
                snapshot = await _build_runtime_stream_snapshot(session, user_id=user_id)
                payload = snapshot.model_dump(mode="json")
                signature = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                if signature != last_signature:
                    yield _sse_event(
                        "runtime_snapshot" if last_signature is None else "runtime_update",
                        payload,
                    )
                    emitted_events += 1
                    last_signature = signature
                    elapsed_since_heartbeat_ms = 0
                elif elapsed_since_heartbeat_ms >= heartbeat_interval_ms:
                    yield _sse_event(
                        "runtime_heartbeat",
                        {"generated_at": datetime.now(UTC).isoformat()},
                    )
                    emitted_events += 1
                    elapsed_since_heartbeat_ms = 0
            except Exception:
                logger.warning("runtime_stream_snapshot_failed", exc_info=True)
                yield _sse_event(
                    "runtime_error",
                    {
                        "message": "Runtime updates are temporarily unavailable.",
                        "generated_at": datetime.now(UTC).isoformat(),
                    },
                )
                emitted_events += 1
                try:
                    await session.rollback()
                except Exception:
                    logger.warning("runtime_stream_rollback_failed", exc_info=True)

            await asyncio.sleep(poll_interval_ms / 1000)
            elapsed_since_heartbeat_ms += poll_interval_ms

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
