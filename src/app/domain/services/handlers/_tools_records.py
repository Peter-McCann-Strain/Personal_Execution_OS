"""Best-effort persistence for tool policy, approvals, receipts, and checkpoints."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.hitl import ApprovalResult, build_approval_span
from src.app.domain.models import (
    MessageInput,
    PendingToolPlan,
    PolicyDecision,
    Specialist,
    ToolInvocationPlan,
)
from src.app.domain.services.handlers._tools_planning import optional_string
from src.app.persistence.models import ToolReceipt

logger = structlog.get_logger()


async def persist_approval_span(
    session: AsyncSession | None,
    *,
    result: ApprovalResult,
    plan: ToolInvocationPlan,
    trace_id: str | None,
) -> None:
    """Record an approval span without making execution depend on telemetry."""
    if session is None or trace_id is None:
        return
    try:
        from src.app.persistence.repositories.traces import create_trace_spans

        span = build_approval_span(
            result=result,
            tool_name=plan.public_name,
            trace_id=trace_id,
            specialist=Specialist.TOOLS.value,
            original_args=plan.arguments,
        )
        await create_trace_spans(session, [span])
    except Exception:
        logger.warning("hitl_approval_span_persist_failed", exc_info=True)


async def maybe_get_existing_receipt(
    session: AsyncSession | None,
    idempotency_key: str,
) -> ToolReceipt | None:
    if session is None:
        return None
    try:
        from src.app.domain.services.handlers import tools as facade

        receipt = await facade.get_tool_receipt_by_idempotency_key(session, idempotency_key)
        if receipt is None or not isinstance(getattr(receipt, "idempotency_key", None), str):
            return None
        return receipt
    except Exception:
        logger.warning("tool_receipt_lookup_failed", exc_info=True)
        return None


async def maybe_create_tool_receipt(
    session: AsyncSession | None,
    *,
    plan: ToolInvocationPlan,
    result: dict[str, Any],
    trace_id: str | None,
    interaction_id: str | None,
) -> None:
    if session is None:
        return
    try:
        from src.app.domain.services.handlers import tools as facade

        content = result.get("content", "")
        is_error = bool(result.get("is_error"))
        await facade.create_tool_receipt(
            session,
            plan=plan,
            status="failed" if is_error else "executed",
            trace_id=trace_id,
            interaction_id=interaction_id,
            result_summary=None if is_error else str(content),
            error_message=str(content) if is_error else None,
        )
    except Exception:
        logger.warning("tool_receipt_persist_failed", exc_info=True)


async def persist_policy_decision(
    session: AsyncSession | None,
    *,
    message: MessageInput,
    decision: PolicyDecision,
) -> None:
    if session is None:
        return
    try:
        from src.app.domain.services.handlers import tools as facade

        await facade.create_policy_decision(
            session,
            decision,
            workflow_id=optional_string(message.metadata.get("workflow_id")),
            trace_id=optional_string(message.metadata.get("trace_id")),
            specialist=Specialist.TOOLS.value,
        )
    except Exception:
        logger.warning("policy_decision_persist_failed", exc_info=True)


async def persist_checkpoint(
    session: AsyncSession | None,
    *,
    workflow_id: str | None,
    payload: dict[str, Any],
) -> object | None:
    if session is None or workflow_id is None:
        return None
    try:
        from src.app.domain.services.handlers import tools as facade

        return await facade.create_workflow_checkpoint(
            session,
            workflow_id=workflow_id,
            checkpoint_kind="tool_confirmation",
            status="pending",
            payload=payload,
        )
    except Exception:
        logger.warning("workflow_checkpoint_persist_failed", exc_info=True)
        return None


async def resolve_pending_checkpoint(
    session: AsyncSession | None,
    plan: PendingToolPlan,
    *,
    status: str,
) -> None:
    if session is None:
        return
    try:
        from src.app.domain.services.handlers import tools as facade

        updated = await facade.update_workflow_checkpoint(
            session,
            checkpoint_id=plan.checkpoint_id,
            workflow_id=None if plan.checkpoint_id else plan.workflow_id,
            checkpoint_kind="tool_confirmation",
            from_status="pending",
            status=status,
        )
        if not updated:
            logger.info(
                "workflow_checkpoint_not_resolved",
                checkpoint_id=plan.checkpoint_id,
                workflow_id=plan.workflow_id,
                target_status=status,
            )
    except Exception:
        logger.warning("workflow_checkpoint_resolution_failed", exc_info=True)
