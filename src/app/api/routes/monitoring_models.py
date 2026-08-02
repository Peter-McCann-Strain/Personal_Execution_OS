"""Response models shared by monitoring and operator endpoints."""

from pydantic import BaseModel


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


# Keep the existing qualified OpenAPI component name where this DTO collides
# with another schema named ``ToolReceiptDTO`` elsewhere in the application.
ToolReceiptDTO.__module__ = "src.app.api.routes.monitoring"
ToolReceiptDTO.model_rebuild(force=True)
