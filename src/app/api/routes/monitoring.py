"""Authenticated monitoring and operator routes.

The public imports in this module are retained for application and test compatibility.
Route implementations live in cohesive monitoring modules grouped by responsibility.
"""

from fastapi import APIRouter, Depends

from src.app.api.deps import get_current_principal
from src.app.config import get_settings
from src.app.core.assistant_native_evals import (
    evaluate_assistant_native_replays,
    validate_assistant_native_eval_assets,
)
from src.app.core.slo import collect_slo_report
from src.app.domain.services.chat import _get_conversation_context
from src.app.persistence.repositories.interactions import (
    get_avg_scores_in_window as repo_get_avg_scores,
)
from src.app.persistence.repositories.interactions import (
    get_interaction_by_id as repo_get_interaction_by_id,
)
from src.app.persistence.repositories.runtime_records import (
    get_latest_pending_workflow_checkpoint_for_user,
    list_policy_decisions,
    list_tool_receipts,
)
from src.app.persistence.repositories.traces import get_trace_detail, summarize_traces

from .monitoring_common import (
    _action_to_dto,
    _optional_bool_field,
    _optional_dict_field,
    _optional_float_field,
    _optional_int_field,
    _optional_string_field,
    _period_to_cutoff,
    _policy_decision_to_dto,
    _result_rows,
    _result_scalar_values,
    _tool_receipt_to_dto,
)
from .monitoring_context import context_snapshot
from .monitoring_context import router as context_router
from .monitoring_models import (
    AgentActionDTO,
    AgentComparisonDTO,
    AgentCost,
    AgentLatency,
    AgentSummary,
    AssistantNativeEvalCaseDTO,
    AssistantNativeEvalSummaryDTO,
    AssistantNativeMetricsDTO,
    ChannelMetricDTO,
    ContextSnapshotDTO,
    CostStat,
    CostTrendPoint,
    EvalOutcomeDTO,
    InteractionRecordDTO,
    LLMStatsDTO,
    ModelCost,
    PolicyDecisionDTO,
    PromptVersionDTO,
    QualityGatesDTO,
    QualityScoresDTO,
    ReleaseReadinessCheckDTO,
    ReleaseReadinessDTO,
    SecurityMetricsDTO,
    SLOReportDTO,
    SLOValueDTO,
    TelegramWebhookStatusDTO,
    TokenStat,
    ToolReceiptDTO,
    TraceDetailDTO,
    TraceSpanDTO,
    TraceSummaryDTO,
    UsageDistribution,
    WorkflowRuntimeDTO,
    WorkflowShadowDTO,
)
from .monitoring_native import assistant_native_metrics
from .monitoring_native import router as native_router
from .monitoring_replay import (
    assistant_native_evals,
    release_readiness,
)
from .monitoring_replay import (
    router as replay_router,
)
from .monitoring_runtime import (
    _evaluate_quality_gates_for_window,
    _quality_gate_thresholds_from_settings,
    policy_decisions,
    quality_gates,
    tool_receipts,
    workflow_runtimes,
    workflow_shadows,
)
from .monitoring_runtime import (
    router as runtime_router,
)
from .monitoring_security import router as security_router
from .monitoring_security import security_metrics
from .monitoring_slo import router as slo_router
from .monitoring_slo import slo_report
from .monitoring_telemetry import (
    channel_metrics,
    eval_outcomes,
    list_traces,
    telegram_webhook_status,
    trace_detail,
)
from .monitoring_telemetry import (
    router as telemetry_router,
)
from .monitoring_usage import (
    agent_comparison,
    get_interaction,
    list_agent_actions,
    llm_stats,
    prompt_versions,
    quality_scores,
)
from .monitoring_usage import (
    router as usage_router,
)

__all__ = [
    "AgentActionDTO",
    "AgentComparisonDTO",
    "AgentCost",
    "AgentLatency",
    "AgentSummary",
    "AssistantNativeEvalCaseDTO",
    "AssistantNativeEvalSummaryDTO",
    "AssistantNativeMetricsDTO",
    "ChannelMetricDTO",
    "ContextSnapshotDTO",
    "CostStat",
    "CostTrendPoint",
    "EvalOutcomeDTO",
    "InteractionRecordDTO",
    "LLMStatsDTO",
    "ModelCost",
    "PolicyDecisionDTO",
    "PromptVersionDTO",
    "QualityGatesDTO",
    "QualityScoresDTO",
    "ReleaseReadinessCheckDTO",
    "ReleaseReadinessDTO",
    "SLOReportDTO",
    "SLOValueDTO",
    "SecurityMetricsDTO",
    "TelegramWebhookStatusDTO",
    "TokenStat",
    "ToolReceiptDTO",
    "TraceDetailDTO",
    "TraceSpanDTO",
    "TraceSummaryDTO",
    "UsageDistribution",
    "WorkflowRuntimeDTO",
    "WorkflowShadowDTO",
    "_action_to_dto",
    "_evaluate_quality_gates_for_window",
    "_get_conversation_context",
    "_optional_bool_field",
    "_optional_dict_field",
    "_optional_float_field",
    "_optional_int_field",
    "_optional_string_field",
    "_period_to_cutoff",
    "_policy_decision_to_dto",
    "_quality_gate_thresholds_from_settings",
    "_result_rows",
    "_result_scalar_values",
    "_tool_receipt_to_dto",
    "agent_comparison",
    "assistant_native_evals",
    "assistant_native_metrics",
    "channel_metrics",
    "collect_slo_report",
    "context_snapshot",
    "eval_outcomes",
    "evaluate_assistant_native_replays",
    "get_interaction",
    "get_latest_pending_workflow_checkpoint_for_user",
    "get_settings",
    "get_trace_detail",
    "list_agent_actions",
    "list_policy_decisions",
    "list_tool_receipts",
    "list_traces",
    "llm_stats",
    "policy_decisions",
    "prompt_versions",
    "quality_gates",
    "quality_scores",
    "release_readiness",
    "repo_get_avg_scores",
    "repo_get_interaction_by_id",
    "router",
    "security_metrics",
    "slo_report",
    "summarize_traces",
    "telegram_webhook_status",
    "tool_receipts",
    "trace_detail",
    "validate_assistant_native_eval_assets",
    "workflow_runtimes",
    "workflow_shadows",
]

router = APIRouter(dependencies=[Depends(get_current_principal)])
for child_router in (
    usage_router,
    telemetry_router,
    runtime_router,
    replay_router,
    native_router,
    security_router,
    context_router,
    slo_router,
):
    router.include_router(child_router)
