import { absolutePath, api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { HealthStatus, AgentAction, AgentName, PaginatedResponse } from "@/types";

// ─── System Health ──────────────────────────────────────────
// Health endpoint is registered at /health (no /api prefix)
export function getHealth(): Promise<HealthStatus> {
  return fetch(absolutePath(API_PATHS.health), {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  }).then((r) => {
    if (!r.ok) throw new Error(`Health check failed: ${r.status}`);
    return r.json() as Promise<HealthStatus>;
  });
}

export interface PreflightCheck {
  name: string;
  status: "ok" | "warn" | "fail" | "skipped";
  message: string;
  required: boolean;
  details: Record<string, unknown>;
}

export interface PreflightReport {
  status: "ok" | "warn" | "fail";
  generated_at: string;
  checks: PreflightCheck[];
}

export function getPreflightReport(): Promise<PreflightReport> {
  return fetch(absolutePath(API_PATHS.healthPreflight), {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  }).then((r) => {
    if (!r.ok) throw new Error(`Preflight check failed: ${r.status}`);
    return r.json() as Promise<PreflightReport>;
  });
}

// ─── Agent Actions ──────────────────────────────────────────
export interface AgentActionQueryParams {
  limit?: number;
  offset?: number;
  agent?: AgentName;
  model?: string;
  sort?: "newest" | "oldest" | "costliest" | "cheapest" | "slowest" | "fastest";
  date_from?: string;
  date_to?: string;
}

export function getAgentActions(
  params: AgentActionQueryParams = {},
): Promise<PaginatedResponse<AgentAction>> {
  return getWithQuery<PaginatedResponse<AgentAction>, AgentActionQueryParams>(
    apiPath(API_PATHS.apiMonitoringActions),
    params,
  );
}

// ─── LLM Stats ──────────────────────────────────────────────
export interface CostStat {
  today: number;
  week: number;
  month: number;
}

export interface CostTrendPoint {
  date: string;
  cost: number;
}

export interface ModelCost {
  model: string;
  cost: number;
}

export interface AgentCost {
  agent: AgentName;
  cost: number;
}

export interface TokenStat {
  input: number;
  output: number;
}

export interface AgentLatency {
  agent: AgentName;
  avg_ms: number;
}

export interface LLMStats {
  cost: CostStat;
  cost_trend: CostTrendPoint[];
  cost_by_model: ModelCost[];
  cost_by_agent: AgentCost[];
  tokens: TokenStat;
  latency_by_agent: AgentLatency[];
}

export function getLLMStats(period: "today" | "7d" | "30d" = "7d"): Promise<LLMStats> {
  return api.get<LLMStats>(apiPath(API_PATHS.apiMonitoringLlmStats), { period });
}

// ─── Agent Comparison ───────────────────────────────────────
export interface AgentSummary {
  agent: AgentName;
  call_count: number;
  avg_cost: number;
  avg_latency_ms: number;
  error_rate: number;
  total_tokens: number;
}

export interface AgentComparisonData {
  summaries: AgentSummary[];
  usage_distribution: Array<{ agent: AgentName; calls: number }>;
}

export function getAgentComparison(
  period: "today" | "7d" | "30d" = "7d",
): Promise<AgentComparisonData> {
  return api.get<AgentComparisonData>(apiPath(API_PATHS.apiMonitoringAgentComparison), { period });
}

export interface PromptVersionRecord {
  kind: "specialist" | "supervisor";
  agent: string;
  prompt_version: string | null;
  prompt_source: string;
  model_policy: string;
  eval_rubric_id: string | null;
  memory_namespace: string | null;
  confirmation_policy: string | null;
  allowed_tool_patterns: string[];
}

export function getPromptVersions(): Promise<PromptVersionRecord[]> {
  return api.get<PromptVersionRecord[]>(apiPath(API_PATHS.apiMonitoringPromptVersions));
}

// ─── Trace / Runtime Monitoring ────────────────────────────
export interface TraceSummary {
  trace_id: string;
  channel: string;
  specialist: string | null;
  status: string;
  span_count: number;
  total_latency_ms: number;
  error_count: number;
  created_at: string;
}

export interface TraceSpan {
  id: string;
  parent_span_id: string | null;
  name: string;
  span_kind: string;
  channel: string;
  specialist: string | null;
  status: string;
  error_class: string | null;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  tool_name: string | null;
  cache_hit: boolean | null;
  latency_ms: number | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface TraceDetail {
  trace_id: string;
  channel: string;
  specialist: string | null;
  status: string;
  created_at: string;
  spans: TraceSpan[];
}

export interface EvalOutcome {
  id: string;
  trace_id: string | null;
  response_id: string | null;
  specialist: string;
  source: string;
  eval_status: string;
  quality_scores: Record<string, number | string | null> | null;
  channel_metrics: Record<string, number | string | boolean | null> | null;
  feedback_rating: string | null;
  created_at: string;
}

export interface ChannelMetric {
  source: string;
  interaction_count: number;
  avg_latency_ms: number;
  avg_chunk_count: number;
  render_failures: number;
  delivery_failures: number;
  delivery_success_rate: number;
  avg_retry_count: number;
  total_retry_count: number;
  chunked_delivery_rate: number;
  reply_anchor_drop_rate: number | null;
  feedback_callback_success_rate: number | null;
}

export interface TelegramWebhookStatus {
  status: string;
  url: string | null;
  pending_update_count: number | null;
  last_error_date: number | null;
  last_error_message: string | null;
  max_connections: number | null;
  last_error_age_seconds: number | null;
  webhook_lagging: boolean | null;
  pending_updates_warning_threshold: number | null;
}

export interface SecurityMetrics {
  generated_at: string;
  policy_decision_count: number;
  tool_receipt_count: number;
  instruction_risk_decisions: number;
  trust_boundary_denies: number;
  confirmation_required_count: number;
  confirmation_allowed_count: number;
  confirmation_denied_count: number;
  confirmation_coverage: number | null;
  mutating_receipt_count: number;
  mutating_without_confirmation_count: number;
  failed_mutating_receipt_count: number;
  suspicious_tool_receipt_count: number;
  duplicate_idempotency_key_count: number;
  policy_counts: Record<string, number>;
  decision_counts: Record<string, number>;
}

export interface AssistantNativeMetrics {
  generated_at: string;
  interaction_sample_size: number;
  continuity_resolution_count: number;
  continuity_retry_replayed_count: number;
  continuity_duplicate_prevented_count: number;
  continuity_note_reference_resolved_count: number;
  assistant_receipt_count: number;
  pending_action_cleared_count: number;
  project_draft_created_interaction_count: number;
  project_drafts_total: number;
  project_drafts_applied: number;
  notes_total: number;
  daily_notes_total: number;
  moc_notes_total: number;
  canvases_total: number;
  note_links_total: number;
  wiki_links_total: number;
  manual_links_total: number;
  semantic_links_total: number;
  content_assets_total: number;
  content_assets_ready_total: number;
  content_assets_in_progress_total: number;
  content_assets_needs_review_total: number;
  content_assets_done_total: number;
  notebooklm_podcast_total: number;
  saved_memories_total: number;
  pinned_memories_total: number;
  connector_accounts_total: number;
  connector_documents_total: number;
  scheduled_actions_total: number;
  scheduled_actions_active_total: number;
  scheduled_action_runs_total: number;
  approval_requests_pending_total: number;
  browser_sessions_total: number;
}

export interface AssistantNativeEvalCase {
  id: string;
  description: string;
  passed: boolean;
  baseline_passed: boolean;
  current_resolution_type: string | null;
  baseline_resolution_type: string | null;
  current_forced_specialist: string | null;
  failures: string[];
}

export interface AssistantNativeEvalSummary {
  generated_at: string;
  dataset_id: string;
  version: string;
  dataset_path: string;
  passing: boolean;
  case_count: number;
  pass_count: number;
  pass_rate: number;
  baseline_pass_count: number;
  baseline_pass_rate: number;
  baseline_lift: number;
  minimum_pass_rate_target: number;
  minimum_baseline_lift_target: number;
  minimum_case_count_target: number;
  failing_case_ids: string[];
  asset_errors: string[];
  cases: AssistantNativeEvalCase[];
}

export function getTraceSummaries(limit = 25): Promise<TraceSummary[]> {
  return api.get<TraceSummary[]>(apiPath(API_PATHS.apiMonitoringTraces), { limit });
}

export function getAssistantNativeMetrics(): Promise<AssistantNativeMetrics> {
  return api.get<AssistantNativeMetrics>(apiPath(API_PATHS.apiOpsAssistantNativeMetrics));
}

export function getAssistantNativeEvalSummary(): Promise<AssistantNativeEvalSummary> {
  return api.get<AssistantNativeEvalSummary>(apiPath(API_PATHS.apiOpsAssistantNativeEvals));
}

export function getTraceDetail(traceId: string): Promise<TraceDetail> {
  return api.get<TraceDetail>(
    apiPath(API_PATHS.apiMonitoringTracesByTraceId, { trace_id: traceId }),
  );
}

export function getEvalOutcomes(limit = 25): Promise<EvalOutcome[]> {
  return api.get<EvalOutcome[]>(apiPath(API_PATHS.apiMonitoringEvalOutcomes), { limit });
}

export function getChannelMetrics(limit = 500): Promise<ChannelMetric[]> {
  return api.get<ChannelMetric[]>(apiPath(API_PATHS.apiMonitoringChannelMetrics), { limit });
}

export function getTelegramWebhookStatus(): Promise<TelegramWebhookStatus> {
  return api.get<TelegramWebhookStatus>(apiPath(API_PATHS.apiMonitoringTelegramWebhook));
}

export function getSecurityMetrics(): Promise<SecurityMetrics> {
  return api.get<SecurityMetrics>(apiPath(API_PATHS.apiOpsSecurityMetrics));
}

// ─── Interaction Detail ────────────────────────────────────
export interface InteractionRecord {
  id: string;
  agent_name: AgentName;
  user_message: string;
  agent_response: string;
  model_used: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  duration_ms: number | null;
  quality_scores: Record<string, number> | null;
  created_at: string;
}

export function getInteractionDetail(id: string): Promise<InteractionRecord> {
  return api.get<InteractionRecord>(
    apiPath(API_PATHS.apiMonitoringInteractionsByInteractionId, {
      interaction_id: id,
    }),
  );
}

// ─── Quality Scores ────────────────────────────────────────
export interface QualityScorePoint {
  date: string;
  agent: AgentName;
  avg_score: number;
  count: number;
}

export interface QualityScoresParams {
  start: string;
  end: string;
  agent?: AgentName;
}

export function getQualityScores(params: QualityScoresParams): Promise<QualityScorePoint[]> {
  return getWithQuery<QualityScorePoint[], QualityScoresParams>(
    apiPath(API_PATHS.apiMonitoringQualityScores),
    params,
  );
}
