"""Resume or reject persisted MCP plans after explicit user confirmation."""

from __future__ import annotations

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.async_utils import maybe_await
from src.app.core.confirmation import is_explicit_confirmation, is_explicit_rejection
from src.app.core.tool_contracts import build_tool_specs
from src.app.domain.constants import PolicyDecisionOutcome, TrustLabel
from src.app.domain.models import (
    ChatResponse,
    MessageInput,
    PendingToolPlan,
    PolicyDecision,
)
from src.app.domain.runtime import AgentRuntimeConfig

logger = structlog.get_logger()


async def resume_pending_tool_plan(
    *,
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession | None,
    manager: object,
    runtime: AgentRuntimeConfig,
    pending_plan: PendingToolPlan,
    trace_id: str | None,
) -> ChatResponse | None:
    """Handle a confirmation turn, or return ``None`` when this is a new request."""
    from src.app.domain.services.handlers import tools as facade

    if is_explicit_rejection(message.content):
        await facade._persist_policy_decision(
            session,
            message=message,
            decision=PolicyDecision(
                policy_name="tool_confirmation",
                decision=PolicyDecisionOutcome.DENY,
                reason="User explicitly rejected the pending mutating tool plan.",
                subject_type="pending_tool_plan",
                subject_id=pending_plan.plan_id,
                metadata={"tool_count": len(pending_plan.tool_calls)},
            ),
        )
        await facade._resolve_pending_checkpoint(session, pending_plan, status="cancelled")
        return ChatResponse(
            content="Okay. I have cancelled the pending tool action.",
            agent="tools",
            metadata={
                "confirmation_required": False,
                "mcp_execution": False,
                "pending_tool_plan_cleared": True,
                "tool_count": len(pending_plan.tool_calls),
                "tool_calls": [
                    {"name": call.name, "status": "cancelled"} for call in pending_plan.tool_calls
                ],
                "tool_events": [
                    {"name": call.name, "status": "cancelled", "details": {}}
                    for call in pending_plan.tool_calls
                ],
            },
        )

    if not is_explicit_confirmation(message.content):
        return None

    pending_trust = facade._coerce_trust_label(pending_plan.trust_label)
    if pending_trust == TrustLabel.UNTRUSTED_EXTERNAL:
        await facade._persist_policy_decision(
            session,
            message=message,
            decision=PolicyDecision(
                policy_name="tool_trust_boundary",
                decision=PolicyDecisionOutcome.DENY,
                reason=(
                    "Pending tool plan originated from untrusted external content "
                    "and cannot be executed directly."
                ),
                subject_type="pending_tool_plan",
                subject_id=pending_plan.plan_id,
                metadata={"tool_count": len(pending_plan.tool_calls)},
            ),
        )
        await facade._resolve_pending_checkpoint(session, pending_plan, status="cancelled")
        return ChatResponse(
            content=(
                "I can't run this pending tool plan because it came from untrusted "
                "external content. Tell me directly what action you want, and I'll "
                "plan it again."
            ),
            agent="tools",
            metadata={
                "confirmation_required": False,
                "mcp_execution": False,
                "pending_tool_plan_cleared": True,
                "tool_count": len(pending_plan.tool_calls),
                "tool_calls": [
                    {"name": call.name, "status": "blocked"} for call in pending_plan.tool_calls
                ],
                "tool_events": [
                    {
                        "name": call.name,
                        "status": "blocked",
                        "details": {"reason": "untrusted_external_content"},
                    }
                    for call in pending_plan.tool_calls
                ],
            },
        )

    list_tools = getattr(manager, "list_tools", None)
    mcp_tools_raw = await maybe_await(list_tools()) if callable(list_tools) else []
    if not isinstance(mcp_tools_raw, list):
        mcp_tools_raw = []
    allowed_tools = facade._filter_allowed_tools(mcp_tools_raw, runtime)
    tool_specs = build_tool_specs(
        allowed_tools,
        tool_metadata={
            facade._tool_full_name(tool): dict(tool.get("tool_metadata") or {})
            for tool in allowed_tools
        },
    )
    tool_use_blocks = facade._enforce_confirmation_policy(
        facade._pending_plan_to_plans(pending_plan, tool_specs),
        runtime=runtime,
    )
    await facade._persist_policy_decision(
        session,
        message=message,
        decision=PolicyDecision(
            policy_name="tool_confirmation",
            decision=PolicyDecisionOutcome.ALLOW,
            reason="User explicitly confirmed the pending mutating tool plan.",
            subject_type="pending_tool_plan",
            subject_id=pending_plan.plan_id,
            metadata={"tool_count": len(tool_use_blocks)},
        ),
    )
    await facade._resolve_pending_checkpoint(session, pending_plan, status="confirmed")
    tool_results = await facade._execute_with_receipts(
        session,
        manager=manager,
        plans=tool_use_blocks,
        trace_id=trace_id,
        interaction_id=facade._optional_string(message.metadata.get("interaction_id")),
        confirmed_mutations=True,
    )
    logger.info(
        "mcp_tools_resumed_from_confirmation",
        tool_count=len(tool_use_blocks),
        plan_id=pending_plan.plan_id,
        errors=sum(1 for result in tool_results if result.get("is_error")),
    )

    return await facade._summarise_executed_tools(
        message=message,
        client=client,
        tool_use_blocks=tool_use_blocks,
        tool_results=tool_results,
        resumed_from_confirmation=True,
    )
