"""Execution helpers for scheduled actions and proactive runs."""

from __future__ import annotations

import uuid

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.domain.models import MessageInput
from src.app.domain.services.chat import persist_recorded_trace, process_message
from src.app.domain.services.web_push import dispatch_web_push_for_notification
from src.app.persistence.models import NotificationRecord, ScheduledAction
from src.app.persistence.repositories.scheduled_actions import (
    create_scheduled_action_run,
    mark_scheduled_action_executed,
    update_scheduled_action_run,
)

logger = structlog.get_logger()


async def execute_scheduled_action(
    session: AsyncSession,
    *,
    client: AsyncAnthropic,
    action: ScheduledAction,
) -> str:
    """Execute one scheduled action through the existing chat runtime."""
    workflow_uuid = uuid.uuid4()
    scheduled_run = await create_scheduled_action_run(
        session,
        action_id=action.id,
        workflow_id=workflow_uuid,
        status="running",
        payload={"delivery_channel": action.delivery_channel},
    )
    await session.commit()

    request_id = str(uuid.uuid4())
    message = MessageInput(
        content=action.prompt,
        source="api",
        user_id=action.user_id,
        metadata={
            "request_id": request_id,
            "workflow_id": str(workflow_uuid),
            "scheduled_action_id": str(action.id),
            "scheduled_action_run_id": str(scheduled_run.id),
            "scheduled_delivery_channel": action.delivery_channel,
        },
    )

    try:
        response = await process_message(message, client, session)
        await persist_recorded_trace(session, message.metadata)
        result_summary = response.content[:500]
        if response.metadata.get("confirmation_required"):
            result_summary = (
                f"Approval required for scheduled action '{action.title}'. {response.content[:400]}"
            )
        await update_scheduled_action_run(
            session,
            run_id=scheduled_run.id,
            status="completed",
            result_summary=result_summary,
            payload={
                "response_metadata": response.metadata,
                "workflow_id": str(workflow_uuid),
            },
        )
        await mark_scheduled_action_executed(
            session,
            action=action,
            result_summary=result_summary,
        )
        notification = NotificationRecord(
            message=f"{action.title}: {result_summary}",
            priority="P2",
            category="proactive",
            status="unread",
        )
        session.add(notification)
        await session.commit()
        try:
            await dispatch_web_push_for_notification(
                session,
                user_id=action.user_id,
                notification=notification,
            )
        except Exception:
            logger.warning("scheduled_action_web_push_dispatch_failed", exc_info=True)
        return result_summary
    except Exception as exc:
        await session.rollback()
        await update_scheduled_action_run(
            session,
            run_id=scheduled_run.id,
            status="failed",
            error_message=str(exc),
            payload={"workflow_id": str(workflow_uuid)},
        )
        notification = NotificationRecord(
            message=f"Scheduled action failed: {action.title}",
            priority="P1",
            category="proactive",
            status="unread",
        )
        session.add(notification)
        await session.commit()
        try:
            await dispatch_web_push_for_notification(
                session,
                user_id=action.user_id,
                notification=notification,
            )
        except Exception:
            logger.warning("scheduled_action_failure_web_push_dispatch_failed", exc_info=True)
        raise
