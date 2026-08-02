"""Deterministic MCP tool inventory filtering and plan validation."""

from __future__ import annotations

import uuid
from fnmatch import fnmatch
from typing import Any

import structlog

from src.app.core.security import detect_instruction_like_content
from src.app.core.tool_contracts import (
    build_invocation_plan,
    hash_tool_arguments,
    validate_tool_arguments,
)
from src.app.domain.constants import ToolMutationClass, TrustLabel
from src.app.domain.models import (
    MessageInput,
    PendingToolCall,
    PendingToolPlan,
    Specialist,
    ToolInvocationPlan,
)
from src.app.domain.runtime import (
    AgentRuntimeConfig,
    ConfirmationPolicy,
    get_agent_runtime_config,
)

logger = structlog.get_logger()


def load_runtime_config(message: MessageInput) -> AgentRuntimeConfig:
    runtime_data = message.metadata.get("agent_runtime")
    if isinstance(runtime_data, dict):
        return AgentRuntimeConfig.model_validate(runtime_data)
    return get_agent_runtime_config(Specialist.TOOLS)


def tool_full_name(tool: dict[str, Any]) -> str:
    return f"{tool['server_name']}__{tool['tool_name']}"


def filter_allowed_tools(
    tools: list[dict[str, Any]],
    runtime: AgentRuntimeConfig,
) -> list[dict[str, Any]]:
    if not runtime.allowed_tools:
        return tools

    return [
        tool
        for tool in tools
        if any(fnmatch(tool_full_name(tool), pattern) for pattern in runtime.allowed_tools)
    ]


def tool_requires_confirmation(
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


def build_tool_invocation_plans(
    tool_use_blocks: list[dict[str, Any]],
    tool_specs: dict[str, Any],
    runtime: AgentRuntimeConfig,
    *,
    trust_label: str,
    workflow_id: str | None,
) -> list[ToolInvocationPlan]:
    """Apply deterministic post-validation to planned tool calls."""
    validated: list[ToolInvocationPlan] = []

    for candidate in tool_use_blocks:
        name = str(candidate.get("name", ""))
        tool_input = candidate.get("input", {})
        if not name or not isinstance(tool_input, dict):
            logger.warning("invalid_tool_block_rejected", block=candidate)
            continue
        if runtime.allowed_tools and not any(
            fnmatch(name, pattern) for pattern in runtime.allowed_tools
        ):
            logger.warning("tool_not_allowed_by_runtime", tool=name)
            continue
        tool_spec = tool_specs.get(name)
        if tool_spec is None:
            logger.warning("tool_spec_missing", tool=name)
            continue

        block = {
            **candidate,
            "input": tool_input,
            "idempotency_key": str(uuid.uuid4()),
            "audit": {
                "confirmation_required": tool_requires_confirmation(name, runtime),
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

    return enforce_confirmation_policy(validated, runtime=runtime)


def detect_untrusted_instruction_risk(message: MessageInput) -> bool:
    """Detect obvious instruction-like content that should not become tool authority."""
    return detect_instruction_like_content(message.content)


def coerce_trust_label(value: object) -> TrustLabel:
    """Normalize trust labels and fail closed on invalid values."""
    if isinstance(value, TrustLabel):
        return value
    try:
        return TrustLabel(str(value))
    except Exception:
        return TrustLabel.UNTRUSTED_EXTERNAL


def enforce_instruction_risk_confirmation(
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
        requires_confirmation = plan.requires_confirmation or must_confirm
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


def load_pending_tool_plan(message: MessageInput) -> PendingToolPlan | None:
    raw_plan = message.metadata.get("pending_tool_plan")
    if isinstance(raw_plan, PendingToolPlan):
        return raw_plan
    if isinstance(raw_plan, dict):
        return PendingToolPlan.model_validate(raw_plan)
    return None


def to_pending_tool_plan(
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
        workflow_id=optional_string(message.metadata.get("workflow_id")),
    )


def pending_plan_to_plans(
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


def plan_requires_confirmation(
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


def enforce_confirmation_policy(
    plans: list[ToolInvocationPlan],
    *,
    runtime: AgentRuntimeConfig,
) -> list[ToolInvocationPlan]:
    """Normalize confirmation flags so mutation policy is enforced deterministically."""
    normalized: list[ToolInvocationPlan] = []
    for plan in plans:
        requires_confirmation = plan_requires_confirmation(plan, runtime=runtime)
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


def optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
