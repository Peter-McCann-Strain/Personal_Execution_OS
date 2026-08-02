"""Durable workflow, approval, and trace records for the chat service."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.telemetry import get_telemetry
from src.app.core.trace import TraceRecorder
from src.app.domain.models import ChatResponse, PendingToolPlan, WorkflowState
from src.app.persistence.repositories.runtime_records import (
    create_approval_request,
    create_workflow_run,
    create_workflow_run_step,
    get_pending_approval_request_for_checkpoint,
    resolve_approval_request,
    update_workflow_run,
)
from src.app.persistence.repositories.traces import create_trace_spans

logger = structlog.get_logger()


async def upsert_workflow_run_record(
    session: AsyncSession,
    *,
    workflow_id: str,
    status: str,
    source: str,
    user_id: str,
    message_content: str,
    trace_id: str | None,
    interaction_id: str | None = None,
    specialist: str | None = None,
    response_id: str | None = None,
    flags: list[str] | None = None,
    details: dict | None = None,
) -> bool:
    """Create or update the workflow run backing the current interaction."""
    updated = await update_workflow_run(
        session,
        workflow_id,
        status=status,
        specialist=specialist,
        trace_id=trace_id,
        response_id=response_id,
        details=details,
    )
    if updated:
        return True

    await create_workflow_run(
        session,
        WorkflowState(
            workflow_id=workflow_id,
            status=status,
            source=source,
            user_id=user_id,
            message_content=message_content,
            trace_id=trace_id,
            interaction_id=interaction_id,
            specialist=specialist,
            flags=flags or [],
            details=details or {},
        ),
    )
    return True


async def record_workflow_step(
    session: AsyncSession,
    *,
    workflow_id: str,
    step_type: str,
    title: str,
    status: str = "completed",
    details: dict | None = None,
) -> None:
    """Persist a workflow timeline step without breaking the main request on failure."""
    try:
        await create_workflow_run_step(
            session,
            workflow_id=workflow_id,
            step_type=step_type,
            title=title,
            status=status,
            details=details or {},
        )
    except Exception:
        logger.warning("workflow_step_persist_failed", exc_info=True)


async def sync_approval_request_for_response(
    session: AsyncSession,
    *,
    workflow_id: str,
    pending_tool_plan: PendingToolPlan | None,
    pending_resolution: str | None,
    response: ChatResponse,
) -> str | None:
    """Create or resolve product-level approval requests around tool checkpoints."""
    checkpoint_id = pending_tool_plan.checkpoint_id if pending_tool_plan is not None else None
    if response.metadata.get("confirmation_required"):
        raw_pending_plan = response.metadata.get("pending_tool_plan")
        if isinstance(raw_pending_plan, dict):
            checkpoint_id = raw_pending_plan.get("checkpoint_id") or checkpoint_id
        existing = await get_pending_approval_request_for_checkpoint(
            session,
            workflow_id=workflow_id,
            checkpoint_id=checkpoint_id,
        )
        if existing is None:
            tool_names = response.metadata.get("tools_pending") or []
            approval = await create_approval_request(
                session,
                workflow_id=workflow_id,
                checkpoint_id=checkpoint_id,
                title="Approval required to continue",
                description=(
                    f"Confirm before executing: {', '.join(tool_names)}"
                    if isinstance(tool_names, list) and tool_names
                    else "Confirm before executing the pending tool action."
                ),
                payload={
                    "tool_names": tool_names,
                    "response_excerpt": response.content[:300],
                },
            )
            response.metadata["approval_request_id"] = str(approval.id)
            return str(approval.id)
        return None

    if pending_resolution is None or checkpoint_id is None:
        return None

    existing = await get_pending_approval_request_for_checkpoint(
        session,
        workflow_id=workflow_id,
        checkpoint_id=checkpoint_id,
    )
    if existing is None:
        return None
    await resolve_approval_request(
        session,
        approval_id=str(existing.id),
        status="approved" if pending_resolution == "confirm" else "rejected",
        payload={
            **(existing.payload or {}),
            "response_excerpt": response.content[:300],
        },
    )
    return None


async def persist_recorded_trace(
    session: AsyncSession,
    metadata: dict,
) -> int:
    """Persist any recorded spans attached to a message metadata dict."""
    recorder = metadata.get("_trace_recorder")
    if not isinstance(recorder, TraceRecorder):
        return 0
    if metadata.get("_trace_persisted"):
        return 0
    if not recorder.spans:
        return 0

    await create_trace_spans(
        session,
        [span.to_record() for span in recorder.spans],
    )
    await session.commit()
    get_telemetry().record_trace(recorder)
    metadata["_trace_persisted"] = True
    return len(recorder.spans)
