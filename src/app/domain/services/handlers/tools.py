"""Compatibility facade for MCP tool planning and execution.

Keep imports from this module stable. The implementation is divided into
focused planning, execution, persistence, and workflow modules.
"""

from src.app.agents.specialists.tools import summarise_tool_results
from src.app.core.llm_helpers import call_llm
from src.app.core.mcp_bridge import execute_tool_calls, format_mcp_tools_for_anthropic
from src.app.domain.services.handlers._common import enqueue_entity_extraction
from src.app.domain.services.handlers._tools_execution import (
    dispatch_approval_preview as _dispatch_approval_preview,
)
from src.app.domain.services.handlers._tools_execution import (
    execute_with_receipts as _execute_with_receipts,
)
from src.app.domain.services.handlers._tools_execution import (
    route_plan_through_hitl_gate as _route_plan_through_hitl_gate,
)
from src.app.domain.services.handlers._tools_planning import (
    build_tool_invocation_plans as _build_tool_invocation_plans,
)
from src.app.domain.services.handlers._tools_planning import (
    coerce_trust_label as _coerce_trust_label,
)
from src.app.domain.services.handlers._tools_planning import (
    detect_untrusted_instruction_risk as _detect_untrusted_instruction_risk,
)
from src.app.domain.services.handlers._tools_planning import (
    enforce_confirmation_policy as _enforce_confirmation_policy,
)
from src.app.domain.services.handlers._tools_planning import (
    enforce_instruction_risk_confirmation as _enforce_instruction_risk_confirmation,
)
from src.app.domain.services.handlers._tools_planning import (
    filter_allowed_tools as _filter_allowed_tools,
)
from src.app.domain.services.handlers._tools_planning import (
    load_pending_tool_plan as _load_pending_tool_plan,
)
from src.app.domain.services.handlers._tools_planning import (
    load_runtime_config as _load_runtime_config,
)
from src.app.domain.services.handlers._tools_planning import (
    optional_string as _optional_string,
)
from src.app.domain.services.handlers._tools_planning import (
    pending_plan_to_plans as _pending_plan_to_plans,
)
from src.app.domain.services.handlers._tools_planning import (
    plan_requires_confirmation as _plan_requires_confirmation,
)
from src.app.domain.services.handlers._tools_planning import (
    to_pending_tool_plan as _to_pending_tool_plan,
)
from src.app.domain.services.handlers._tools_planning import (
    tool_full_name as _tool_full_name,
)
from src.app.domain.services.handlers._tools_planning import (
    tool_requires_confirmation as _tool_requires_confirmation,
)
from src.app.domain.services.handlers._tools_records import (
    maybe_create_tool_receipt as _maybe_create_tool_receipt,
)
from src.app.domain.services.handlers._tools_records import (
    maybe_get_existing_receipt as _maybe_get_existing_receipt,
)
from src.app.domain.services.handlers._tools_records import (
    persist_approval_span as _persist_approval_span,
)
from src.app.domain.services.handlers._tools_records import (
    persist_checkpoint as _persist_checkpoint,
)
from src.app.domain.services.handlers._tools_records import (
    persist_policy_decision as _persist_policy_decision,
)
from src.app.domain.services.handlers._tools_records import (
    resolve_pending_checkpoint as _resolve_pending_checkpoint,
)
from src.app.domain.services.handlers._tools_responses import (
    summarise_executed_tools as _summarise_executed_tools,
)
from src.app.domain.services.handlers._tools_workflow import (
    _handle_tools_with_mcp,
    get_mcp_client_manager,
    handle_tools,
    set_mcp_client_manager,
)
from src.app.persistence.repositories.runtime_records import (
    create_artifact_record,
    create_policy_decision,
    create_tool_receipt,
    create_workflow_checkpoint,
    get_tool_receipt_by_idempotency_key,
    update_workflow_checkpoint,
)

__all__ = [
    "_build_tool_invocation_plans",
    "_coerce_trust_label",
    "_detect_untrusted_instruction_risk",
    "_dispatch_approval_preview",
    "_enforce_confirmation_policy",
    "_enforce_instruction_risk_confirmation",
    "_execute_with_receipts",
    "_filter_allowed_tools",
    "_handle_tools_with_mcp",
    "_load_pending_tool_plan",
    "_load_runtime_config",
    "_maybe_create_tool_receipt",
    "_maybe_get_existing_receipt",
    "_optional_string",
    "_pending_plan_to_plans",
    "_persist_approval_span",
    "_persist_checkpoint",
    "_persist_policy_decision",
    "_plan_requires_confirmation",
    "_resolve_pending_checkpoint",
    "_route_plan_through_hitl_gate",
    "_summarise_executed_tools",
    "_to_pending_tool_plan",
    "_tool_full_name",
    "_tool_requires_confirmation",
    "call_llm",
    "create_artifact_record",
    "create_policy_decision",
    "create_tool_receipt",
    "create_workflow_checkpoint",
    "enqueue_entity_extraction",
    "execute_tool_calls",
    "format_mcp_tools_for_anthropic",
    "get_mcp_client_manager",
    "get_tool_receipt_by_idempotency_key",
    "handle_tools",
    "set_mcp_client_manager",
    "summarise_tool_results",
    "update_workflow_checkpoint",
]
