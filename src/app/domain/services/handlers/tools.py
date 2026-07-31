"""Tools handler — live MCP tool planning and execution."""

from __future__ import annotations

import uuid
from fnmatch import fnmatch
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.specialists.tools import ToolResult, summarise_tool_results
from src.app.core.async_utils import maybe_await
from src.app.core.confirmation import is_explicit_confirmation, is_explicit_rejection
from src.app.core.exceptions import MCPError
from src.app.core.hitl import (
    ApprovalResult,
    SyntheticCancelledResult,
    build_approval_span,
    build_interrupt_payload,
    is_auto_approved,
    parse_resume_value,
    requires_approval,
)
from src.app.core.llm_helpers import call_llm
from src.app.core.mcp_bridge import execute_tool_calls, format_mcp_tools_for_anthropic
from src.app.core.security import (
    detect_instruction_like_content,
    trust_label_for_message_source,
)
from src.app.core.tool_contracts import (
    build_invocation_plan,
    build_tool_specs,
    hash_tool_arguments,
    validate_tool_arguments,
)
from src.app.domain.constants import PolicyDecisionOutcome, ToolMutationClass, TrustLabel
from src.app.domain.models import (
    ArtifactRecord,
    ChatResponse,
    Intent,
    MessageInput,
    PendingToolCall,
    PendingToolPlan,
    PolicyDecision,
    Specialist,
    ToolInvocationPlan,
)
from src.app.domain.runtime import (
    AgentRuntimeConfig,
    ConfirmationPolicy,
    get_agent_runtime_config,
)
from src.app.domain.services.handlers._common import enqueue_entity_extraction
from src.app.persistence.repositories.runtime_records import (
    create_artifact_record,
    create_policy_decision,
    create_tool_receipt,
    create_workflow_checkpoint,
    get_tool_receipt_by_idempotency_key,
    update_workflow_checkpoint,
)

logger = structlog.get_logger()

# Module-level MCP client manager — set during app startup via set_mcp_client_manager().
_mcp_client_manager: Any = None


def set_mcp_client_manager(manager: Any) -> None:
    """Register the MCP client manager for the tools handler.

    Called once during app lifespan after the manager connects to MCP servers.
    """
    global _mcp_client_manager
    _mcp_client_manager = manager


def get_mcp_client_manager() -> Any:
    """Return the current MCP client manager, or None."""
    return _mcp_client_manager


def _load_runtime_config(message: MessageInput) -> AgentRuntimeConfig:
    runtime_data = message.metadata.get("agent_runtime")
    if isinstance(runtime_data, dict):
        return AgentRuntimeConfig.model_validate(runtime_data)
    return get_agent_runtime_config(Specialist.TOOLS)


def _tool_full_name(tool: dict[str, Any]) -> str:
    return f"{tool['server_name']}__{tool['tool_name']}"


def _filter_allowed_tools(
    tools: list[dict[str, Any]],
    runtime: AgentRuntimeConfig,
) -> list[dict[str, Any]]:
    if not runtime.allowed_tools:
        return tools

    filtered: list[dict[str, Any]] = []
    for tool in tools:
        full_name = _tool_full_name(tool)
        if any(fnmatch(full_name, pattern) for pattern in runtime.allowed_tools):
            filtered.append(tool)
    return filtered


def _tool_requires_confirmation(
    tool_name: str,
    runtime: AgentRuntimeConfig,
) -> bool:
    if runtime.confirmation_policy == ConfirmationPolicy.ALWAYS:
        return True
    if runtime.confirmation_policy == ConfirmationPolicy.NEVER:
        return False

    read_only_prefixes = (
        "get_",
        "list_",
        "read_",
        "search_",
        "find_",
        "fetch_",
    )
    action_name = tool_name.split("__", 1)[-1]
    return not action_name.startswith(read_only_prefixes)


def _build_tool_invocation_plans(
    tool_use_blocks: list[dict[str, Any]],
    tool_specs: dict[str, Any],
    runtime: AgentRuntimeConfig,
    *,
    trust_label: str,
    workflow_id: str | None,
) -> list[ToolInvocationPlan]:
    """Apply deterministic post-validation to planned tool calls."""
    validated: list[ToolInvocationPlan] = []
    allowed_patterns = runtime.allowed_tools

    for block in tool_use_blocks:
        name = str(block.get("name", ""))
        tool_input = block.get("input", {})
        if not name or not isinstance(tool_input, dict):
            logger.warning("invalid_tool_block_rejected", block=block)
            continue
        if allowed_patterns and not any(fnmatch(name, pattern) for pattern in allowed_patterns):
            logger.warning("tool_not_allowed_by_runtime", tool=name)
            continue
        tool_spec = tool_specs.get(name)
        if tool_spec is None:
            logger.warning("tool_spec_missing", tool=name)
            continue
        block = {
            **block,
            "input": tool_input,
            "idempotency_key": str(uuid.uuid4()),
            "audit": {
                "confirmation_required": _tool_requires_confirmation(name, runtime),
                "trusted_content_only": True,
                "trust_label": trust_label,
            },
        }
        errors = validate_tool_arguments(tool_spec, tool_input)
        if errors:
            logger.warning("tool_argument_validation_failed", tool=name, errors=errors)
            continue
        validated.append(
            build_invocation_plan(
                tool_block=block,
                tool_spec=tool_spec,
                runtime=runtime,
                trust_label=trust_label,
                workflow_id=workflow_id,
            )
        )

    return _enforce_confirmation_policy(validated, runtime=runtime)


def _detect_untrusted_instruction_risk(message: MessageInput) -> bool:
    """Detect obvious instruction-like content that should not become tool authority."""
    return detect_instruction_like_content(message.content)


def _coerce_trust_label(value: object) -> TrustLabel:
    """Normalize trust labels and fail closed to untrusted_external on invalid values."""
    if isinstance(value, TrustLabel):
        return value
    try:
        return TrustLabel(str(value))
    except Exception:
        return TrustLabel.UNTRUSTED_EXTERNAL


def _enforce_instruction_risk_confirmation(
    plans: list[ToolInvocationPlan],
) -> list[ToolInvocationPlan]:
    """Force confirmation for mutating calls when instruction-risk markers are present."""
    normalized: list[ToolInvocationPlan] = []
    for plan in plans:
        audit = dict(plan.audit_metadata or {})
        audit["instruction_like_content"] = True
        must_confirm = str(plan.mutation_class) == str(ToolMutationClass.MUTATING)
        if must_confirm:
            audit["confirmation_required"] = True
            audit["confirmation_reason"] = "instruction_like_content"
        normalized.append(
            plan.model_copy(
                update={
                    "requires_confirmation": plan.requires_confirmation or must_confirm,
                    "allowed_parallelism": (
                        "sequential"
                        if (plan.requires_confirmation or must_confirm)
                        else plan.allowed_parallelism
                    ),
                    "audit_metadata": audit,
                }
            )
        )
    return normalized


def _load_pending_tool_plan(message: MessageInput) -> PendingToolPlan | None:
    raw_plan = message.metadata.get("pending_tool_plan")
    if isinstance(raw_plan, PendingToolPlan):
        return raw_plan
    if isinstance(raw_plan, dict):
        return PendingToolPlan.model_validate(raw_plan)
    return None


def _to_pending_tool_plan(
    tool_use_blocks: list[ToolInvocationPlan],
    *,
    message: MessageInput,
    trust_label: str,
) -> PendingToolPlan:
    return PendingToolPlan(
        plan_id=str(uuid.uuid4()),
        original_user_message=message.content,
        tool_calls=[
            PendingToolCall(
                tool_use_id=block.tool_id,
                name=block.public_name,
                input=dict(block.arguments),
                idempotency_key=block.idempotency_key,
                audit=dict(block.audit_metadata),
            )
            for block in tool_use_blocks
        ],
        trust_label=trust_label,
        workflow_id=_optional_string(message.metadata.get("workflow_id")),
    )


def _pending_plan_to_plans(
    plan: PendingToolPlan,
    tool_specs: dict[str, Any],
    *,
    workflow_id: str | None = None,
) -> list[ToolInvocationPlan]:
    plans: list[ToolInvocationPlan] = []
    plan_workflow_id = workflow_id or plan.workflow_id
    for call in plan.tool_calls:
        tool_spec = tool_specs.get(call.name)
        if tool_spec is None:
            logger.warning("tool_spec_missing_for_pending_plan", tool=call.name)
            server_name, _, tool_name = call.name.partition("__")
            plans.append(
                ToolInvocationPlan(
                    tool_id=call.tool_use_id,
                    server_name=server_name,
                    tool_name=tool_name or call.name,
                    public_name=call.name,
                    arguments=call.input,
                    input_schema={},
                    argument_hash=hash_tool_arguments(call.input),
                    idempotency_key=call.idempotency_key,
                    trust_context=str(call.audit.get("trust_label", plan.trust_label)),
                    requires_confirmation=True,
                    mutation_class=str(ToolMutationClass.MUTATING),
                    allowed_parallelism="sequential",
                    audit_metadata=call.audit,
                    workflow_id=plan_workflow_id,
                )
            )
            continue
        confirmation_required = bool(call.audit.get("confirmation_required", False)) or str(
            tool_spec.mutation_class
        ) == str(ToolMutationClass.MUTATING)
        plans.append(
            ToolInvocationPlan(
                tool_id=call.tool_use_id,
                server_name=tool_spec.server_name,
                tool_name=tool_spec.tool_name,
                public_name=call.name,
                arguments=call.input,
                input_schema=tool_spec.input_schema,
                argument_hash=hash_tool_arguments(call.input),
                idempotency_key=call.idempotency_key,
                trust_context=str(call.audit.get("trust_label", plan.trust_label)),
                requires_confirmation=confirmation_required,
                mutation_class=str(tool_spec.mutation_class),
                allowed_parallelism=(
                    "sequential" if confirmation_required else str(tool_spec.allowed_parallelism)
                ),
                audit_metadata=call.audit,
                workflow_id=plan_workflow_id,
            )
        )
    return plans


def _plan_requires_confirmation(
    plan: ToolInvocationPlan,
    *,
    runtime: AgentRuntimeConfig,
) -> bool:
    if runtime.confirmation_policy == ConfirmationPolicy.ALWAYS:
        return True
    if runtime.confirmation_policy == ConfirmationPolicy.NEVER:
        return False
    return str(plan.mutation_class) == str(ToolMutationClass.MUTATING) or bool(
        plan.requires_confirmation
    )


def _enforce_confirmation_policy(
    plans: list[ToolInvocationPlan],
    *,
    runtime: AgentRuntimeConfig,
) -> list[ToolInvocationPlan]:
    """Normalize confirmation flags so mutation policy is enforced deterministically."""
    normalized: list[ToolInvocationPlan] = []
    for plan in plans:
        requires_confirmation = _plan_requires_confirmation(plan, runtime=runtime)
        audit = dict(plan.audit_metadata or {})
        audit["confirmation_required"] = requires_confirmation
        normalized.append(
            plan.model_copy(
                update={
                    "requires_confirmation": requires_confirmation,
                    "allowed_parallelism": (
                        "sequential" if requires_confirmation else plan.allowed_parallelism
                    ),
                    "audit_metadata": audit,
                }
            )
        )
    return normalized


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


async def _summarise_executed_tools(
    *,
    message: MessageInput,
    client: AsyncAnthropic,
    tool_use_blocks: list[ToolInvocationPlan],
    tool_results: list[dict[str, Any]],
    resumed_from_confirmation: bool,
) -> ChatResponse:
    result_objects = []
    tool_events: list[dict[str, Any]] = []
    for block, result in zip(tool_use_blocks, tool_results, strict=True):
        content = result.get("content", "")
        is_error = result.get("is_error", False)
        result_objects.append(
            ToolResult(
                tool=block.public_name,
                action="execute",
                success=not is_error,
                data={"result": content if isinstance(content, str) else str(content)},
                error=content if is_error else None,
            )
        )
        tool_events.append(
            {
                "name": block.public_name,
                "status": "failed" if is_error else "executed",
                "details": {
                    "idempotency_key": block.idempotency_key,
                    "argument_hash": block.argument_hash,
                    "resumed_from_confirmation": resumed_from_confirmation,
                    "result_preview": (
                        str(content)[:300] if not is_error and content is not None else None
                    ),
                    "error": str(content) if is_error else None,
                },
            }
        )

    summary = await summarise_tool_results(message.content, result_objects, client)
    tool_call_status = "confirmed" if resumed_from_confirmation else "executed"

    return ChatResponse(
        content=summary,
        agent="tools",
        metadata={
            "tool_count": len(tool_use_blocks),
            "mcp_execution": True,
            "tools_executed": [b.public_name for b in tool_use_blocks],
            "tool_calls": [
                {
                    "name": b.public_name,
                    "status": tool_call_status,
                    "idempotency_key": b.idempotency_key,
                    "argument_hash": b.argument_hash,
                    "audit": b.audit_metadata,
                }
                for b in tool_use_blocks
            ],
            "errors": sum(1 for r in tool_results if r.get("is_error")),
            "tool_events": tool_events,
            "pending_tool_plan_cleared": resumed_from_confirmation,
            "confirmation_resumed": resumed_from_confirmation,
        },
    )


async def handle_tools(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    _intent: Intent,
) -> ChatResponse:
    """Plan and execute tool calls for a user request via MCP."""
    manager = get_mcp_client_manager()

    if manager is None or not manager.connected:
        raise MCPError("MCP tool execution is unavailable in this runtime.")

    response = await _handle_tools_with_mcp(message, client, session, manager)

    try:
        await enqueue_entity_extraction(
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
        await create_artifact_record(
            session,
            user_id=message.user_id,
            artifact=ArtifactRecord(
                artifact_type="tool_summary",
                summary=response.content[:500],
                source_id=_optional_string(response.metadata.get("response_id")),
                trace_id=_optional_string(response.metadata.get("trace_id")),
                workflow_id=_optional_string(message.metadata.get("workflow_id")),
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

    if manager is None:
        manager = session
        session = None

    settings = get_settings()
    runtime = _load_runtime_config(message)
    raw_trust_label = message.metadata.get("trust_label") or trust_label_for_message_source(
        message.source
    )
    trust_label = _coerce_trust_label(raw_trust_label)
    trace_id = _optional_string(message.metadata.get("trace_id"))
    workflow_id = _optional_string(message.metadata.get("workflow_id"))
    pending_plan = _load_pending_tool_plan(message)

    if pending_plan is not None:
        if is_explicit_rejection(message.content):
            await _persist_policy_decision(
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
            await _resolve_pending_checkpoint(session, pending_plan, status="cancelled")
            return ChatResponse(
                content="Okay. I have cancelled the pending tool action.",
                agent="tools",
                metadata={
                    "confirmation_required": False,
                    "mcp_execution": False,
                    "pending_tool_plan_cleared": True,
                    "tool_count": len(pending_plan.tool_calls),
                    "tool_calls": [
                        {"name": call.name, "status": "cancelled"}
                        for call in pending_plan.tool_calls
                    ],
                    "tool_events": [
                        {"name": call.name, "status": "cancelled", "details": {}}
                        for call in pending_plan.tool_calls
                    ],
                },
            )
        if is_explicit_confirmation(message.content):
            pending_trust = _coerce_trust_label(pending_plan.trust_label)
            if pending_trust == TrustLabel.UNTRUSTED_EXTERNAL:
                await _persist_policy_decision(
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
                await _resolve_pending_checkpoint(session, pending_plan, status="cancelled")
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
                            {"name": call.name, "status": "blocked"}
                            for call in pending_plan.tool_calls
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
            allowed_tools = _filter_allowed_tools(mcp_tools_raw, runtime)
            tool_specs = build_tool_specs(
                allowed_tools,
                tool_metadata={
                    _tool_full_name(tool): dict(tool.get("tool_metadata") or {})
                    for tool in allowed_tools
                },
            )
            tool_use_blocks = _enforce_confirmation_policy(
                _pending_plan_to_plans(pending_plan, tool_specs),
                runtime=runtime,
            )
            await _persist_policy_decision(
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
            await _resolve_pending_checkpoint(session, pending_plan, status="confirmed")
            tool_results = await _execute_with_receipts(
                session,
                manager=manager,
                plans=tool_use_blocks,
                trace_id=trace_id,
                interaction_id=_optional_string(message.metadata.get("interaction_id")),
                confirmed_mutations=True,
            )
            logger.info(
                "mcp_tools_resumed_from_confirmation",
                tool_count=len(tool_use_blocks),
                plan_id=pending_plan.plan_id,
                errors=sum(1 for r in tool_results if r.get("is_error")),
            )
            return await _summarise_executed_tools(
                message=message,
                client=client,
                tool_use_blocks=tool_use_blocks,
                tool_results=tool_results,
                resumed_from_confirmation=True,
            )

    list_tools = getattr(manager, "list_tools", None)
    mcp_tools_raw = await maybe_await(list_tools()) if callable(list_tools) else []
    if not isinstance(mcp_tools_raw, list):
        mcp_tools_raw = []
    allowed_tools = _filter_allowed_tools(mcp_tools_raw, runtime)
    tool_specs = build_tool_specs(
        allowed_tools,
        tool_metadata={
            _tool_full_name(tool): dict(tool.get("tool_metadata") or {}) for tool in allowed_tools
        },
    )

    # Get available MCP tools formatted for Claude
    anthropic_tools = format_mcp_tools_for_anthropic(allowed_tools)

    if not anthropic_tools:
        raise MCPError("MCP is connected but no tools are available for execution.")

    # Ask Claude which tools to call, giving it the real MCP tool definitions.
    # We use call_llm() for retry, structlog logging, and prompt caching.
    from src.app.core.exceptions import LLMError

    instruction_risk = _detect_untrusted_instruction_risk(message)
    if instruction_risk:
        logger.warning("tool_request_contains_instruction_like_content")
        message.metadata.setdefault("safety_flags", []).append("instruction_like_content")
        await _persist_policy_decision(
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
        response = await call_llm(
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
    tool_use_blocks = _build_tool_invocation_plans(
        tool_use_blocks,
        tool_specs,
        runtime,
        trust_label=str(trust_label.value),
        workflow_id=workflow_id,
    )
    if instruction_risk and tool_use_blocks:
        tool_use_blocks = _enforce_instruction_risk_confirmation(tool_use_blocks)

    if not tool_use_blocks:
        if response.content:
            await _persist_policy_decision(
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
        await _persist_policy_decision(
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
        pending_tool_plan = _to_pending_tool_plan(
            tool_use_blocks,
            message=message,
            trust_label=str(trust_label.value),
        )
        await _persist_policy_decision(
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
        checkpoint = await _persist_checkpoint(
            session,
            workflow_id=workflow_id,
            payload=pending_tool_plan.model_dump(mode="json"),
        )
        pending_tool_plan = pending_tool_plan.model_copy(
            update={
                "workflow_id": workflow_id,
                "checkpoint_id": _optional_string(getattr(checkpoint, "id", None)),
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
    await _persist_policy_decision(
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
    tool_results = await _execute_with_receipts(
        session,
        manager=manager,
        plans=tool_use_blocks,
        trace_id=trace_id,
        interaction_id=_optional_string(message.metadata.get("interaction_id")),
        confirmed_mutations=False,
    )

    logger.info(
        "mcp_tools_executed",
        tool_count=len(tool_use_blocks),
        errors=sum(1 for r in tool_results if r.get("is_error")),
    )

    return await _summarise_executed_tools(
        message=message,
        client=client,
        tool_use_blocks=tool_use_blocks,
        tool_results=tool_results,
        resumed_from_confirmation=False,
    )


async def _execute_with_receipts(
    session: AsyncSession,
    *,
    manager: Any,
    plans: list[ToolInvocationPlan],
    trace_id: str | None,
    interaction_id: str | None,
    confirmed_mutations: bool,
) -> list[dict[str, Any]]:
    """Execute tool plans while enforcing idempotency receipts.

    P5.8: every mutating plan is routed through ``approval_gate`` before it
    reaches the MCP bridge. The gate returns APPROVE / EDIT / AUTO_APPROVE /
    CANCEL / TIMEOUT. APPROVE/EDIT/AUTO_APPROVE proceed (with possibly edited
    args); CANCEL/TIMEOUT yield a ``SyntheticCancelledResult`` tool_result so
    the specialist can continue the conversation gracefully.
    """
    if (
        any(str(plan.mutation_class) == str(ToolMutationClass.MUTATING) for plan in plans)
        and not confirmed_mutations
    ):
        raise MCPError("Mutating tool execution is blocked until explicit user confirmation.")

    cached_results: dict[str, dict[str, Any]] = {}
    cancelled_results: dict[str, dict[str, Any]] = {}
    plans_to_execute: list[ToolInvocationPlan] = []
    # Tracks the final args each plan executes with — supports the edit path
    # where approval_gate may have mutated the plan's arguments.
    resolved_args: dict[str, dict[str, Any]] = {}

    for plan in plans:
        existing_receipt = await _maybe_get_existing_receipt(session, plan.idempotency_key)
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

        # When the user has already confirmed the mutating plan via the prior
        # text-confirmation turn (``confirmed_mutations=True``), don't gate
        # the call again — that would double-prompt and time out.
        if confirmed_mutations:
            plans_to_execute.append(plan)
            resolved_args[plan.idempotency_key] = dict(plan.arguments)
            continue

        gated_plan = await _route_plan_through_hitl_gate(
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
        resolved_args[gated_plan.idempotency_key] = dict(gated_plan.arguments)

    executed_results = await execute_tool_calls(manager, plans_to_execute)

    executed_by_idempotency = {
        plan.idempotency_key: result
        for plan, result in zip(plans_to_execute, executed_results, strict=True)
    }

    for plan in plans_to_execute:
        result = executed_by_idempotency[plan.idempotency_key]
        await _maybe_create_tool_receipt(
            session,
            plan=plan,
            result=result,
            trace_id=trace_id,
            interaction_id=interaction_id,
        )

    out: list[dict[str, Any]] = []
    for plan in plans:
        if plan.idempotency_key in cancelled_results:
            out.append(cancelled_results[plan.idempotency_key])
        elif plan.idempotency_key in cached_results:
            out.append(cached_results[plan.idempotency_key])
        else:
            out.append(executed_by_idempotency[plan.idempotency_key])
    return out


async def _route_plan_through_hitl_gate(
    session: AsyncSession | None,
    *,
    plan: ToolInvocationPlan,
    trace_id: str | None,
) -> ToolInvocationPlan | SyntheticCancelledResult:
    """Apply the HITL approval gate to a single plan.

    Returns the (possibly edit-updated) plan when the user approves or the
    plan passes through, otherwise a ``SyntheticCancelledResult`` that the
    caller surfaces as a cancelled tool_result.

    The ``approval_gate`` helper in ``src.app.core.hitl`` is transport-agnostic
    but synchronous. Because our Telegram approval flow is inherently async
    (waits on a future keyed by ``interrupt_id``), we drive the same three
    stages manually here: evaluate gating, check trusted-destination auto
    approve, post a preview, and block on the user's reply.
    """
    from src.app.config import get_settings
    from src.app.domain.services.approval_callbacks import (
        get_registry,
        wait_for_approval_decision,
    )

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
        await _persist_approval_span(
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

    # Best-effort Telegram preview dispatch — tests that don't hook Telegram
    # still drive the flow via wait_for_approval_decision because the
    # registry is process-local.
    chat_id = None
    try:
        await _dispatch_approval_preview(payload=payload, plan=plan)
    except Exception:
        logger.debug("hitl_preview_dispatch_skipped", exc_info=True)

    registry = get_registry()  # noqa: F841 — registration happens inside wait_for_approval_decision
    resume_value = await wait_for_approval_decision(
        interrupt_id=plan.tool_id,
        tool_name=plan.public_name,
        original_args=dict(plan.arguments),
        chat_id=chat_id,
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

    await _persist_approval_span(
        session,
        result=decision,
        plan=plan,
        trace_id=trace_id,
    )

    if not decision.should_run:
        reason = decision.reason or "cancelled_by_user"
        logger.info(
            "hitl_cancelled_before_execution",
            tool=plan.public_name,
            decision=decision.decision,
            interrupt_id=decision.interrupt_id,
            reason=reason,
        )
        return SyntheticCancelledResult(
            tool_name=plan.public_name,
            reason=reason,
            interrupt_id=decision.interrupt_id,
        )

    if decision.decision == ApprovalResult.EDIT and decision.args != plan.arguments:
        return plan.model_copy(
            update={
                "arguments": dict(decision.args),
                "audit_metadata": {
                    **(plan.audit_metadata or {}),
                    "hitl_edited": True,
                    "hitl_interrupt_id": decision.interrupt_id,
                },
            }
        )
    return plan.model_copy(
        update={
            "audit_metadata": {
                **(plan.audit_metadata or {}),
                "hitl_decision": decision.decision,
                "hitl_interrupt_id": decision.interrupt_id,
            }
        }
    )


async def _dispatch_approval_preview(
    *,
    payload: dict[str, Any],
    plan: ToolInvocationPlan,
) -> None:
    """Best-effort Telegram preview for a pending approval.

    Lives behind a try/except at the call site so broken transports never
    stall a tool call. Tests override this symbol via monkeypatch.
    """
    _ = (payload, plan)  # Subclassed transports override this hook.


async def _persist_approval_span(
    session: AsyncSession | None,
    *,
    result: ApprovalResult,
    plan: ToolInvocationPlan,
    trace_id: str | None,
) -> None:
    """Record an approval span (best-effort). Never blocks execution on failure."""
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


async def _maybe_get_existing_receipt(session: AsyncSession, idempotency_key: str):
    try:
        receipt = await get_tool_receipt_by_idempotency_key(session, idempotency_key)
        if receipt is None or not isinstance(getattr(receipt, "idempotency_key", None), str):
            return None
        return receipt
    except Exception:
        logger.warning("tool_receipt_lookup_failed", exc_info=True)
        return None


async def _maybe_create_tool_receipt(
    session: AsyncSession,
    *,
    plan: ToolInvocationPlan,
    result: dict[str, Any],
    trace_id: str | None,
    interaction_id: str | None,
) -> None:
    try:
        content = result.get("content", "")
        is_error = bool(result.get("is_error"))
        await create_tool_receipt(
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


async def _persist_policy_decision(
    session: AsyncSession | None,
    *,
    message: MessageInput,
    decision: PolicyDecision,
) -> None:
    if session is None:
        return
    try:
        await create_policy_decision(
            session,
            decision,
            workflow_id=_optional_string(message.metadata.get("workflow_id")),
            trace_id=_optional_string(message.metadata.get("trace_id")),
            specialist=Specialist.TOOLS.value,
        )
    except Exception:
        logger.warning("policy_decision_persist_failed", exc_info=True)


async def _persist_checkpoint(
    session: AsyncSession | None,
    *,
    workflow_id: str | None,
    payload: dict[str, Any],
) -> Any | None:
    if session is None or workflow_id is None:
        return None
    try:
        return await create_workflow_checkpoint(
            session,
            workflow_id=workflow_id,
            checkpoint_kind="tool_confirmation",
            status="pending",
            payload=payload,
        )
    except Exception:
        logger.warning("workflow_checkpoint_persist_failed", exc_info=True)
        return None


async def _resolve_pending_checkpoint(
    session: AsyncSession | None,
    plan: PendingToolPlan,
    *,
    status: str,
) -> None:
    if session is None:
        return
    try:
        updated = await update_workflow_checkpoint(
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
