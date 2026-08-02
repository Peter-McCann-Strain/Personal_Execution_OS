"""MCP tool workflow orchestration.

The public compatibility surface remains in ``handlers.tools``.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.async_utils import maybe_await
from src.app.core.exceptions import MCPError
from src.app.core.mcp_client import MCPClientManager
from src.app.core.security import trust_label_for_message_source
from src.app.core.tool_contracts import build_tool_specs
from src.app.domain.constants import PolicyDecisionOutcome, TrustLabel
from src.app.domain.models import (
    ArtifactRecord,
    ChatResponse,
    Intent,
    MessageInput,
    PolicyDecision,
)
from src.app.domain.services.handlers._tools_pending import resume_pending_tool_plan

logger = structlog.get_logger()

# Module-level MCP client manager, registered once during application startup.
_mcp_client_manager: MCPClientManager | None = None


def set_mcp_client_manager(manager: MCPClientManager | None) -> None:
    """Register the MCP client manager for the tools handler.

    Called once during app lifespan after the manager connects to MCP servers.
    """
    global _mcp_client_manager
    _mcp_client_manager = manager


def get_mcp_client_manager() -> MCPClientManager | None:
    """Return the current MCP client manager, or None."""
    return _mcp_client_manager


async def handle_tools(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    _intent: Intent,
) -> ChatResponse:
    """Plan and execute tool calls for a user request via MCP."""
    from src.app.domain.services.handlers import tools as facade

    manager = facade.get_mcp_client_manager()

    if manager is None or not manager.connected:
        raise MCPError("MCP tool execution is unavailable in this runtime.")

    response = await facade._handle_tools_with_mcp(message, client, session, manager)

    try:
        await facade.enqueue_entity_extraction(
            episode_id=str(uuid.uuid4()),
            text_content=response.content,
        )
    except Exception as exc:
        logger.warning(
            "tools_entity_extraction_degraded",
            error=str(exc),
            exc_info=True,
        )
    try:
        await facade.create_artifact_record(
            session,
            user_id=message.user_id,
            artifact=ArtifactRecord(
                artifact_type="tool_summary",
                summary=response.content[:500],
                source_id=facade._optional_string(response.metadata.get("response_id")),
                trace_id=facade._optional_string(response.metadata.get("trace_id")),
                workflow_id=facade._optional_string(message.metadata.get("workflow_id")),
                payload={
                    "tool_calls": response.metadata.get("tool_calls", []),
                    "tool_events": response.metadata.get("tool_events", []),
                    "tool_count": response.metadata.get("tool_count", 0),
                    "errors": response.metadata.get("errors", 0),
                },
            ),
        )
    except Exception:
        logger.warning("tool_artifact_persist_failed", exc_info=True)

    return response


async def _handle_tools_with_mcp(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession | Any | None,
    manager: Any | None = None,
) -> ChatResponse:
    """Execute tool calls via MCP bridge and return a summary."""
    from src.app.config import get_settings
    from src.app.domain.services.handlers import tools as facade

    if manager is None:
        manager = session
        session = None

    settings = get_settings()
    runtime = facade._load_runtime_config(message)
    raw_trust_label = message.metadata.get("trust_label") or trust_label_for_message_source(
        message.source
    )
    trust_label = facade._coerce_trust_label(raw_trust_label)
    trace_id = facade._optional_string(message.metadata.get("trace_id"))
    workflow_id = facade._optional_string(message.metadata.get("workflow_id"))
    pending_plan = facade._load_pending_tool_plan(message)

    if pending_plan is not None:
        pending_response = await resume_pending_tool_plan(
            message=message,
            client=client,
            session=session,
            manager=manager,
            runtime=runtime,
            pending_plan=pending_plan,
            trace_id=trace_id,
        )
        if pending_response is not None:
            return pending_response

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

    # Get available MCP tools formatted for Claude
    anthropic_tools = facade.format_mcp_tools_for_anthropic(allowed_tools)

    if not anthropic_tools:
        raise MCPError("MCP is connected but no tools are available for execution.")

    # Ask Claude which tools to call, giving it the real MCP tool definitions.
    # We use call_llm() for retry, structlog logging, and prompt caching.
    from src.app.core.exceptions import LLMError

    instruction_risk = facade._detect_untrusted_instruction_risk(message)
    if instruction_risk:
        logger.warning("tool_request_contains_instruction_like_content")
        message.metadata.setdefault("safety_flags", []).append("instruction_like_content")
        await facade._persist_policy_decision(
            session,
            message=message,
            decision=PolicyDecision(
                policy_name="instruction_like_content",
                decision=PolicyDecisionOutcome.DEGRADED,
                reason="Tool request included instruction-like untrusted content markers.",
                subject_type="message",
                metadata={"source": message.source},
            ),
        )

    try:
        response = await facade.call_llm(
            client,
            model=settings.tools_model,
            max_tokens=settings.tools_plan_max_tokens,
            system="You are a tool-calling assistant. Use the provided tools to help the user.",
            messages=[{"role": "user", "content": message.content}],
            inject_personality=False,
            _tools=anthropic_tools,
        )
    except LLMError:
        raise

    # Extract tool_use blocks from the response
    tool_use_blocks = [
        {"id": block.id, "name": block.name, "input": block.input}
        for block in response.content
        if block.type == "tool_use"
    ]
    tool_use_blocks = facade._build_tool_invocation_plans(
        tool_use_blocks,
        tool_specs,
        runtime,
        trust_label=str(trust_label.value),
        workflow_id=workflow_id,
    )
    if instruction_risk and tool_use_blocks:
        tool_use_blocks = facade._enforce_instruction_risk_confirmation(tool_use_blocks)

    if not tool_use_blocks:
        if response.content:
            await facade._persist_policy_decision(
                session,
                message=message,
                decision=PolicyDecision(
                    policy_name="tool_validation",
                    decision=PolicyDecisionOutcome.DENY,
                    reason="Tool planner returned tool calls that failed runtime validation.",
                    subject_type="tool_plan",
                    metadata={"candidate_count": len(response.content)},
                ),
            )
        text_parts = [
            str(block.text)
            for block in response.content
            if getattr(block, "type", None) == "text" and hasattr(block, "text")
        ]
        if text_parts:
            return ChatResponse(
                content="\n".join(text_parts),
                agent="tools",
                metadata={"tool_count": 0, "mcp_execution": True},
            )
        raise MCPError("Tool planner returned no tool calls and no response text.")

    if trust_label == TrustLabel.UNTRUSTED_EXTERNAL:
        await facade._persist_policy_decision(
            session,
            message=message,
            decision=PolicyDecision(
                policy_name="tool_trust_boundary",
                decision=PolicyDecisionOutcome.DENY,
                reason=(
                    "Tool plans from untrusted external content are blocked until the "
                    "user restates the action request explicitly."
                ),
                subject_type="tool_plan",
                metadata={"tool_count": len(tool_use_blocks)},
            ),
        )
        return ChatResponse(
            content=(
                "I can use that external content as context, but I won't execute tools from it "
                "directly. Tell me explicitly what action you want me to take."
            ),
            agent="tools",
            metadata={
                "confirmation_required": False,
                "mcp_execution": False,
                "tool_count": len(tool_use_blocks),
                "tool_calls": [
                    {
                        "name": block.public_name,
                        "status": "blocked",
                        "idempotency_key": block.idempotency_key,
                        "argument_hash": block.argument_hash,
                        "audit": block.audit_metadata,
                    }
                    for block in tool_use_blocks
                ],
                "tool_events": [
                    {
                        "name": block.public_name,
                        "status": "blocked",
                        "details": {"reason": "untrusted_external_content"},
                    }
                    for block in tool_use_blocks
                ],
            },
        )

    confirmation_required = any(plan.requires_confirmation for plan in tool_use_blocks)
    if confirmation_required:
        tool_names = ", ".join(plan.public_name for plan in tool_use_blocks)
        pending_tool_plan = facade._to_pending_tool_plan(
            tool_use_blocks,
            message=message,
            trust_label=str(trust_label.value),
        )
        await facade._persist_policy_decision(
            session,
            message=message,
            decision=PolicyDecision(
                policy_name="tool_confirmation",
                decision=PolicyDecisionOutcome.REQUIRE_CONFIRMATION,
                reason="Mutating tool execution requires explicit user confirmation.",
                subject_type="pending_tool_plan",
                subject_id=pending_tool_plan.plan_id,
                metadata={"tool_count": len(tool_use_blocks)},
            ),
        )
        checkpoint = await facade._persist_checkpoint(
            session,
            workflow_id=workflow_id,
            payload=pending_tool_plan.model_dump(mode="json"),
        )
        pending_tool_plan = pending_tool_plan.model_copy(
            update={
                "workflow_id": workflow_id,
                "checkpoint_id": facade._optional_string(getattr(checkpoint, "id", None)),
            }
        )
        return ChatResponse(
            content=(
                "I'm ready to run these mutating tools, but I need your explicit "
                "confirmation first.\n\n"
                f"Planned tools: {tool_names}\n\nReply with 'yes' to continue or 'cancel' to stop."
            ),
            agent="tools",
            metadata={
                "confirmation_required": True,
                "tool_count": len(tool_use_blocks),
                "tools_pending": [block.public_name for block in tool_use_blocks],
                "mcp_execution": False,
                "pending_plan_id": pending_tool_plan.plan_id,
                "pending_tool_plan": pending_tool_plan.model_dump(mode="json"),
                "tool_calls": [
                    {
                        "name": block.public_name,
                        "status": "planned",
                        "idempotency_key": block.idempotency_key,
                        "argument_hash": block.argument_hash,
                        "audit": block.audit_metadata,
                    }
                    for block in tool_use_blocks
                ],
                "tool_events": [
                    {
                        "name": block.public_name,
                        "status": "planned",
                        "details": {
                            "idempotency_key": block.idempotency_key,
                            "argument_hash": block.argument_hash,
                            "requires_confirmation": True,
                        },
                    }
                    for block in tool_use_blocks
                ],
            },
        )

    # Execute tool calls via MCP bridge
    await facade._persist_policy_decision(
        session,
        message=message,
        decision=PolicyDecision(
            policy_name="tool_execution",
            decision=PolicyDecisionOutcome.ALLOW,
            reason="Validated tool plan is read-only and can execute immediately.",
            subject_type="tool_plan",
            metadata={"tool_count": len(tool_use_blocks)},
        ),
    )
    tool_results = await facade._execute_with_receipts(
        session,
        manager=manager,
        plans=tool_use_blocks,
        trace_id=trace_id,
        interaction_id=facade._optional_string(message.metadata.get("interaction_id")),
        confirmed_mutations=False,
    )

    logger.info(
        "mcp_tools_executed",
        tool_count=len(tool_use_blocks),
        errors=sum(1 for r in tool_results if r.get("is_error")),
    )

    return await facade._summarise_executed_tools(
        message=message,
        client=client,
        tool_use_blocks=tool_use_blocks,
        tool_results=tool_results,
        resumed_from_confirmation=False,
    )
