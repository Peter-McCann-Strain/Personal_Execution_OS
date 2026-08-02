"""Receipt-aware MCP execution and human approval gating."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.exceptions import MCPError
from src.app.core.hitl import (
    ApprovalResult,
    SyntheticCancelledResult,
    build_interrupt_payload,
    is_auto_approved,
    parse_resume_value,
    requires_approval,
)
from src.app.domain.constants import ToolMutationClass
from src.app.domain.models import ToolInvocationPlan

logger = structlog.get_logger()


async def execute_with_receipts(
    session: AsyncSession | None,
    *,
    manager: Any,
    plans: list[ToolInvocationPlan],
    trace_id: str | None,
    interaction_id: str | None,
    confirmed_mutations: bool,
) -> list[dict[str, Any]]:
    """Execute validated plans while enforcing approval and idempotency receipts."""
    from src.app.domain.services.handlers import tools as facade

    if (
        any(str(plan.mutation_class) == str(ToolMutationClass.MUTATING) for plan in plans)
        and not confirmed_mutations
    ):
        raise MCPError("Mutating tool execution is blocked until explicit user confirmation.")

    cached_results: dict[str, dict[str, Any]] = {}
    cancelled_results: dict[str, dict[str, Any]] = {}
    plans_to_execute: list[ToolInvocationPlan] = []

    for plan in plans:
        existing_receipt = await facade._maybe_get_existing_receipt(
            session,
            plan.idempotency_key,
        )
        if existing_receipt is not None:
            cached_results[plan.idempotency_key] = {
                "type": "tool_result",
                "tool_use_id": plan.tool_id,
                "content": (
                    existing_receipt.result_summary or "Previously executed tool result reused."
                ),
                "is_error": bool(existing_receipt.error_message),
                "idempotency_key": plan.idempotency_key,
                "argument_hash": existing_receipt.argument_hash,
            }
            continue

        if confirmed_mutations:
            plans_to_execute.append(plan)
            continue

        gated_plan = await facade._route_plan_through_hitl_gate(
            session,
            plan=plan,
            trace_id=trace_id,
        )
        if isinstance(gated_plan, SyntheticCancelledResult):
            cancelled_results[plan.idempotency_key] = gated_plan.to_tool_result() | {
                "idempotency_key": plan.idempotency_key,
                "argument_hash": plan.argument_hash,
            }
            continue
        plans_to_execute.append(gated_plan)

    executed_results = await facade.execute_tool_calls(manager, plans_to_execute)
    executed_by_idempotency = {
        plan.idempotency_key: result
        for plan, result in zip(plans_to_execute, executed_results, strict=True)
    }

    for plan in plans_to_execute:
        await facade._maybe_create_tool_receipt(
            session,
            plan=plan,
            result=executed_by_idempotency[plan.idempotency_key],
            trace_id=trace_id,
            interaction_id=interaction_id,
        )

    results: list[dict[str, Any]] = []
    for plan in plans:
        if plan.idempotency_key in cancelled_results:
            results.append(cancelled_results[plan.idempotency_key])
        elif plan.idempotency_key in cached_results:
            results.append(cached_results[plan.idempotency_key])
        else:
            results.append(executed_by_idempotency[plan.idempotency_key])
    return results


async def route_plan_through_hitl_gate(
    session: AsyncSession | None,
    *,
    plan: ToolInvocationPlan,
    trace_id: str | None,
) -> ToolInvocationPlan | SyntheticCancelledResult:
    """Approve, edit, cancel, or time out one plan before execution."""
    from src.app.config import get_settings
    from src.app.domain.services.approval_callbacks import (
        get_registry,
        wait_for_approval_decision,
    )
    from src.app.domain.services.handlers import tools as facade

    settings = get_settings()

    if not requires_approval(
        mutation_class=plan.mutation_class,
        requires_confirmation=bool(plan.requires_confirmation),
        settings=settings,
    ):
        return plan

    if is_auto_approved(
        tool_name=plan.public_name,
        args=dict(plan.arguments),
        settings=settings,
    ):
        auto_result = ApprovalResult(
            decision=ApprovalResult.AUTO_APPROVE,
            args=dict(plan.arguments),
            interrupt_id=plan.tool_id,
            reason="trusted_destination",
        )
        await facade._persist_approval_span(
            session,
            result=auto_result,
            plan=plan,
            trace_id=trace_id,
        )
        return plan.model_copy(
            update={
                "audit_metadata": {
                    **(plan.audit_metadata or {}),
                    "hitl_decision": ApprovalResult.AUTO_APPROVE,
                    "hitl_interrupt_id": plan.tool_id,
                }
            }
        )

    payload = build_interrupt_payload(
        tool_name=plan.public_name,
        args=dict(plan.arguments),
        interrupt_id=plan.tool_id,
        timeout_seconds=settings.hitl_timeout_seconds,
    )

    try:
        await facade._dispatch_approval_preview(payload=payload, plan=plan)
    except Exception:
        logger.debug("hitl_preview_dispatch_skipped", exc_info=True)

    get_registry()
    resume_value = await wait_for_approval_decision(
        interrupt_id=plan.tool_id,
        tool_name=plan.public_name,
        original_args=dict(plan.arguments),
        chat_id=None,
        timeout_seconds=settings.hitl_timeout_seconds,
    )
    decision_name, resolved_args, reason = parse_resume_value(
        resume_value,
        original_args=dict(plan.arguments),
    )
    decision = ApprovalResult(
        decision=decision_name,
        args=resolved_args,
        interrupt_id=plan.tool_id,
        reason=reason,
    )

    await facade._persist_approval_span(
        session,
        result=decision,
        plan=plan,
        trace_id=trace_id,
    )

    if not decision.should_run:
        cancellation_reason = decision.reason or "cancelled_by_user"
        logger.info(
            "hitl_cancelled_before_execution",
            tool=plan.public_name,
            decision=decision.decision,
            interrupt_id=decision.interrupt_id,
            reason=cancellation_reason,
        )
        return SyntheticCancelledResult(
            tool_name=plan.public_name,
            reason=cancellation_reason,
            interrupt_id=decision.interrupt_id,
        )

    audit_metadata = {
        **(plan.audit_metadata or {}),
        "hitl_interrupt_id": decision.interrupt_id,
    }
    if decision.decision == ApprovalResult.EDIT and decision.args != plan.arguments:
        audit_metadata["hitl_edited"] = True
        return plan.model_copy(
            update={
                "arguments": dict(decision.args),
                "audit_metadata": audit_metadata,
            }
        )

    audit_metadata["hitl_decision"] = decision.decision
    return plan.model_copy(update={"audit_metadata": audit_metadata})


async def dispatch_approval_preview(
    *,
    payload: dict[str, Any],
    plan: ToolInvocationPlan,
) -> None:
    """Transport hook for a pending approval preview."""
    _ = (payload, plan)
