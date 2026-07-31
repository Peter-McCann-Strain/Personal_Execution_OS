"""Monitoring endpoints — agent actions, LLM stats, agent comparison."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.prompts import PROMPT_VERSIONS
from src.app.api.deps import get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.config import get_settings
from src.app.core.assistant_native_evals import (
    ASSISTANT_NATIVE_EVAL_DATASET_PATH,
    evaluate_assistant_native_replays,
    validate_assistant_native_eval_assets,
)
from src.app.core.exceptions import NotFoundError
from src.app.core.quality_gates import QualityGateThresholds, evaluate_quality_gates
from src.app.core.slo import collect_slo_report
from src.app.domain.constants import WorkflowStatus
from src.app.domain.models import PendingToolPlan, Specialist
from src.app.domain.runtime import get_agent_runtime_config
from src.app.domain.services.chat import _get_conversation_context
from src.app.persistence.models import (
    AgentAction,
    ApprovalRequest,
    BrowserSession,
    ConnectorAccount,
    ConnectorDocument,
    ContentAsset,
    InteractionRecord,
    Note,
    NoteCanvas,
    NoteLink,
    ProjectDraft,
    SavedMemory,
    ScheduledAction,
    ScheduledActionRun,
    ToolReceipt,
    WorkflowRun,
)
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

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])
_TELEGRAM_PENDING_WARNING_THRESHOLD = 10
_TELEGRAM_RECENT_ERROR_WINDOW_SECONDS = 3600


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class AgentActionDTO(BaseModel):
    id: str
    agent_name: str
    action_type: str | None
    model_used: str | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    duration_ms: int | None
    input_summary: str | None
    output_summary: str | None
    trace_id: str | None
    created_at: str


# --- LLM Stats ---


class CostStat(BaseModel):
    today: float
    week: float
    month: float


class CostTrendPoint(BaseModel):
    date: str
    cost: float


class ModelCost(BaseModel):
    model: str
    cost: float


class AgentCost(BaseModel):
    agent: str
    cost: float


class TokenStat(BaseModel):
    input: int
    output: int


class AgentLatency(BaseModel):
    agent: str
    avg_ms: float


class LLMStatsDTO(BaseModel):
    cost: CostStat
    cost_trend: list[CostTrendPoint]
    cost_by_model: list[ModelCost]
    cost_by_agent: list[AgentCost]
    tokens: TokenStat
    latency_by_agent: list[AgentLatency]


# --- Agent Comparison ---


class AgentSummary(BaseModel):
    agent: str
    call_count: int
    avg_cost: float
    avg_latency_ms: float
    error_rate: float
    total_tokens: int


class UsageDistribution(BaseModel):
    agent: str
    calls: int


class AgentComparisonDTO(BaseModel):
    summaries: list[AgentSummary]
    usage_distribution: list[UsageDistribution]


class InteractionRecordDTO(BaseModel):
    id: str
    trace_id: str | None = None
    response_id: str | None = None
    user_id: str
    user_message: str
    source: str
    intent_type: str
    specialist: str
    routing_confidence: float
    response_content: str
    response_agent: str
    duration_ms: int
    eval_status: str
    score_relevance: float | None
    score_actionability: float | None
    score_tone: float | None
    score_conciseness: float | None
    quality_scores: dict | None = None
    channel_metrics: dict | None = None
    created_at: str


class QualityScoresDTO(BaseModel):
    relevance: float | None
    actionability: float | None
    tone: float | None
    conciseness: float | None
    count: int


class PromptVersionDTO(BaseModel):
    kind: str
    agent: str
    prompt_version: str | None
    prompt_source: str
    model_policy: str
    eval_rubric_id: str | None
    memory_namespace: str | None
    confirmation_policy: str | None
    allowed_tool_patterns: list[str]


class TraceSummaryDTO(BaseModel):
    trace_id: str
    channel: str
    specialist: str | None
    status: str
    span_count: int
    total_latency_ms: int
    error_count: int
    created_at: str


class TraceSpanDTO(BaseModel):
    id: str
    parent_span_id: str | None
    name: str
    span_kind: str
    channel: str
    specialist: str | None
    status: str
    error_class: str | None
    model: str | None
    tokens_in: int | None
    tokens_out: int | None
    tool_name: str | None
    cache_hit: bool | None
    latency_ms: int | None
    details: dict
    created_at: str


class TraceDetailDTO(BaseModel):
    trace_id: str
    channel: str
    specialist: str | None
    status: str
    created_at: str
    spans: list[TraceSpanDTO]


class EvalOutcomeDTO(BaseModel):
    id: str
    trace_id: str | None
    response_id: str | None
    specialist: str
    source: str
    eval_status: str
    quality_scores: dict | None
    channel_metrics: dict | None
    feedback_rating: str | None
    created_at: str


class ChannelMetricDTO(BaseModel):
    source: str
    interaction_count: int
    avg_latency_ms: float
    avg_chunk_count: float
    render_failures: int
    delivery_failures: int
    delivery_success_rate: float
    avg_retry_count: float
    total_retry_count: int
    chunked_delivery_rate: float
    reply_anchor_drop_rate: float | None = None
    feedback_callback_success_rate: float | None = None


class TelegramWebhookStatusDTO(BaseModel):
    status: str
    url: str | None = None
    pending_update_count: int | None = None
    last_error_date: int | None = None
    last_error_message: str | None = None
    max_connections: int | None = None
    last_error_age_seconds: int | None = None
    webhook_lagging: bool | None = None
    pending_updates_warning_threshold: int | None = None


class ToolReceiptDTO(BaseModel):
    id: str
    workflow_id: str | None = None
    trace_id: str | None = None
    interaction_id: str | None = None
    idempotency_key: str
    tool_name: str
    server_name: str | None = None
    mutation_class: str
    status: str
    argument_hash: str
    arguments: dict | None = None
    audit_metadata: dict | None = None
    result_summary: str | None = None
    error_message: str | None = None
    created_at: str


class PolicyDecisionDTO(BaseModel):
    id: str
    workflow_id: str | None = None
    trace_id: str | None = None
    specialist: str | None = None
    policy_name: str
    decision: str
    reason: str
    subject_type: str
    subject_id: str | None = None
    metadata: dict | None = None
    created_at: str


class WorkflowShadowDTO(BaseModel):
    workflow_id: str
    live_workflow_id: str | None = None
    trace_id: str | None = None
    source: str
    live_specialist: str | None = None
    shadow_specialist: str | None = None
    route_match: bool | None = None
    shadow_status: str | None = None
    executed: bool = False
    skipped_reason: str | None = None
    confidence: float | None = None
    latency_ms: int | None = None
    result_preview: str | None = None
    created_at: str


class WorkflowRuntimeDTO(BaseModel):
    workflow_id: str
    trace_id: str | None = None
    response_id: str | None = None
    source: str
    specialist: str | None = None
    workflow_status: str
    runtime_mode: str | None = None
    runtime_status: str | None = None
    executed: bool | None = None
    fallback_used: bool | None = None
    reason: str | None = None
    latency_ms: int | None = None
    response_agent: str | None = None
    response_preview: str | None = None
    created_at: str


class QualityGatesDTO(BaseModel):
    generated_at: str
    route_accuracy: float | None = None
    route_accuracy_target: float = 0.95
    channel_style_pass_rate: float | None = None
    channel_style_target: float = 0.95
    final_response_quality_pass_rate: float | None = None
    final_response_quality_target: float = 0.90
    renderer_pass_rate: float | None = None
    renderer_pass_rate_target: float = 0.95
    trace_coverage: float | None = None
    trace_coverage_target: float = 1.0
    tool_execution_success_rate: float | None = None
    tool_execution_success_rate_target: float = 0.90
    confirmation_coverage: float | None = None
    confirmation_coverage_target: float = 1.0
    sample_sizes: dict[str, int]
    failing_gates: list[str]


class ReleaseReadinessCheckDTO(BaseModel):
    name: str
    passed: bool
    value: bool | int | float | str | None = None
    target: bool | int | float | str | None = None
    detail: str | None = None


class ReleaseReadinessDTO(BaseModel):
    generated_at: str
    ready: bool
    failing_checks: list[str]
    gate_failures: list[str]
    checks: list[ReleaseReadinessCheckDTO]
    quality_gates: QualityGatesDTO


class AssistantNativeMetricsDTO(BaseModel):
    generated_at: str
    interaction_sample_size: int
    continuity_resolution_count: int
    continuity_retry_replayed_count: int
    continuity_duplicate_prevented_count: int
    continuity_note_reference_resolved_count: int
    assistant_receipt_count: int
    pending_action_cleared_count: int
    project_draft_created_interaction_count: int
    project_drafts_total: int
    project_drafts_applied: int
    notes_total: int
    daily_notes_total: int
    moc_notes_total: int
    canvases_total: int
    note_links_total: int
    wiki_links_total: int
    manual_links_total: int
    semantic_links_total: int
    content_assets_total: int
    content_assets_ready_total: int
    content_assets_in_progress_total: int
    content_assets_needs_review_total: int
    content_assets_done_total: int
    notebooklm_podcast_total: int
    saved_memories_total: int
    pinned_memories_total: int
    connector_accounts_total: int
    connector_documents_total: int
    scheduled_actions_total: int
    scheduled_actions_active_total: int
    scheduled_action_runs_total: int
    approval_requests_pending_total: int
    browser_sessions_total: int


class AssistantNativeEvalCaseDTO(BaseModel):
    id: str
    description: str
    passed: bool
    baseline_passed: bool
    current_resolution_type: str | None = None
    baseline_resolution_type: str | None = None
    current_forced_specialist: str | None = None
    failures: list[str] = []


class AssistantNativeEvalSummaryDTO(BaseModel):
    generated_at: str
    dataset_id: str
    version: str
    dataset_path: str
    passing: bool
    case_count: int
    pass_count: int
    pass_rate: float
    baseline_pass_count: int
    baseline_pass_rate: float
    baseline_lift: float
    minimum_pass_rate_target: float
    minimum_baseline_lift_target: float
    minimum_case_count_target: int
    failing_case_ids: list[str]
    asset_errors: list[str] = []
    cases: list[AssistantNativeEvalCaseDTO] = []


class SecurityMetricsDTO(BaseModel):
    generated_at: str
    policy_decision_count: int
    tool_receipt_count: int
    instruction_risk_decisions: int
    trust_boundary_denies: int
    confirmation_required_count: int
    confirmation_allowed_count: int
    confirmation_denied_count: int
    confirmation_coverage: float | None = None
    mutating_receipt_count: int
    mutating_without_confirmation_count: int
    failed_mutating_receipt_count: int
    suspicious_tool_receipt_count: int
    duplicate_idempotency_key_count: int
    policy_counts: dict[str, int]
    decision_counts: dict[str, int]


class ContextSnapshotDTO(BaseModel):
    session_id: str
    configured: bool
    message_count: int
    messages: list[dict]
    summary: str
    state_packet: dict | None = None
    pending_tool_plan: dict | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _action_to_dto(a: AgentAction) -> AgentActionDTO:
    return AgentActionDTO(
        id=str(a.id),
        agent_name=a.agent_name,
        action_type=a.action_type,
        model_used=a.model_used,
        tokens_in=a.tokens_in,
        tokens_out=a.tokens_out,
        cost_usd=a.cost_usd,
        duration_ms=a.duration_ms,
        input_summary=a.input_summary,
        output_summary=a.output_summary,
        trace_id=a.trace_id,
        created_at=a.created_at.isoformat(),
    )


def _tool_receipt_to_dto(record) -> ToolReceiptDTO:
    return ToolReceiptDTO(
        id=str(record.id),
        workflow_id=_optional_string_field(getattr(record, "workflow_id", None)),
        trace_id=_optional_string_field(getattr(record, "trace_id", None)),
        interaction_id=_optional_string_field(getattr(record, "interaction_id", None)),
        idempotency_key=record.idempotency_key,
        tool_name=record.tool_name,
        server_name=record.server_name,
        mutation_class=record.mutation_class,
        status=record.status,
        argument_hash=record.argument_hash,
        arguments=_optional_dict_field(getattr(record, "arguments", None)),
        audit_metadata=_optional_dict_field(getattr(record, "audit_metadata", None)),
        result_summary=record.result_summary,
        error_message=record.error_message,
        created_at=record.created_at.isoformat(),
    )


def _policy_decision_to_dto(record) -> PolicyDecisionDTO:
    return PolicyDecisionDTO(
        id=str(record.id),
        workflow_id=_optional_string_field(getattr(record, "workflow_id", None)),
        trace_id=_optional_string_field(getattr(record, "trace_id", None)),
        specialist=_optional_string_field(getattr(record, "specialist", None)),
        policy_name=record.policy_name,
        decision=record.decision,
        reason=record.reason,
        subject_type=record.subject_type,
        subject_id=_optional_string_field(getattr(record, "subject_id", None)),
        metadata=_optional_dict_field(getattr(record, "metadata_", None)),
        created_at=record.created_at.isoformat(),
    )


def _period_to_cutoff(period: str) -> datetime:
    """Convert a period string to a UTC cutoff datetime."""
    now = datetime.now(UTC)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)
    return now - timedelta(days=7)


def _optional_string_field(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else None


def _optional_dict_field(value: object) -> dict | None:
    return value if isinstance(value, dict) else None


def _optional_bool_field(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_float_field(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _optional_int_field(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value)
    return None


async def _result_scalar_values(result: object) -> list[object]:
    if not hasattr(result, "scalars"):
        return []
    scalars = result.scalars()
    if hasattr(scalars, "__await__"):
        scalars = await scalars
    if not hasattr(scalars, "all"):
        return []
    values = scalars.all()
    if hasattr(values, "__await__"):
        values = await values
    return list(values)


async def _result_rows(result: object) -> list[object]:
    if not hasattr(result, "all"):
        return []
    values = result.all()
    if hasattr(values, "__await__"):
        values = await values
    return list(values)


def _quality_gate_thresholds_from_settings(settings) -> QualityGateThresholds:
    """Build quality-gate threshold settings used across ops endpoints."""
    return QualityGateThresholds(
        route_accuracy_target=settings.quality_gate_route_accuracy_target,
        channel_style_pass_rate_target=settings.quality_gate_channel_style_pass_rate_target,
        channel_style_score_threshold=settings.quality_gate_channel_style_score_threshold,
        final_response_quality_pass_rate_target=(
            settings.quality_gate_final_response_quality_pass_rate_target
        ),
        final_response_quality_score_threshold=(
            settings.quality_gate_final_response_quality_score_threshold
        ),
        renderer_pass_rate_target=settings.quality_gate_renderer_pass_rate_target,
        trace_coverage_target=settings.quality_gate_trace_coverage_target,
        tool_execution_success_rate_target=settings.quality_gate_tool_execution_success_rate_target,
        confirmation_coverage_target=settings.quality_gate_confirmation_coverage_target,
    )


async def _evaluate_quality_gates_for_window(
    *,
    session: AsyncSession,
    settings,
    window_days: int,
    limit: int,
):
    """Load recent records and evaluate quality gates for a time window."""
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    thresholds = _quality_gate_thresholds_from_settings(settings)

    interaction_stmt = (
        select(InteractionRecord)
        .where(InteractionRecord.created_at >= cutoff)
        .order_by(InteractionRecord.created_at.desc())
        .limit(limit)
    )
    interaction_result = await session.execute(interaction_stmt)
    interactions = list(interaction_result.scalars().all())

    tool_stmt = (
        select(ToolReceipt)
        .where(ToolReceipt.created_at >= cutoff)
        .order_by(ToolReceipt.created_at.desc())
        .limit(limit)
    )
    tool_result = await session.execute(tool_stmt)
    tool_receipts = list(tool_result.scalars().all())

    evaluation = evaluate_quality_gates(
        interactions,
        tool_receipts,
        thresholds=thresholds,
    )
    return evaluation, thresholds


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/monitoring/actions", response_model=PaginatedResponse[AgentActionDTO])
async def list_agent_actions(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    agent: str | None = Query(None),
    model: str | None = Query(None),
    sort: str = Query("newest"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
) -> PaginatedResponse[AgentActionDTO]:
    """List agent actions with filtering and sorting."""
    query = select(AgentAction)

    # --- Filters ---
    if agent:
        query = query.where(AgentAction.agent_name == agent)
    if model:
        query = query.where(AgentAction.model_used == model)
    if date_from:
        query = query.where(AgentAction.created_at >= date_from)
    if date_to:
        query = query.where(AgentAction.created_at <= date_to)

    # --- Sorting ---
    sort_map = {
        "newest": AgentAction.created_at.desc(),
        "oldest": AgentAction.created_at.asc(),
        "costliest": AgentAction.cost_usd.desc().nullslast(),
        "cheapest": AgentAction.cost_usd.asc().nullsfirst(),
        "slowest": AgentAction.duration_ms.desc().nullslast(),
        "fastest": AgentAction.duration_ms.asc().nullsfirst(),
    }
    order_clause = sort_map.get(sort, AgentAction.created_at.desc())
    query = query.order_by(order_clause)

    # --- Count ---
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar_one()

    # --- Paginate ---
    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    actions = list(result.scalars().all())

    items = [_action_to_dto(a) for a in actions]
    return paginate(items=items, total=total, offset=offset, limit=limit)


@router.get("/monitoring/llm-stats", response_model=LLMStatsDTO)
async def llm_stats(
    session: AsyncSession = Depends(get_db),
    period: str = Query("7d"),
) -> LLMStatsDTO:
    """Compute LLM usage statistics from agent_actions."""
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)
    period_cutoff = _period_to_cutoff(period)

    # --- Cost by period ---
    cost_today_row = await session.execute(
        text("SELECT COALESCE(SUM(cost_usd), 0) FROM agent_actions WHERE created_at >= :cutoff"),
        {"cutoff": today_start},
    )
    cost_today = float(cost_today_row.scalar_one())

    cost_week_row = await session.execute(
        text("SELECT COALESCE(SUM(cost_usd), 0) FROM agent_actions WHERE created_at >= :cutoff"),
        {"cutoff": week_start},
    )
    cost_week = float(cost_week_row.scalar_one())

    cost_month_row = await session.execute(
        text("SELECT COALESCE(SUM(cost_usd), 0) FROM agent_actions WHERE created_at >= :cutoff"),
        {"cutoff": month_start},
    )
    cost_month = float(cost_month_row.scalar_one())

    # --- Cost trend (daily) for the requested period ---
    cost_trend_rows = await session.execute(
        text("""
            SELECT DATE(created_at) AS d, COALESCE(SUM(cost_usd), 0) AS cost
            FROM agent_actions
            WHERE created_at >= :cutoff
            GROUP BY DATE(created_at)
            ORDER BY d
        """),
        {"cutoff": period_cutoff},
    )
    cost_trend = [CostTrendPoint(date=str(row.d), cost=float(row.cost)) for row in cost_trend_rows]

    # --- Cost by model ---
    cost_by_model_rows = await session.execute(
        text("""
            SELECT COALESCE(model_used, 'unknown') AS model, COALESCE(SUM(cost_usd), 0) AS cost
            FROM agent_actions
            WHERE created_at >= :cutoff
            GROUP BY model_used
            ORDER BY cost DESC
        """),
        {"cutoff": period_cutoff},
    )
    cost_by_model = [ModelCost(model=row.model, cost=float(row.cost)) for row in cost_by_model_rows]

    # --- Cost by agent ---
    cost_by_agent_rows = await session.execute(
        text("""
            SELECT agent_name AS agent, COALESCE(SUM(cost_usd), 0) AS cost
            FROM agent_actions
            WHERE created_at >= :cutoff
            GROUP BY agent_name
            ORDER BY cost DESC
        """),
        {"cutoff": period_cutoff},
    )
    cost_by_agent = [AgentCost(agent=row.agent, cost=float(row.cost)) for row in cost_by_agent_rows]

    # --- Token totals ---
    token_row = await session.execute(
        text("""
            SELECT COALESCE(SUM(tokens_in), 0) AS input,
                   COALESCE(SUM(tokens_out), 0) AS output
            FROM agent_actions
            WHERE created_at >= :cutoff
        """),
        {"cutoff": period_cutoff},
    )
    token_data = token_row.one()

    # --- Latency by agent ---
    latency_rows = await session.execute(
        text("""
            SELECT agent_name AS agent, COALESCE(AVG(duration_ms), 0) AS avg_ms
            FROM agent_actions
            WHERE created_at >= :cutoff
            GROUP BY agent_name
            ORDER BY avg_ms DESC
        """),
        {"cutoff": period_cutoff},
    )
    latency_by_agent = [
        AgentLatency(agent=row.agent, avg_ms=round(float(row.avg_ms), 1)) for row in latency_rows
    ]

    return LLMStatsDTO(
        cost=CostStat(today=cost_today, week=cost_week, month=cost_month),
        cost_trend=cost_trend,
        cost_by_model=cost_by_model,
        cost_by_agent=cost_by_agent,
        tokens=TokenStat(input=int(token_data.input), output=int(token_data.output)),
        latency_by_agent=latency_by_agent,
    )


@router.get("/monitoring/agent-comparison", response_model=AgentComparisonDTO)
async def agent_comparison(
    session: AsyncSession = Depends(get_db),
    period: str = Query("7d"),
) -> AgentComparisonDTO:
    """Compare agents by cost, latency, error rate, and usage."""
    period_cutoff = _period_to_cutoff(period)

    # --- Agent summaries ---
    summary_rows = await session.execute(
        text("""
            SELECT
                agent_name AS agent,
                COUNT(*) AS call_count,
                COALESCE(AVG(cost_usd), 0) AS avg_cost,
                COALESCE(AVG(duration_ms), 0) AS avg_latency_ms,
                COALESCE(
                    SUM(CASE WHEN action_type = 'error' THEN 1 ELSE 0 END)::float
                    / NULLIF(COUNT(*), 0),
                    0
                ) AS error_rate,
                COALESCE(SUM(COALESCE(tokens_in, 0) + COALESCE(tokens_out, 0)), 0) AS total_tokens
            FROM agent_actions
            WHERE created_at >= :cutoff
            GROUP BY agent_name
            ORDER BY call_count DESC
        """),
        {"cutoff": period_cutoff},
    )
    summaries = [
        AgentSummary(
            agent=row.agent,
            call_count=int(row.call_count),
            avg_cost=round(float(row.avg_cost), 6),
            avg_latency_ms=round(float(row.avg_latency_ms), 1),
            error_rate=round(float(row.error_rate), 4),
            total_tokens=int(row.total_tokens),
        )
        for row in summary_rows
    ]

    # --- Usage distribution ---
    usage_rows = await session.execute(
        text("""
            SELECT agent_name AS agent, COUNT(*) AS calls
            FROM agent_actions
            WHERE created_at >= :cutoff
            GROUP BY agent_name
            ORDER BY calls DESC
        """),
        {"cutoff": period_cutoff},
    )
    usage_distribution = [
        UsageDistribution(agent=row.agent, calls=int(row.calls)) for row in usage_rows
    ]

    return AgentComparisonDTO(
        summaries=summaries,
        usage_distribution=usage_distribution,
    )


@router.get("/monitoring/interactions/{interaction_id}", response_model=InteractionRecordDTO)
async def get_interaction(
    interaction_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> InteractionRecordDTO:
    """Get a single interaction record by ID."""
    record = await repo_get_interaction_by_id(session, interaction_id)
    if record is None:
        raise NotFoundError(f"Interaction not found: {interaction_id}")
    return InteractionRecordDTO(
        id=str(record.id),
        trace_id=_optional_string_field(getattr(record, "trace_id", None)),
        response_id=_optional_string_field(getattr(record, "response_id", None)),
        user_id=record.user_id,
        user_message=record.user_message,
        source=record.source,
        intent_type=record.intent_type,
        specialist=record.specialist,
        routing_confidence=record.routing_confidence,
        response_content=record.response_content,
        response_agent=record.response_agent,
        duration_ms=record.duration_ms,
        eval_status=record.eval_status,
        score_relevance=record.score_relevance,
        score_actionability=record.score_actionability,
        score_tone=record.score_tone,
        score_conciseness=record.score_conciseness,
        quality_scores=_optional_dict_field(getattr(record, "quality_scores", None)),
        channel_metrics=_optional_dict_field(getattr(record, "channel_metrics", None)),
        created_at=record.created_at.isoformat(),
    )


@router.get("/monitoring/quality-scores", response_model=QualityScoresDTO)
async def quality_scores(
    session: AsyncSession = Depends(get_db),
    start: datetime = Query(..., description="ISO-8601 start datetime"),
    end: datetime = Query(..., description="ISO-8601 end datetime"),
    specialist: str | None = Query(None, description="Filter by specialist agent name"),
) -> QualityScoresDTO:
    """Get average auto-judge quality scores within a time window."""
    start_dt = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_dt = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    scores = await repo_get_avg_scores(
        session,
        start=start_dt,
        end=end_dt,
        specialist=specialist,
    )

    def _round_or_none(val: float | None) -> float | None:
        return round(float(val), 4) if val is not None else None

    return QualityScoresDTO(
        relevance=_round_or_none(scores["relevance"]),
        actionability=_round_or_none(scores["actionability"]),
        tone=_round_or_none(scores["tone"]),
        conciseness=_round_or_none(scores["conciseness"]),
        count=scores["count"],
    )


@router.get("/monitoring/prompt-versions", response_model=list[PromptVersionDTO])
async def prompt_versions() -> list[PromptVersionDTO]:
    """Expose runtime prompt governance metadata for operator tooling."""
    settings = get_settings()
    records = [
        PromptVersionDTO(
            kind="supervisor",
            agent="routing",
            prompt_version=PROMPT_VERSIONS.get("routing"),
            prompt_source="src/app/agents/prompts/routing.py",
            model_policy=settings.classifier_model,
            eval_rubric_id=None,
            memory_namespace=None,
            confirmation_policy=None,
            allowed_tool_patterns=[],
        )
    ]

    for specialist in sorted(Specialist, key=lambda item: item.value):
        runtime = get_agent_runtime_config(specialist, settings)
        records.append(
            PromptVersionDTO(
                kind="specialist",
                agent=specialist.value,
                prompt_version=PROMPT_VERSIONS.get(specialist.value),
                prompt_source=runtime.prompt_source,
                model_policy=runtime.model_policy,
                eval_rubric_id=runtime.eval_rubric_id,
                memory_namespace=runtime.memory_namespace,
                confirmation_policy=runtime.confirmation_policy.value,
                allowed_tool_patterns=runtime.allowed_tools,
            )
        )

    return records


@router.get("/monitoring/traces", response_model=list[TraceSummaryDTO])
@router.get("/ops/traces", response_model=list[TraceSummaryDTO])
async def list_traces(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
) -> list[TraceSummaryDTO]:
    """Return lightweight summaries of recent request traces."""
    summaries = await summarize_traces(session, limit=limit)
    return [TraceSummaryDTO(**summary) for summary in summaries]


@router.get("/monitoring/traces/{trace_id}", response_model=TraceDetailDTO)
@router.get("/ops/traces/{trace_id}", response_model=TraceDetailDTO)
async def trace_detail(
    trace_id: str,
    session: AsyncSession = Depends(get_db),
) -> TraceDetailDTO:
    """Return full span detail for one trace."""
    detail = await get_trace_detail(session, trace_id)
    if detail is None:
        raise NotFoundError(f"Trace not found: {trace_id}")
    return TraceDetailDTO(**detail)


@router.get("/monitoring/eval-outcomes", response_model=list[EvalOutcomeDTO])
@router.get("/ops/evals", response_model=list[EvalOutcomeDTO])
async def eval_outcomes(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
) -> list[EvalOutcomeDTO]:
    """List recent evaluation outcomes with quality and renderer metadata."""
    stmt = select(InteractionRecord).order_by(InteractionRecord.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    records = list(result.scalars().all())
    return [
        EvalOutcomeDTO(
            id=str(record.id),
            trace_id=record.trace_id,
            response_id=record.response_id,
            specialist=record.specialist,
            source=record.source,
            eval_status=record.eval_status,
            quality_scores=record.quality_scores,
            channel_metrics=record.channel_metrics,
            feedback_rating=record.feedback_rating,
            created_at=record.created_at.isoformat(),
        )
        for record in records
    ]


@router.get("/monitoring/channel-metrics", response_model=list[ChannelMetricDTO])
@router.get("/ops/channel-metrics", response_model=list[ChannelMetricDTO])
async def channel_metrics(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(500, ge=1, le=5000),
) -> list[ChannelMetricDTO]:
    """Aggregate renderer/channel metrics from recent interaction records."""
    stmt = select(InteractionRecord).order_by(InteractionRecord.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    records = list(result.scalars().all())

    grouped: dict[str, list[InteractionRecord]] = {}
    for record in records:
        grouped.setdefault(record.source, []).append(record)

    metrics: list[ChannelMetricDTO] = []
    for source, source_records in grouped.items():
        latencies = [
            float(record.duration_ms) for record in source_records if record.duration_ms is not None
        ]
        chunk_counts = [
            float((record.channel_metrics or {}).get("chunk_count", 1)) for record in source_records
        ]
        retry_counts = [
            int((record.channel_metrics or {}).get("retry_count", 0)) for record in source_records
        ]
        render_failures = sum(
            1
            for record in source_records
            if (record.channel_metrics or {}).get("render_passed") is False
        )
        delivery_failures = sum(
            1
            for record in source_records
            if (record.channel_metrics or {}).get("delivery_status")
            in {"failed", "partial_failure"}
        )
        chunked_count = sum(
            1
            for record in source_records
            if float((record.channel_metrics or {}).get("chunk_count", 1)) > 1
        )
        anchors_requested = sum(
            1
            for record in source_records
            if (record.channel_metrics or {}).get("reply_anchor_requested") is True
        )
        anchors_dropped = sum(
            1
            for record in source_records
            if (record.channel_metrics or {}).get("reply_anchor_dropped") is True
        )
        callback_attempts = sum(
            int((record.channel_metrics or {}).get("feedback_callback_attempts", 0))
            for record in source_records
        )
        callback_successes = sum(
            int((record.channel_metrics or {}).get("feedback_callback_successes", 0))
            for record in source_records
        )

        interaction_count = len(source_records)
        metrics.append(
            ChannelMetricDTO(
                source=source,
                interaction_count=interaction_count,
                avg_latency_ms=round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
                avg_chunk_count=(
                    round(sum(chunk_counts) / len(chunk_counts), 2) if chunk_counts else 0.0
                ),
                render_failures=render_failures,
                delivery_failures=delivery_failures,
                delivery_success_rate=(
                    round((interaction_count - delivery_failures) / interaction_count, 3)
                    if interaction_count
                    else 1.0
                ),
                avg_retry_count=(
                    round(sum(retry_counts) / len(retry_counts), 3) if retry_counts else 0.0
                ),
                total_retry_count=sum(retry_counts),
                chunked_delivery_rate=(
                    round(chunked_count / interaction_count, 3) if interaction_count else 0.0
                ),
                reply_anchor_drop_rate=(
                    round(anchors_dropped / anchors_requested, 3) if anchors_requested else None
                ),
                feedback_callback_success_rate=(
                    round(callback_successes / callback_attempts, 3) if callback_attempts else None
                ),
            )
        )

    metrics.sort(key=lambda item: item.source)
    return metrics


@router.get("/monitoring/telegram-webhook", response_model=TelegramWebhookStatusDTO)
@router.get("/ops/webhook-status", response_model=TelegramWebhookStatusDTO)
async def telegram_webhook_status(request: Request) -> TelegramWebhookStatusDTO:
    """Expose current Telegram webhook state when the bot is configured."""
    telegram_service = getattr(request.app.state, "telegram_service", None)
    if telegram_service is None:
        return TelegramWebhookStatusDTO(status="not_configured")

    try:
        status = await telegram_service.get_webhook_status()
    except Exception:
        logger.warning("telegram_webhook_status_failed", exc_info=True)
        return TelegramWebhookStatusDTO(status="error")

    pending_update_count = status.get("pending_update_count")
    if isinstance(pending_update_count, bool):
        pending_update_count = int(pending_update_count)
    if not isinstance(pending_update_count, int):
        pending_update_count = 0

    warning_threshold = _TELEGRAM_PENDING_WARNING_THRESHOLD
    if pending_update_count >= warning_threshold:
        overall_status = "degraded"
    elif pending_update_count > 0:
        overall_status = "lagging"
    else:
        overall_status = "ok"

    now_timestamp = int(datetime.now(UTC).timestamp())
    last_error_date = status.get("last_error_date")
    if isinstance(last_error_date, bool):
        last_error_date = int(last_error_date)
    if not isinstance(last_error_date, int):
        last_error_date = None

    last_error_age_seconds: int | None = None
    if last_error_date is not None:
        last_error_age_seconds = max(now_timestamp - last_error_date, 0)

    has_recent_error = bool(status.get("last_error_message")) and (
        last_error_age_seconds is None
        or last_error_age_seconds <= _TELEGRAM_RECENT_ERROR_WINDOW_SECONDS
    )
    if has_recent_error:
        overall_status = "degraded"

    payload = dict(status)
    payload.update(
        {
            "pending_update_count": pending_update_count,
            "last_error_date": last_error_date,
            "last_error_age_seconds": last_error_age_seconds,
            "webhook_lagging": pending_update_count > 0,
            "pending_updates_warning_threshold": warning_threshold,
        }
    )
    return TelegramWebhookStatusDTO(status=overall_status, **payload)


@router.get("/ops/tool-receipts", response_model=list[ToolReceiptDTO])
async def tool_receipts(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=250),
) -> list[ToolReceiptDTO]:
    """List recent tool receipts for operator inspection."""
    records = await list_tool_receipts(session, limit=limit)
    return [_tool_receipt_to_dto(record) for record in records]


@router.get("/ops/policy-decisions", response_model=list[PolicyDecisionDTO])
async def policy_decisions(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=250),
) -> list[PolicyDecisionDTO]:
    """List recent runtime policy decisions."""
    records = await list_policy_decisions(session, limit=limit)
    return [_policy_decision_to_dto(record) for record in records]


@router.get("/ops/workflow-shadows", response_model=list[WorkflowShadowDTO])
async def workflow_shadows(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=250),
) -> list[WorkflowShadowDTO]:
    """List recent shadow workflow comparisons."""
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.status == str(WorkflowStatus.SHADOW))
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    records = list(result.scalars().all())

    shadows: list[WorkflowShadowDTO] = []
    for record in records:
        metadata = _optional_dict_field(getattr(record, "metadata_", None)) or {}
        shadows.append(
            WorkflowShadowDTO(
                workflow_id=str(record.id),
                live_workflow_id=_optional_string_field(metadata.get("live_workflow_id")),
                trace_id=_optional_string_field(getattr(record, "trace_id", None)),
                source=record.source,
                live_specialist=_optional_string_field(metadata.get("live_specialist")),
                shadow_specialist=_optional_string_field(getattr(record, "specialist", None))
                or _optional_string_field(metadata.get("shadow_specialist")),
                route_match=_optional_bool_field(metadata.get("route_match")),
                shadow_status=_optional_string_field(metadata.get("shadow_status")),
                executed=bool(metadata.get("executed", False)),
                skipped_reason=_optional_string_field(metadata.get("skipped_reason")),
                confidence=_optional_float_field(metadata.get("confidence")),
                latency_ms=_optional_int_field(metadata.get("latency_ms")),
                result_preview=_optional_string_field(metadata.get("result_preview")),
                created_at=record.created_at.isoformat(),
            )
        )
    return shadows


@router.get("/ops/workflow-runtimes", response_model=list[WorkflowRuntimeDTO])
async def workflow_runtimes(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=250),
) -> list[WorkflowRuntimeDTO]:
    """List recent live workflow-runtime execution outcomes."""
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.status != str(WorkflowStatus.SHADOW))
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    records = list(result.scalars().all())

    runtimes: list[WorkflowRuntimeDTO] = []
    for record in records:
        metadata = _optional_dict_field(getattr(record, "metadata_", None)) or {}
        runtime = _optional_dict_field(metadata.get("workflow_runtime"))
        if not runtime:
            continue
        runtimes.append(
            WorkflowRuntimeDTO(
                workflow_id=str(record.id),
                trace_id=_optional_string_field(getattr(record, "trace_id", None)),
                response_id=_optional_string_field(getattr(record, "response_id", None)),
                source=record.source,
                specialist=_optional_string_field(getattr(record, "specialist", None)),
                workflow_status=record.status,
                runtime_mode=_optional_string_field(runtime.get("mode")),
                runtime_status=_optional_string_field(runtime.get("status")),
                executed=_optional_bool_field(runtime.get("executed")),
                fallback_used=_optional_bool_field(runtime.get("fallback_used")),
                reason=_optional_string_field(runtime.get("reason")),
                latency_ms=_optional_int_field(runtime.get("latency_ms")),
                response_agent=_optional_string_field(runtime.get("response_agent")),
                response_preview=_optional_string_field(runtime.get("response_preview")),
                created_at=record.created_at.isoformat(),
            )
        )

    return runtimes


@router.get("/ops/quality-gates", response_model=QualityGatesDTO)
async def quality_gates(
    session: AsyncSession = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
    limit: int = Query(2000, ge=100, le=10000),
) -> QualityGatesDTO:
    """Return measured quality-gate performance over a recent window."""
    settings = get_settings()
    evaluation, thresholds = await _evaluate_quality_gates_for_window(
        session=session,
        settings=settings,
        window_days=window_days,
        limit=limit,
    )

    return QualityGatesDTO(
        generated_at=datetime.now(UTC).isoformat(),
        route_accuracy=(
            round(evaluation.route_accuracy, 4) if evaluation.route_accuracy is not None else None
        ),
        route_accuracy_target=thresholds.route_accuracy_target,
        channel_style_pass_rate=(
            round(evaluation.channel_style_pass_rate, 4)
            if evaluation.channel_style_pass_rate is not None
            else None
        ),
        channel_style_target=thresholds.channel_style_pass_rate_target,
        final_response_quality_pass_rate=(
            round(evaluation.final_response_quality_pass_rate, 4)
            if evaluation.final_response_quality_pass_rate is not None
            else None
        ),
        final_response_quality_target=thresholds.final_response_quality_pass_rate_target,
        renderer_pass_rate=(
            round(evaluation.renderer_pass_rate, 4)
            if evaluation.renderer_pass_rate is not None
            else None
        ),
        renderer_pass_rate_target=thresholds.renderer_pass_rate_target,
        trace_coverage=(
            round(evaluation.trace_coverage, 4) if evaluation.trace_coverage is not None else None
        ),
        trace_coverage_target=thresholds.trace_coverage_target,
        tool_execution_success_rate=(
            round(evaluation.tool_execution_success_rate, 4)
            if evaluation.tool_execution_success_rate is not None
            else None
        ),
        tool_execution_success_rate_target=thresholds.tool_execution_success_rate_target,
        confirmation_coverage=(
            round(evaluation.confirmation_coverage, 4)
            if evaluation.confirmation_coverage is not None
            else None
        ),
        confirmation_coverage_target=thresholds.confirmation_coverage_target,
        sample_sizes=evaluation.sample_sizes,
        failing_gates=evaluation.failing_gates,
    )


@router.get("/ops/assistant-native-evals", response_model=AssistantNativeEvalSummaryDTO)
async def assistant_native_evals() -> AssistantNativeEvalSummaryDTO:
    """Return deterministic replay coverage for assistant-native continuity behavior."""
    asset_errors = validate_assistant_native_eval_assets()
    if asset_errors:
        return AssistantNativeEvalSummaryDTO(
            generated_at=datetime.now(UTC).isoformat(),
            dataset_id="assistant_native_continuity.v1",
            version="unknown",
            dataset_path=ASSISTANT_NATIVE_EVAL_DATASET_PATH.as_posix(),
            passing=False,
            case_count=0,
            pass_count=0,
            pass_rate=0.0,
            baseline_pass_count=0,
            baseline_pass_rate=0.0,
            baseline_lift=0.0,
            minimum_pass_rate_target=1.0,
            minimum_baseline_lift_target=0.0,
            minimum_case_count_target=1,
            failing_case_ids=[],
            asset_errors=asset_errors,
            cases=[],
        )

    result = evaluate_assistant_native_replays()
    return AssistantNativeEvalSummaryDTO(
        generated_at=result.generated_at.isoformat(),
        dataset_id=result.dataset_id,
        version=result.version,
        dataset_path=ASSISTANT_NATIVE_EVAL_DATASET_PATH.as_posix(),
        passing=result.passing,
        case_count=result.case_count,
        pass_count=result.pass_count,
        pass_rate=result.pass_rate,
        baseline_pass_count=result.baseline_pass_count,
        baseline_pass_rate=result.baseline_pass_rate,
        baseline_lift=result.baseline_lift,
        minimum_pass_rate_target=result.minimum_pass_rate_target,
        minimum_baseline_lift_target=result.minimum_baseline_lift_target,
        minimum_case_count_target=result.minimum_case_count_target,
        failing_case_ids=result.failing_case_ids,
        asset_errors=[],
        cases=[
            AssistantNativeEvalCaseDTO(
                id=case.id,
                description=case.description,
                passed=case.passed,
                baseline_passed=case.baseline_passed,
                current_resolution_type=case.current_resolution_type,
                baseline_resolution_type=case.baseline_resolution_type,
                current_forced_specialist=case.current_forced_specialist,
                failures=case.failures,
            )
            for case in result.cases
        ],
    )


@router.get("/ops/release-readiness", response_model=ReleaseReadinessDTO)
async def release_readiness(
    request: Request,
    session: AsyncSession = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
    limit: int = Query(2000, ge=100, le=10000),
) -> ReleaseReadinessDTO:
    """Return production-readiness status against runtime quality and ops gates."""
    settings = get_settings()
    assistant_native_asset_errors = validate_assistant_native_eval_assets()
    assistant_native_eval = (
        evaluate_assistant_native_replays() if not assistant_native_asset_errors else None
    )
    evaluation, thresholds = await _evaluate_quality_gates_for_window(
        session=session,
        settings=settings,
        window_days=window_days,
        limit=limit,
    )

    quality = QualityGatesDTO(
        generated_at=datetime.now(UTC).isoformat(),
        route_accuracy=(
            round(evaluation.route_accuracy, 4) if evaluation.route_accuracy is not None else None
        ),
        route_accuracy_target=thresholds.route_accuracy_target,
        channel_style_pass_rate=(
            round(evaluation.channel_style_pass_rate, 4)
            if evaluation.channel_style_pass_rate is not None
            else None
        ),
        channel_style_target=thresholds.channel_style_pass_rate_target,
        final_response_quality_pass_rate=(
            round(evaluation.final_response_quality_pass_rate, 4)
            if evaluation.final_response_quality_pass_rate is not None
            else None
        ),
        final_response_quality_target=thresholds.final_response_quality_pass_rate_target,
        renderer_pass_rate=(
            round(evaluation.renderer_pass_rate, 4)
            if evaluation.renderer_pass_rate is not None
            else None
        ),
        renderer_pass_rate_target=thresholds.renderer_pass_rate_target,
        trace_coverage=(
            round(evaluation.trace_coverage, 4) if evaluation.trace_coverage is not None else None
        ),
        trace_coverage_target=thresholds.trace_coverage_target,
        tool_execution_success_rate=(
            round(evaluation.tool_execution_success_rate, 4)
            if evaluation.tool_execution_success_rate is not None
            else None
        ),
        tool_execution_success_rate_target=thresholds.tool_execution_success_rate_target,
        confirmation_coverage=(
            round(evaluation.confirmation_coverage, 4)
            if evaluation.confirmation_coverage is not None
            else None
        ),
        confirmation_coverage_target=thresholds.confirmation_coverage_target,
        sample_sizes=evaluation.sample_sizes,
        failing_gates=evaluation.failing_gates,
    )

    preflight_report = getattr(request.app.state, "preflight_report", None)
    if preflight_report is None:
        preflight_report = getattr(request.app.state, "startup_preflight_report", None)
    preflight_status = None
    if preflight_report is not None:
        preflight_status = getattr(preflight_report, "status", None)
        if preflight_status is None and isinstance(preflight_report, dict):
            preflight_status = preflight_report.get("status")

    minimum_interactions = int(getattr(settings, "quality_gates_alert_min_interactions", 25))
    interaction_count = int(quality.sample_sizes.get("interactions", 0))

    checks = [
        ReleaseReadinessCheckDTO(
            name="quality_gates_pass",
            passed=len(quality.failing_gates) == 0,
            value=len(quality.failing_gates) == 0,
            target=True,
            detail=(
                ", ".join(quality.failing_gates)
                if quality.failing_gates
                else "all quality gates passing"
            ),
        ),
        ReleaseReadinessCheckDTO(
            name="quality_gate_sample_size",
            passed=interaction_count >= minimum_interactions,
            value=interaction_count,
            target=minimum_interactions,
            detail="minimum recent interactions required for reliable gate scoring",
        ),
        ReleaseReadinessCheckDTO(
            name="workflow_live_runtime_enabled",
            passed=bool(settings.workflow_live_runtime_enabled),
            value=bool(settings.workflow_live_runtime_enabled),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="auto_judge_enabled",
            passed=bool(settings.auto_judge_enabled),
            value=bool(settings.auto_judge_enabled),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="quality_gates_alerts_enabled",
            passed=bool(settings.quality_gates_alerts_enabled),
            value=bool(settings.quality_gates_alerts_enabled),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="session_maintenance_enabled",
            passed=bool(settings.session_maintenance_enabled),
            value=bool(settings.session_maintenance_enabled),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="continuity_runtime_enabled",
            passed=bool(getattr(settings, "continuity_runtime_enabled", True)),
            value=bool(getattr(settings, "continuity_runtime_enabled", True)),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="project_draft_runtime_enabled",
            passed=bool(getattr(settings, "project_draft_runtime_enabled", True)),
            value=bool(getattr(settings, "project_draft_runtime_enabled", True)),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="notes_workspace_enabled",
            passed=bool(getattr(settings, "notes_workspace_enabled", True)),
            value=bool(getattr(settings, "notes_workspace_enabled", True)),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="content_factory_enabled",
            passed=bool(getattr(settings, "content_factory_enabled", True)),
            value=bool(getattr(settings, "content_factory_enabled", True)),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="assistant_native_replay_eval_enabled",
            passed=bool(getattr(settings, "assistant_native_replay_eval_enabled", True)),
            value=bool(getattr(settings, "assistant_native_replay_eval_enabled", True)),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="assistant_native_replay_assets",
            passed=not assistant_native_asset_errors,
            value="ok" if not assistant_native_asset_errors else "invalid",
            target="ok",
            detail=", ".join(assistant_native_asset_errors[:3]) or None,
        ),
        ReleaseReadinessCheckDTO(
            name="assistant_native_replay_pass_rate",
            passed=assistant_native_eval is not None
            and assistant_native_eval.pass_rate
            >= float(getattr(settings, "assistant_native_replay_pass_rate_target", 1.0)),
            value=(
                round(assistant_native_eval.pass_rate, 4)
                if assistant_native_eval is not None
                else None
            ),
            target=float(getattr(settings, "assistant_native_replay_pass_rate_target", 1.0)),
            detail=(
                ", ".join(assistant_native_eval.failing_case_ids)
                if assistant_native_eval is not None and assistant_native_eval.failing_case_ids
                else ("all replay cases passing" if assistant_native_eval is not None else None)
            ),
        ),
        ReleaseReadinessCheckDTO(
            name="assistant_native_replay_baseline_lift",
            passed=(
                assistant_native_eval is not None
                and assistant_native_eval.baseline_lift
                >= float(getattr(settings, "assistant_native_replay_baseline_lift_target", 0.5))
            ),
            value=(
                round(assistant_native_eval.baseline_lift, 4)
                if assistant_native_eval is not None
                else None
            ),
            target=float(getattr(settings, "assistant_native_replay_baseline_lift_target", 0.5)),
        ),
        ReleaseReadinessCheckDTO(
            name="sentry_configured",
            passed=bool(settings.sentry_configured),
            value=bool(settings.sentry_configured),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="posthog_configured",
            passed=bool(settings.posthog_configured),
            value=bool(settings.posthog_configured),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="startup_preflight",
            passed=preflight_status in {"ok", "warn"},
            value=preflight_status or "missing",
            target="ok|warn",
            detail="startup preflight report should be present and non-failing",
        ),
    ]

    failing_checks = [check.name for check in checks if not check.passed]
    ready = len(failing_checks) == 0

    return ReleaseReadinessDTO(
        generated_at=datetime.now(UTC).isoformat(),
        ready=ready,
        failing_checks=failing_checks,
        gate_failures=quality.failing_gates,
        checks=checks,
        quality_gates=quality,
    )


@router.get("/ops/assistant-native-metrics", response_model=AssistantNativeMetricsDTO)
async def assistant_native_metrics(
    session: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=90),
    limit: int = Query(2000, ge=100, le=10000),
) -> AssistantNativeMetricsDTO:
    """Aggregate continuity, second-brain, project draft, and content-factory signals."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    interactions_result = await session.execute(
        select(InteractionRecord.channel_metrics)
        .where(InteractionRecord.created_at >= cutoff)
        .order_by(InteractionRecord.created_at.desc())
        .limit(limit)
    )
    interaction_metrics = [
        metrics
        for metrics in await _result_scalar_values(interactions_result)
        if isinstance(metrics, dict)
    ]

    note_kinds_result = await session.execute(select(Note.kind).where(Note.deleted_at.is_(None)))
    note_kinds = [
        value
        for value in await _result_scalar_values(note_kinds_result)
        if isinstance(value, str) or value is None
    ]

    canvas_ids_result = await session.execute(
        select(NoteCanvas.id).where(NoteCanvas.deleted_at.is_(None))
    )
    canvas_ids = await _result_scalar_values(canvas_ids_result)

    note_link_types_result = await session.execute(select(NoteLink.link_type))
    note_link_types = [
        value
        for value in await _result_scalar_values(note_link_types_result)
        if isinstance(value, str)
    ]

    project_drafts_result = await session.execute(
        select(ProjectDraft.status, ProjectDraft.applied_project_id)
    )
    project_draft_rows = await _result_rows(project_drafts_result)

    content_assets_result = await session.execute(
        select(ContentAsset.status, ContentAsset.asset_type).where(
            ContentAsset.deleted_at.is_(None)
        )
    )
    content_asset_rows = await _result_rows(content_assets_result)

    saved_memories_result = await session.execute(
        select(SavedMemory.pinned).where(SavedMemory.deleted_at.is_(None))
    )
    saved_memory_pins = await _result_scalar_values(saved_memories_result)

    connector_accounts_result = await session.execute(
        select(ConnectorAccount.id).where(ConnectorAccount.deleted_at.is_(None))
    )
    connector_account_ids = await _result_scalar_values(connector_accounts_result)

    connector_documents_result = await session.execute(
        select(ConnectorDocument.id).where(ConnectorDocument.deleted_at.is_(None))
    )
    connector_document_ids = await _result_scalar_values(connector_documents_result)

    scheduled_actions_result = await session.execute(
        select(ScheduledAction.status).where(ScheduledAction.deleted_at.is_(None))
    )
    scheduled_action_statuses = await _result_scalar_values(scheduled_actions_result)

    scheduled_action_runs_result = await session.execute(select(ScheduledActionRun.id))
    scheduled_action_run_ids = await _result_scalar_values(scheduled_action_runs_result)

    approval_requests_result = await session.execute(select(ApprovalRequest.status))
    approval_request_statuses = await _result_scalar_values(approval_requests_result)

    browser_sessions_result = await session.execute(select(BrowserSession.id))
    browser_session_ids = await _result_scalar_values(browser_sessions_result)

    continuity_resolution_count = sum(
        1
        for metrics in interaction_metrics
        if isinstance(metrics.get("continuity_resolution_type"), str)
    )
    continuity_retry_replayed_count = sum(
        1 for metrics in interaction_metrics if bool(metrics.get("continuity_retry_replayed"))
    )
    continuity_duplicate_prevented_count = sum(
        1 for metrics in interaction_metrics if bool(metrics.get("continuity_duplicate_prevented"))
    )
    continuity_note_reference_resolved_count = sum(
        1
        for metrics in interaction_metrics
        if bool(metrics.get("continuity_note_reference_resolved"))
    )
    assistant_receipt_count = sum(
        1 for metrics in interaction_metrics if bool(metrics.get("assistant_receipt_present"))
    )
    pending_action_cleared_count = sum(
        1 for metrics in interaction_metrics if bool(metrics.get("pending_action_cleared"))
    )
    project_draft_created_interaction_count = sum(
        1 for metrics in interaction_metrics if bool(metrics.get("project_draft_created"))
    )

    project_drafts_total = len(project_draft_rows)
    project_drafts_applied = sum(
        1
        for row in project_draft_rows
        if (isinstance(row, tuple) and len(row) >= 2 and row[0] == "applied" and row[1] is not None)
    )

    content_assets_total = len(content_asset_rows)
    content_assets_ready_total = sum(
        1
        for row in content_asset_rows
        if isinstance(row, tuple) and len(row) >= 1 and row[0] == "ready"
    )
    content_assets_in_progress_total = sum(
        1
        for row in content_asset_rows
        if isinstance(row, tuple) and len(row) >= 1 and row[0] == "in_progress"
    )
    content_assets_needs_review_total = sum(
        1
        for row in content_asset_rows
        if isinstance(row, tuple) and len(row) >= 1 and row[0] == "needs_review"
    )
    content_assets_done_total = sum(
        1
        for row in content_asset_rows
        if isinstance(row, tuple) and len(row) >= 1 and row[0] == "done"
    )
    notebooklm_podcast_total = sum(
        1
        for row in content_asset_rows
        if isinstance(row, tuple) and len(row) >= 2 and row[1] == "notebooklm_podcast"
    )

    return AssistantNativeMetricsDTO(
        generated_at=datetime.now(UTC).isoformat(),
        interaction_sample_size=len(interaction_metrics),
        continuity_resolution_count=continuity_resolution_count,
        continuity_retry_replayed_count=continuity_retry_replayed_count,
        continuity_duplicate_prevented_count=continuity_duplicate_prevented_count,
        continuity_note_reference_resolved_count=continuity_note_reference_resolved_count,
        assistant_receipt_count=assistant_receipt_count,
        pending_action_cleared_count=pending_action_cleared_count,
        project_draft_created_interaction_count=project_draft_created_interaction_count,
        project_drafts_total=project_drafts_total,
        project_drafts_applied=project_drafts_applied,
        notes_total=len(note_kinds),
        daily_notes_total=sum(1 for kind in note_kinds if kind == "daily"),
        moc_notes_total=sum(1 for kind in note_kinds if kind == "moc"),
        canvases_total=len(canvas_ids),
        note_links_total=len(note_link_types),
        wiki_links_total=sum(1 for link_type in note_link_types if link_type == "wiki"),
        manual_links_total=sum(1 for link_type in note_link_types if link_type == "manual"),
        semantic_links_total=sum(1 for link_type in note_link_types if link_type == "semantic"),
        content_assets_total=content_assets_total,
        content_assets_ready_total=content_assets_ready_total,
        content_assets_in_progress_total=content_assets_in_progress_total,
        content_assets_needs_review_total=content_assets_needs_review_total,
        content_assets_done_total=content_assets_done_total,
        notebooklm_podcast_total=notebooklm_podcast_total,
        saved_memories_total=len(saved_memory_pins),
        pinned_memories_total=sum(1 for value in saved_memory_pins if bool(value)),
        connector_accounts_total=len(connector_account_ids),
        connector_documents_total=len(connector_document_ids),
        scheduled_actions_total=len(scheduled_action_statuses),
        scheduled_actions_active_total=sum(
            1 for value in scheduled_action_statuses if value == "active"
        ),
        scheduled_action_runs_total=len(scheduled_action_run_ids),
        approval_requests_pending_total=sum(
            1 for value in approval_request_statuses if value == "pending"
        ),
        browser_sessions_total=len(browser_session_ids),
    )


@router.get("/ops/security-metrics", response_model=SecurityMetricsDTO)
async def security_metrics(
    session: AsyncSession = Depends(get_db),
    decision_limit: int = Query(500, ge=1, le=5000),
    receipt_limit: int = Query(500, ge=1, le=5000),
) -> SecurityMetricsDTO:
    """Aggregate runtime policy and mutation-safety security metrics."""
    policies = list(await list_policy_decisions(session, limit=decision_limit))
    receipts = list(await list_tool_receipts(session, limit=receipt_limit))

    policy_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    for record in policies:
        policy_name = str(getattr(record, "policy_name", "") or "unknown")
        policy_counts[policy_name] = policy_counts.get(policy_name, 0) + 1
        decision = str(getattr(record, "decision", "") or "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    instruction_risk_decisions = sum(
        1
        for record in policies
        if str(getattr(record, "policy_name", "")) == "instruction_like_content"
    )
    trust_boundary_denies = sum(
        1
        for record in policies
        if str(getattr(record, "policy_name", "")) == "tool_trust_boundary"
        and str(getattr(record, "decision", "")) == "deny"
    )
    confirmation_required_count = sum(
        1
        for record in policies
        if str(getattr(record, "policy_name", "")) == "tool_confirmation"
        and str(getattr(record, "decision", "")) == "require_confirmation"
    )
    confirmation_allowed_count = sum(
        1
        for record in policies
        if str(getattr(record, "policy_name", "")) == "tool_confirmation"
        and str(getattr(record, "decision", "")) == "allow"
    )
    confirmation_denied_count = sum(
        1
        for record in policies
        if str(getattr(record, "policy_name", "")) == "tool_confirmation"
        and str(getattr(record, "decision", "")) == "deny"
    )

    mutating_receipts = [
        record for record in receipts if str(getattr(record, "mutation_class", "")) == "mutating"
    ]
    mutating_without_confirmation_count = 0
    failed_mutating_receipt_count = 0
    suspicious_tool_receipt_count = 0
    idempotency_counts: dict[str, int] = {}
    for record in mutating_receipts:
        audit = getattr(record, "audit_metadata", None)
        audit_metadata = audit if isinstance(audit, dict) else {}
        if not bool(audit_metadata.get("confirmation_required", False)):
            mutating_without_confirmation_count += 1
        if str(getattr(record, "status", "")) == "failed":
            failed_mutating_receipt_count += 1
        if bool(audit_metadata.get("instruction_like_content", False)):
            suspicious_tool_receipt_count += 1

    for record in receipts:
        key = str(getattr(record, "idempotency_key", "") or "")
        if key:
            idempotency_counts[key] = idempotency_counts.get(key, 0) + 1
    duplicate_idempotency_key_count = sum(
        count - 1 for count in idempotency_counts.values() if count > 1
    )

    confirmation_coverage: float | None = None
    if confirmation_required_count:
        confirmation_coverage = round(
            min(
                1.0,
                (confirmation_allowed_count + confirmation_denied_count)
                / confirmation_required_count,
            ),
            3,
        )

    return SecurityMetricsDTO(
        generated_at=datetime.now(UTC).isoformat(),
        policy_decision_count=len(policies),
        tool_receipt_count=len(receipts),
        instruction_risk_decisions=instruction_risk_decisions,
        trust_boundary_denies=trust_boundary_denies,
        confirmation_required_count=confirmation_required_count,
        confirmation_allowed_count=confirmation_allowed_count,
        confirmation_denied_count=confirmation_denied_count,
        confirmation_coverage=confirmation_coverage,
        mutating_receipt_count=len(mutating_receipts),
        mutating_without_confirmation_count=mutating_without_confirmation_count,
        failed_mutating_receipt_count=failed_mutating_receipt_count,
        suspicious_tool_receipt_count=suspicious_tool_receipt_count,
        duplicate_idempotency_key_count=duplicate_idempotency_key_count,
        policy_counts=policy_counts,
        decision_counts=decision_counts,
    )


@router.get("/ops/context/{session_id}", response_model=ContextSnapshotDTO)
async def context_snapshot(
    session_id: str,
    session: AsyncSession = Depends(get_db),
) -> ContextSnapshotDTO:
    """Return the currently stored conversation context for one session/user."""
    conv_ctx = _get_conversation_context()
    if conv_ctx is None:
        return ContextSnapshotDTO(
            session_id=session_id,
            configured=False,
            message_count=0,
            messages=[],
            summary="",
            state_packet=None,
            pending_tool_plan=None,
        )

    messages = await conv_ctx.get_context(session_id)
    summary = await conv_ctx.get_summary(session_id)
    state_packet = await conv_ctx.get_state_packet(session_id)
    pending_tool_plan = await conv_ctx.get_pending_tool_plan(session_id)
    if pending_tool_plan is None:
        checkpoint = await get_latest_pending_workflow_checkpoint_for_user(
            session,
            user_id=session_id,
        )
        if checkpoint is not None and isinstance(getattr(checkpoint, "payload", None), dict):
            payload = dict(checkpoint.payload)
            payload.setdefault("workflow_id", str(getattr(checkpoint, "workflow_id", "")))
            payload.setdefault("checkpoint_id", str(getattr(checkpoint, "id", "")))
            try:
                pending_tool_plan = PendingToolPlan.model_validate(payload)
            except Exception:
                logger.warning("monitoring_pending_tool_plan_checkpoint_invalid", exc_info=True)

    return ContextSnapshotDTO(
        session_id=session_id,
        configured=True,
        message_count=len(messages),
        messages=[message.to_dict() for message in messages],
        summary=summary,
        state_packet=(state_packet.model_dump(mode="json") if state_packet is not None else None),
        pending_tool_plan=(
            pending_tool_plan.model_dump(mode="json") if pending_tool_plan is not None else None
        ),
    )


class SLOValueDTO(BaseModel):
    name: str
    current: float
    target: float
    unit: str
    meets_target: bool
    burn_rate: float
    sample_size: int
    details: dict


class SLOReportDTO(BaseModel):
    window_hours: int
    generated_at: str
    slos: list[SLOValueDTO]


@router.get("/monitoring/slo", response_model=SLOReportDTO)
@router.get("/ops/slo", response_model=SLOReportDTO)
async def slo_report(
    session: AsyncSession = Depends(get_db),
    window_hours: int = Query(24, ge=1, le=168),
) -> SLOReportDTO:
    """Return current SLO values, targets and burn rates.

    Covers the five SLOs defined in :mod:`src.app.core.slo`:
    latency, error, quality (7-day rolling p10 of auto-judge scores),
    goodput (combined latency + quality), and cost (daily spend in GBP).
    """
    settings = get_settings()
    report = await collect_slo_report(session, settings, window_hours=window_hours)
    return SLOReportDTO(
        window_hours=report.window_hours,
        generated_at=report.generated_at.isoformat(),
        slos=[SLOValueDTO(**slo.as_dict()) for slo in report.slos],
    )
