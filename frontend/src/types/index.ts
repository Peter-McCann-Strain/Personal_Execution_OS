// ─── Agent Types ─────────────────────────────────────────────
export type AgentName =
  | "diary"
  | "memory"
  | "research"
  | "review"
  | "project"
  | "communications"
  | "tools"
  | "notification"
  | "save"
  | "plan_day"
  | "socratic";

export type MessageSource = "api" | "telegram" | "voice";

// ─── Chat ────────────────────────────────────────────────────
export interface ChatRequest {
  content: string;
  source?: MessageSource;
  sensitive_mode?: boolean;
  suppressed_sources?: Array<"episode" | "note" | "saved_memory" | "connector_document">;
}

export interface ChatResponse {
  content: string;
  agent: AgentName;
  metadata: Record<string, unknown>;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  agent?: AgentName;
  metadata?: Record<string, unknown>;
  timestamp: string;
  isStreaming?: boolean;
}

export interface WorkflowRunStep {
  id: string;
  workflow_id: string;
  step_type: string;
  title: string;
  status: string;
  details: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ApprovalRequest {
  id: string;
  workflow_id: string;
  checkpoint_id: string | null;
  request_kind: string;
  title: string;
  description: string | null;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
  resolved_at: string | null;
  updated_at: string;
}

export interface BrowserSession {
  id: string;
  workflow_id: string;
  status: string;
  start_url: string | null;
  current_url: string | null;
  timeline: Array<Record<string, unknown>>;
  screenshot_artifacts: Array<Record<string, unknown>>;
  risk_flags: string[];
  created_at: string;
  updated_at: string;
}

export interface ToolReceipt {
  id: string;
  workflow_id: string | null;
  tool_name: string;
  server_name: string | null;
  mutation_class: string;
  status: string;
  result_summary: string | null;
  error_message: string | null;
  created_at: string;
}

export interface ArtifactRecord {
  id: string;
  artifact_type: string;
  scope: string;
  summary: string;
  source_id: string | null;
  created_at: string;
  payload: Record<string, unknown>;
}

export interface AgentRunSummary {
  id: string;
  source: string;
  status: string;
  specialist: string | null;
  request_excerpt: string | null;
  pending_approvals: number;
  created_at: string;
  updated_at: string;
}

export interface AgentRunDetail extends AgentRunSummary {
  trace_id: string | null;
  response_id: string | null;
  metadata: Record<string, unknown>;
  steps: WorkflowRunStep[];
  approvals: ApprovalRequest[];
  browser_sessions: BrowserSession[];
  tool_receipts: ToolReceipt[];
  artifacts: ArtifactRecord[];
}

// ─── Diary / Episodes ────────────────────────────────────────
export type ParaCategory = "project" | "area" | "resource" | "archive";
export type EpisodeType = "diary" | "research" | "capture";

export interface Episode {
  id: string;
  content: string;
  summary: string | null;
  episode_type: EpisodeType;
  para_category: ParaCategory | null;
  mood_score: number | null;
  energy_rating: number | null;
  tags: string[];
  people_mentioned: string[];
  source: MessageSource;
  created_at: string;
}

// ─── Memory Search ───────────────────────────────────────────
export interface MemorySearchResult {
  title?: string | null;
  content: string;
  relevance_score: number;
  source_type: "episode" | "note" | "entity" | "saved_memory" | "connector_document";
  source_label: string;
  source_id: string;
  source_url?: string | null;
  provenance_label?: string | null;
}

export interface MemoryAnswer {
  answer: string;
  confidence: number;
  sources: MemorySearchResult[];
  follow_up_suggestions: string[];
}

// ─── Research ────────────────────────────────────────────────
export interface ResearchFinding {
  source: string;
  key_points: string[];
  relevance: "high" | "medium" | "low";
}

export interface DecisionOption {
  name: string;
  pros: string[];
  cons: string[];
}

export interface ResearchReport {
  title: string;
  search_queries: string[];
  findings: ResearchFinding[];
  synthesis: string;
  decision_framework: {
    options: DecisionOption[];
    recommendation: string;
  } | null;
}

// ─── Goals ───────────────────────────────────────────────────
export type GoalStatus = "active" | "paused" | "completed" | "cancelled";

export interface Goal {
  id: string;
  title: string;
  goal_type: string | null;
  parent_id: string | null;
  priority: number;
  status: GoalStatus;
  progress: number;
  deadline: string | null;
  evidence: string[];
  created_at: string;
  updated_at: string;
}

// ─── Projects ────────────────────────────────────────────────
export type ProjectStatus = "planning" | "in-progress" | "completed" | "cancelled";
export type Appetite = "small" | "medium" | "large";
export type TaskStatus = "backlog" | "ready" | "in_progress" | "review" | "done" | "blocked";
export type Complexity = "low" | "medium" | "high";

export interface Task {
  id: string;
  milestone_id: string;
  title: string;
  description: string | null;
  status: TaskStatus;
  estimate_hours: number | null;
  actual_hours: number | null;
  wsjf_score: number | null;
  complexity: Complexity | null;
  context_tags: string[];
  blocked_reason: string | null;
  dependency_task_ids: string[];
  sort_order: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface Milestone {
  id: string;
  epic_id: string;
  title: string;
  success_criteria: string | null;
  sort_order: number;
  tasks: Task[];
  created_at: string;
}

export interface Epic {
  id: string;
  project_id: string;
  title: string;
  description: string | null;
  sort_order: number;
  milestones: Milestone[];
  created_at: string;
}

export interface Project {
  id: string;
  title: string;
  description: string | null;
  status: ProjectStatus;
  appetite: Appetite | null;
  deadline: string | null;
  epics: Epic[];
  created_at: string;
  updated_at: string;
}

export interface ProjectDraft {
  id: string;
  user_id: string;
  title: string;
  source_message: string | null;
  status: string;
  project_summary: string | null;
  total_estimated_hours: number | null;
  milestone_count: number;
  critical_path: string[];
  risks: string[];
  applied_project_id: string | null;
  breakdown: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// ─── Contacts / CRM ─────────────────────────────────────────
export type InteractionType = "call" | "email" | "coffee" | "message";
export type InteractionDirection = "incoming" | "outgoing";

export interface Interaction {
  id: string;
  contact_id: string;
  interaction_type: InteractionType;
  direction: InteractionDirection;
  channel: "manual" | "gmail" | "calendar";
  summary: string;
  topics: string[];
  interaction_at: string;
  created_at: string;
}

export interface Contact {
  id: string;
  first_name: string;
  last_name: string | null;
  email: string | null;
  tags: string[];
  how_we_met: string | null;
  interaction_frequency_days: number | null;
  relationship_score: number;
  relationship_health: number | null;
  last_interaction_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContactSearchResult {
  id: string;
  first_name: string;
  last_name: string | null;
  email: string | null;
  tags: string[];
  relationship_score: number;
}

// ─── Calendar ────────────────────────────────────────────────
export interface CalendarEvent {
  id: string;
  summary: string;
  start: string;
  end: string;
  location: string | null;
  description: string | null;
  attendees: string[];
}

export interface FreeSlot {
  start: string;
  end: string;
  duration_minutes: number;
}

// ─── Email ───────────────────────────────────────────────────
export type TriageCategory = "ACTION_REQUIRED" | "URGENT" | "FYI" | "DELEGATE" | "ARCHIVE";

export interface Email {
  id: string;
  threadId: string | null;
  snippet: string;
  headers: Record<string, string>;
  body: string | null;
  labelIds: string[];
  internalDate: string | null;
  triage?: TriageCategory;
}

// ─── Commitments ─────────────────────────────────────────────
export type CommitmentStatus = "detected" | "acknowledged" | "completed" | "cancelled";

export interface Commitment {
  id: string;
  verbatim_text: string;
  normalized_action: string;
  who_committed: string | null;
  who_to: string | null;
  temporal_expression_raw: string | null;
  temporal_normalized: string | null;
  commitment_type: "promise" | "reminder";
  confidence_score: number;
  status: CommitmentStatus;
  created_at: string;
  updated_at: string;
}

// ─── Notifications ───────────────────────────────────────────
export type Priority = "P0" | "P1" | "P2" | "P3";
export type NotificationCategory =
  "deadline" | "commitment" | "relationship" | "system" | "digest" | "proactive" | "tutorial";

export interface Notification {
  id: string;
  message: string;
  priority: Priority;
  category: NotificationCategory;
  created_at: string;
  dismissed: boolean;
}

export interface WebPushConfig {
  enabled: boolean;
  public_key: string | null;
  active_subscription_count: number;
}

export interface WebPushSubscription {
  id: string;
  status: "active" | "error" | "revoked";
  endpoint_preview: string;
  endpoint_host: string | null;
  expiration_time: string | null;
  user_agent: string | null;
  failure_count: number;
  last_seen_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

// ─── Reviews ─────────────────────────────────────────────────
export interface WeeklyReview {
  id: string;
  period: string;
  accomplishments: string[];
  mood_summary: string | null;
  average_mood: number | null;
  goal_progress: Array<{
    title: string;
    progress: number;
    status: string;
  }>;
  open_commitments: Array<{ action: string; status: string }>;
  relationship_alerts: string[];
  patterns_noticed: string[];
  recommendations: string[];
  key_insight: string | null;
  created_at: string;
}

// ─── Notes ───────────────────────────────────────────────────
export type NoteType = "fleeting" | "literature" | "permanent" | "reference";
export type NoteKind = "note" | "daily" | "moc";

export interface Note {
  id: string;
  title: string;
  slug: string | null;
  aliases: string[];
  kind: NoteKind | null;
  daily_date: string | null;
  frontmatter: Record<string, unknown>;
  content: string;
  note_type: NoteType | null;
  para_category: ParaCategory | null;
  progressive_summary_level: number | null;
  executive_summary: string | null;
  source_url: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface NoteGraphNode {
  id: string;
  title: string;
  slug: string | null;
  kind: NoteKind | null;
  note_type: NoteType | null;
  para_category: ParaCategory | null;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface NoteGraphEdge {
  id: string;
  source: string;
  target: string;
  link_type: string;
  origin: string;
  similarity_score: number | null;
  link_reason: string | null;
}

export interface NoteGraph {
  nodes: NoteGraphNode[];
  edges: NoteGraphEdge[];
}

export interface NoteCanvas {
  id: string;
  title: string;
  description: string | null;
  primary_note_id: string | null;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  viewport: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ContentAsset {
  id: string;
  note_id: string | null;
  project_id: string | null;
  task_id: string | null;
  title: string;
  asset_type: string;
  status: string;
  source_pack: Record<string, unknown>;
  template_prompt: string | null;
  run_notes: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SavedMemory {
  id: string;
  user_id: string;
  title: string;
  content: string;
  scope: "global" | "person" | "project";
  scope_key: string | null;
  state: "active" | "snoozed" | "archived";
  source_type: string | null;
  source_id: string | null;
  provenance: Record<string, unknown>;
  pinned: boolean;
  auto_captured: boolean;
  last_used_at: string | null;
  last_confirmed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConnectorAccount {
  id: string;
  user_id: string;
  connector_type: string;
  display_name: string;
  status: string;
  scopes: string[];
  has_refresh_token: boolean;
  token_last_rotated_at: string | null;
  auto_use: boolean;
  background_access: boolean;
  sync_enabled: boolean;
  last_sync_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ConnectorSyncJob {
  id: string;
  account_id: string;
  sync_type: string;
  status: string;
  document_count: number;
  error_message: string | null;
  metadata: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ConnectorDocument {
  id: string;
  account_id: string;
  external_id: string;
  source_type: string;
  title: string;
  content: string;
  source_url: string | null;
  metadata: Record<string, unknown>;
  synced_at: string;
  created_at: string;
  updated_at: string;
}

export interface ScheduledAction {
  id: string;
  user_id: string;
  title: string;
  prompt: string;
  schedule_type: "once" | "daily" | "weekly" | "monthly";
  schedule_config: Record<string, unknown>;
  timezone: string;
  status: "active" | "paused" | "archived";
  delivery_channel: "web" | "telegram" | "email" | "voice";
  next_run_at: string | null;
  last_run_at: string | null;
  last_result_summary: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ScheduledActionRun {
  id: string;
  action_id: string;
  workflow_id: string | null;
  status: "queued" | "running" | "completed" | "failed";
  result_summary: string | null;
  error_message: string | null;
  payload: Record<string, unknown>;
  triggered_at: string;
  completed_at: string | null;
  created_at: string;
}

export interface NoteLink {
  id: string;
  source_note_id: string;
  target_note_id: string;
  link_reason: string | null;
  similarity_score: number | null;
  auto_discovered: boolean;
}

// ─── Entities (Knowledge Graph) ──────────────────────────────
export type EntityType = "PERSON" | "ORG" | "PLACE" | "CONCEPT";

export interface Entity {
  id: string;
  name: string;
  entity_type: EntityType;
  canonical_name: string | null;
  mention_count: number;
  first_seen: string | null;
  last_seen: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface EntityRelationship {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: string;
  valid_from: string | null;
  valid_to: string | null;
}

// ─── Agent Actions (Monitoring) ──────────────────────────────
export interface AgentAction {
  id: string;
  agent_name: AgentName;
  action_type: string | null;
  model_used: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  duration_ms: number | null;
  input_summary: string | null;
  output_summary: string | null;
  trace_id: string | null;
  created_at: string;
}

// ─── Health ──────────────────────────────────────────────────
export type HealthServiceState = "ok" | "degraded" | "lagging" | "down" | "unknown";

export interface HealthStatus {
  status: "ok" | "degraded" | "down";
  services: Record<
    string,
    {
      status: HealthServiceState;
      message?: string;
      latency_ms?: number;
      pending_update_count?: number;
      last_error_message?: string | null;
    }
  >;
}

// ─── Habits ─────────────────────────────────────────────────
export type HabitFrequency = "daily" | "weekly" | "monthly" | "custom";

export interface Habit {
  id: string;
  name: string;
  description: string | null;
  frequency: HabitFrequency;
  frequency_days: number;
  current_streak: number;
  longest_streak: number;
  total_completions: number;
  last_completed_at: string | null;
  active: boolean;
  tags: string[];
  created_at: string;
}

export interface HabitLog {
  id: string;
  habit_id: string;
  completed_at: string;
  note: string | null;
  source: string;
}

// ─── Decisions ──────────────────────────────────────────────
export type DecisionStatus = "pending_review" | "reviewed" | "archived";

export interface Decision {
  id: string;
  title: string;
  context: string | null;
  options_considered: string[];
  decision_made: string;
  reasoning: string | null;
  expected_outcome: string | null;
  actual_outcome: string | null;
  outcome_rating: number | null;
  tags: string[];
  review_date: string | null;
  status: DecisionStatus;
  created_at: string;
  updated_at: string;
}

// ─── Tutorials ──────────────────────────────────────────────
export type BloomLevel = "remember" | "understand" | "apply" | "analyze" | "evaluate" | "create";
export type TutorialPhase = "submitted" | "dialogue" | "complete";

export interface Tutorial {
  id: string;
  topic: string;
  work_type: string;
  phase: TutorialPhase;
  turn_count: number | null;
  bloom_start: BloomLevel | null;
  bloom_end: BloomLevel | null;
  speaking_ratio_student_pct: number | null;
  knowledge_gaps_found: number | null;
  knowledge_gaps_addressed: number | null;
  created_at: string;
  completed_at: string | null;
}

export interface TutorialDetail extends Tutorial {
  submitted_work: string;
  propositions: unknown[] | null;
  transcript: unknown[] | null;
  analysis: Record<string, unknown> | null;
}

// ─── Related Entity (from /entities/:id/related) ────────────
export interface RelatedEntity {
  id: string;
  name: string;
  entity_type: EntityType;
  relationship_type: string;
  depth: number;
}

// ─── Pagination ──────────────────────────────────────────────
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

/** Email endpoints use a different pagination shape (limit/offset) */
export interface OffsetPaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
