"""Application configuration — all values from environment, nothing hardcoded."""

import ipaddress
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.app.version import APP_VERSION


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core
    app_env: Literal["development", "production", "test"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # LLM provider. The application remains usable for capture and retrieval
    # when no provider is configured; model-backed features return a clear 503.
    llm_provider: Literal["anthropic", "disabled"] = "disabled"
    anthropic_api_key: SecretStr = SecretStr("")

    # Local PostgreSQL is the core data store.
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://assistant:assistant@localhost:5432/personal_execution_os"
    )
    db_pgbouncer_mode: bool = False

    # Redis
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    # Optional local-owner API key for CLI/automation. Browser auth uses the
    # first-run password and server-side session cookie.
    chat_api_key: SecretStr = SecretStr("")
    auth_session_cookie_name: str = "peos_session"
    auth_csrf_cookie_name: str = "peos_csrf"
    auth_session_ttl_hours: int = 168
    auth_cookie_secure: bool = False
    auth_trusted_origins: str = ""
    public_hostname: str = ""
    app_port: int = 8080
    auth_login_attempts: int = 5
    auth_login_window_seconds: float = 60.0

    # Telegram is optional.
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_allowed_user_ids: str = ""  # Comma-separated, parsed in property
    telegram_webhook_url: str = ""
    telegram_webhook_secret: SecretStr = SecretStr("")

    # User timezone (for cron scheduling)
    user_timezone: str = "UTC"

    # CORS — empty string disables CORS (single-user API behind the same-origin web proxy)
    cors_allowed_origins: str = ""
    private_single_user_mode: bool = True
    first_account_id: str = "00000000-0000-0000-0000-000000000001"
    first_owner_user_id: str = "00000000-0000-0000-0000-000000000010"

    # Ollama
    ollama_host: str = ""
    ollama_embed_model: str = "nomic-embed-text:v2-moe"

    # Google Workspace (Calendar + Gmail) — optional, features degrade gracefully
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_refresh_token: SecretStr = SecretStr("")
    google_oauth_redirect_url: str = ""
    connector_token_encryption_key: SecretStr = SecretStr("")

    # Tavily (Web Search) — optional, research agent won't work without it
    tavily_api_key: SecretStr = SecretStr("")
    github_token: SecretStr = SecretStr("")

    # Observability — optional
    sentry_dsn: SecretStr = SecretStr("")
    sentry_traces_sample_rate: float = 0.1
    sentry_profiles_sample_rate: float = 0.0
    sentry_send_default_pii: bool = False
    posthog_api_key: SecretStr = SecretStr("")
    posthog_host: str = "https://eu.i.posthog.com"

    # OpenTelemetry stays off unless it is enabled and an OTLP endpoint is
    # configured. Collector configuration belongs to the operator.
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    otel_service_name: str = "personal-execution-os"
    otel_service_version: str = APP_VERSION
    # Head-sample ratio applied in this process. A downstream Collector may
    # apply its own policy, which is outside this repository's configuration.
    otel_sampler_ratio: float = 0.1
    # Sampler identifier. Valid values: ``parentbased_always_on`` (default),
    # ``parentbased_traceidratio`` (uses otel_sampler_ratio), ``always_on``,
    # ``always_off``. Anything else falls through to parentbased_always_on.
    otel_traces_sampler: str = "parentbased_always_on"
    # April 2026: GenAI semconv is still ``Development`` status. Must opt in
    # explicitly via env var (OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental)
    # for the attribute names to be treated as stable. ``setup_otel`` sets
    # this on the process env if unset, so the contract is maintained
    # regardless of how uvicorn is launched.
    otel_semconv_opt_in: str = "gen_ai_latest_experimental"
    # Prompt and completion bodies are sensitive user data. Export only when
    # an operator makes a separate, explicit opt-in; redaction is defense in
    # depth and is not treated as permission to export content.
    otel_export_content: bool = False
    # Optional installation-local secret used to pseudonymize analytics IDs.
    # Empty means PostHog receives an anonymous, non-user-specific identity.
    telemetry_installation_salt: SecretStr = SecretStr("")

    # Healthchecks.io — optional
    healthchecks_heartbeat_url: str = ""
    healthchecks_backup_url: str = ""

    # LLM Models — configurable per-agent
    routing_model: str = "claude-haiku-4-5-20251001"
    diary_model: str = "claude-sonnet-4-6"
    memory_model: str = "claude-sonnet-4-6"
    research_query_model: str = "claude-sonnet-4-6"
    research_synthesis_model: str = "claude-opus-4-6"
    review_model: str = "claude-opus-4-6"
    project_model: str = "claude-sonnet-4-6"
    communications_model: str = "claude-sonnet-4-6"
    tools_model: str = "claude-sonnet-4-6"
    classifier_model: str = "claude-haiku-4-5-20251001"
    commitment_model: str = "claude-haiku-4-5-20251001"
    # Sonnet for entity extraction: knowledge graph quality compounds daily —
    # every missed entity is a permanent gap in memory retrieval.
    entity_model: str = "claude-sonnet-4-6"
    # Sonnet for summaries: poor compression degrades context quality over long sessions.
    summary_model: str = "claude-sonnet-4-6"

    # Socratic tutorial system — per-agent models (genuine reasoning diversity)
    socratic_tutor_model: str = "claude-sonnet-4-6"
    socratic_devils_advocate_model: str = "claude-opus-4-6"
    socratic_clarifier_model: str = "claude-haiku-4-5-20251001"
    socratic_connector_model: str = "claude-sonnet-4-6"
    socratic_assessor_model: str = "claude-haiku-4-5-20251001"
    socratic_preparation_model: str = "claude-sonnet-4-6"
    socratic_analysis_model: str = "claude-sonnet-4-6"

    # Context engineering
    relevance_threshold: float = 0.25
    working_memory_size: int = 4
    summarization_trigger_ratio: float = 0.6
    session_ttl: int = 604_800  # 7 days
    max_context_messages: int = 50
    context_available_ratio: float = 0.45
    conversation_budget_ratio: float = 0.35
    rag_budget_ratio: float = 0.65
    default_search_limit: int = 10
    rrf_k: int = 60
    memory_decay_rate: float = 0.01
    chars_per_token: float = 3.5

    # Context budget allocation (must sum to 1.0)
    budget_system_pct: float = 0.05
    budget_rag_pct: float = 0.25
    budget_history_pct: float = 0.15
    budget_user_pct: float = 0.05
    budget_output_pct: float = 0.30
    budget_safety_pct: float = 0.20

    # Max tokens — high defaults to prevent truncation
    routing_max_tokens: int = 512
    diary_max_tokens: int = 4096
    memory_max_tokens: int = 4096
    memory_summary_max_tokens: int = 2048
    research_query_max_tokens: int = 1024
    research_synthesis_max_tokens: int = 8192
    review_max_tokens: int = 8192
    project_max_tokens: int = 8192
    communications_triage_max_tokens: int = 1024
    communications_draft_max_tokens: int = 4096
    tools_plan_max_tokens: int = 1024
    tools_summary_max_tokens: int = 2048
    classifier_max_tokens: int = 512
    commitment_max_tokens: int = 1024
    entity_max_tokens: int = 2048
    summary_max_tokens: int = 2048

    # Socratic tutorial max tokens
    socratic_tutor_max_tokens: int = 2048
    socratic_devils_advocate_max_tokens: int = 2048
    socratic_clarifier_max_tokens: int = 1024
    socratic_connector_max_tokens: int = 1024
    socratic_assessor_max_tokens: int = 1024
    socratic_preparation_max_tokens: int = 4096
    socratic_analysis_max_tokens: int = 8192

    # Socratic tutorial context engineering
    socratic_working_memory_turns: int = 6  # Last N turns verbatim in working memory
    socratic_max_propositions: int = 20  # Max atomic claims to extract
    socratic_session_ttl: int = 86_400  # 24 hours

    # --- Notification ---
    notification_dnd_start_hour: int = 22
    notification_dnd_end_hour: int = 7
    web_push_public_key: str = ""
    web_push_private_key: SecretStr = SecretStr("")
    web_push_subject: str = "mailto:owner@example.com"
    web_push_content_preview_enabled: bool = False

    # --- Rate Limiting ---
    rate_limit_api_rpm: int = 60
    rate_limit_api_window: float = 60.0
    rate_limit_telegram_rpm: int = 30
    rate_limit_telegram_window: float = 60.0

    # --- Database Pool ---
    db_pool_size: int = 5
    db_pool_max_overflow: int = 10
    db_pool_recycle: int = 300

    # --- Specialist Max Tokens (non-chat) ---
    pattern_detection_max_tokens: int = 2048
    nudge_max_tokens: int = 200
    evaluator_max_tokens: int = 256

    # --- Consolidation ---
    consolidation_enabled: bool = True
    consolidation_lookback_hours: int = 24
    consolidation_min_cluster_size: int = 2

    # Model-backed scheduled work is opt-in. Configuring an API key alone must
    # never start briefings, reviews, pattern detection, or other paid jobs.
    proactive_automation_enabled: bool = False

    # --- Session maintenance / runtime hygiene ---
    session_maintenance_enabled: bool = False
    session_maintenance_transcript_retention_days: int = 90
    session_maintenance_artifact_compaction_days: int = 30
    session_maintenance_checkpoint_retention_days: int = 30
    session_maintenance_payload_char_threshold: int = 8_000
    session_maintenance_transcript_preview_chars: int = 240

    # --- World-class rollout flags for new assistant-native surfaces ---
    continuity_runtime_enabled: bool = True
    project_draft_runtime_enabled: bool = True
    notes_workspace_enabled: bool = True
    content_factory_enabled: bool = True

    # --- Workflow shadow mode ---
    workflow_shadow_mode_enabled: bool = False
    workflow_shadow_mode_timeout_ms: int = 1_500
    workflow_shadow_mode_sample_rate: float = 1.0
    workflow_shadow_mode_specialists: str = "diary,memory,review,project,communications"
    workflow_live_runtime_enabled: bool = False
    workflow_live_runtime_timeout_ms: int = 3_000
    workflow_live_runtime_specialists: str = (
        "diary,memory,review,project,communications,notification,plan_day,"
        "research,tools,save,socratic"
    )

    # --- Evaluation / auto-judge ---
    auto_judge_enabled: bool = False
    # Sonnet for auto-judge: quality loop accuracy depends on accurate scoring —
    # a weak judge gives wrong signals and masks real failures.
    auto_judge_model: str = "claude-sonnet-4-6"
    auto_judge_max_tokens: int = 512
    auto_judge_batch_size: int = 50  # Max records per cron run
    auto_judge_cron_interval_hours: int = 4
    quality_alerts_enabled: bool = False
    quality_alert_threshold: float = 0.5  # Score drop threshold for alerts
    quality_alert_window_hours: int = 24  # Compare last N hours vs trailing 7 days
    quality_alert_baseline_days: int = 7

    # --- Monthly calibration (P4.4) ---
    # The pinned auto-judge snapshot. When the observed model snapshot diverges
    # from this value (Anthropic shipped a new snapshot), we fire a Telegram
    # alert asking the operator to run ``scripts/calibrate.py`` within 7 days.
    # Empty string = unpinned (no alerting vs pin, only vs previously seen).
    auto_judge_model_version_pinned: str = ""
    calibration_default_sample_size: int = 30
    calibration_min_per_agent: int = 3

    # --- Weekly human spot-check (P4.9) ---
    # A lightweight 15-minute weekly nudge: the operator reads 5 recent interactions
    # and marks whether the auto-judge score feels right. Fires user-local
    # Friday 14:00.
    spotcheck_enabled: bool = False
    spotcheck_n_per_week: int = 5
    spotcheck_dir: str = "data/evaluation/spotcheck"

    # --- Dead-letter queue for ARQ background jobs (Phase 7.1) ---
    # DLQ writes are always attempted on terminal job failure. Alerts can be
    # silenced separately (e.g. during a noisy deploy window).
    dlq_alert_enabled: bool = False
    dlq_alert_age_threshold_hours: int = 24
    dlq_alert_threshold_count: int = 1

    eval_export_enabled: bool = False
    evaluation_export_dir: str = "data/evaluation/exports"
    # Daily eval pipeline — turns pre-scored interactions into per-agent
    # export/failure/report files and sends a Telegram summary. No LLM
    # calls (relies on auto_judge scores already in the DB).
    eval_pipeline_enabled: bool = False
    eval_pipeline_min_samples: int = 5  # skip agents with fewer scored 24h records
    feedback_enabled: bool = True  # Show thumbs up/down on Telegram responses
    startup_preflight_fail_fast: bool = False
    runtime_eval_mode: Literal["sync", "async"] = "async"
    runtime_eval_sample_rate: float = 1.0
    runtime_eval_optimizer_enabled: bool = False
    assistant_native_replay_eval_enabled: bool = False
    assistant_native_replay_pass_rate_target: float = 1.0
    assistant_native_replay_baseline_lift_target: float = 0.5

    # --- Golden-dataset curation (Phase 4.5) ---
    # Weekly cron mines the last 7 days of scored interactions per agent,
    # embeds user_message via the existing Ollama helper, clusters with
    # KMeans to find UNDER-REPRESENTED topic clusters, then proposes a
    # diverse sample of new golden cases (not failure-only — overfits).
    # Proposals land in data/evaluation/datasets/proposals/ and require
    # human approval via scripts/dataset_promote.py before joining vN+1.
    dataset_curation_enabled: bool = False
    dataset_proposals_per_week: int = 5
    dataset_cluster_min_size: int = 3
    dataset_proposals_dir: str = "data/evaluation/datasets/proposals"
    dataset_datasets_dir: str = "data/evaluation/datasets"
    dataset_curation_lookback_days: int = 7

    # --- Quality gates ---
    quality_gate_route_accuracy_target: float = 0.95
    quality_gate_channel_style_pass_rate_target: float = 0.95
    quality_gate_channel_style_score_threshold: float = 0.95
    quality_gate_final_response_quality_pass_rate_target: float = 0.90
    quality_gate_final_response_quality_score_threshold: float = 0.90
    quality_gate_renderer_pass_rate_target: float = 0.95
    quality_gate_trace_coverage_target: float = 1.0
    quality_gate_tool_execution_success_rate_target: float = 0.90
    quality_gate_confirmation_coverage_target: float = 1.0
    quality_gates_alerts_enabled: bool = False
    quality_gates_alert_window_days: int = 7
    quality_gates_alert_limit: int = 2000
    quality_gates_alert_min_interactions: int = 25
    quality_gates_security_max_mutating_without_confirmation: int = 0
    quality_gates_security_max_duplicate_idempotency: int = 0
    quality_gates_security_max_instruction_risk_decisions: int = 5
    quality_gates_security_max_trust_boundary_denies: int = 10

    # --- HITL (human-in-the-loop) approval for side-effecting tool calls ---
    # Phase 5.8 gate that pauses every mutating tool call for explicit user
    # approval via Telegram inline buttons. See src/app/core/hitl.py.
    hitl_enabled: bool = True
    # Comma-separated list of destinations (emails, attendee addresses) that
    # bypass the gate — e.g. the user's own mailbox. Parsed via property.
    hitl_auto_approve_destinations_raw: str = ""
    # Seconds the gate waits for a Telegram reply before defaulting to cancel.
    hitl_timeout_seconds: int = 300

    # --- Cost-ceiling alerts ---
    # Prevent a silent spend escalation (e.g. the March-2026 Anthropic cache-TTL
    # flip that 3x'd costs at another org overnight). Runs hourly, fires at most
    # one alert per hour per category per day via Redis dedup.
    cost_alerts_enabled: bool = False
    cost_daily_ceiling_gbp: float = 5.0  # absolute hard stop
    cost_rolling_multiplier: float = 1.5  # projected EOD > 1.5x of 30d p95

    # --- SLOs (P3.6) ---
    # Four SLOs + a combined goodput SLO tracked against agent_trace_spans
    # (latency/error) and interaction_records (quality). The goodput SLO
    # combines latency + quality into one user-facing objective. Cost is
    # cross-referenced with the cost_daily_ceiling_gbp setting above so
    # there's a single source of truth for spend breaches.
    slo_latency_p95_seconds: float = 5.0
    slo_latency_p99_seconds: float = 12.0
    slo_error_rate_max: float = 0.005
    slo_quality_p10_min: float = 4.0
    slo_goodput_target: float = 0.99
    slo_alert_burn_rate_threshold: float = 2.0
    slo_alerts_enabled: bool = False

    # --- PII redaction (P3.7) ---
    # Scrubs emails / UK phones / UK postcodes / credit-card shapes from
    # every structlog line before it leaves the process. ``pii_override_patterns``
    # takes comma-separated regex strings (e.g. home address tokens or a
    # specific name that should be redacted proactively). ``pii_allowlist_keys``
    # extends the built-in allowlist of keys whose values are never redacted
    # (user_id, trace_id, model, tokens_in/out, etc.).
    pii_redaction_enabled: bool = True
    pii_override_patterns: str = ""
    pii_allowlist_keys: str = ""

    # --- Schema-drift alerts ---
    # Surface ORM/database divergence (UndefinedColumnError / UndefinedTableError /
    # ProgrammingError "does not exist") as a distinct Telegram alert so we never
    # again miss a missing column firing 60x per runtime tick.
    schema_drift_alerts_enabled: bool = False
    schema_drift_alert_window_hours: int = 24
    schema_drift_alert_threshold: int = 10
    # Optional path to a JSON-lines structlog file. Empty means the worker is a
    # no-op. The default Compose logging driver does not create this file.
    schema_drift_alert_log_path: str = ""

    # --- Auto-issue from prod (P3.9) — GitHub issue fan-out for alerts ---
    # When any of the alert workers (DLQ, schema-drift, quality, SLO burn-rate,
    # cost-ceiling, quality-gates) fire a Telegram message, we also file a
    # GitHub issue so the next Claude Code session has a ready-made backlog
    # of production failures to triage. Dedup on a sha256 fingerprint of the
    # alert's identity fields prevents a recurring crash from spamming
    # hundreds of duplicate issues — recurrences are added as comments and
    # the issue's ``count:<N>`` label is bumped. See
    # ``src.app.workers.github_filer`` and
    # ``src.app.core.github_client`` for the full contract.
    #
    # If ``github_issue_repo`` is empty OR ``github_token`` is unset the
    # filer is a strict no-op — Telegram remains the fast path, GitHub is
    # an opt-in durable backlog that must never break the alert pipeline.
    github_issue_filer_enabled: bool = False
    github_issue_repo: str = ""  # e.g. "example/personal-execution-os"
    github_issue_dedup_window_days: int = 7

    # --- Prompt-content hash validation (P4.7) ---
    # Compares live ``PROMPT_CONTENT_HASH`` constants to tracked values at
    # startup. Empty = skip validation (dev mode); populated = fail fast
    # on any drift so you can't ship a prompt edit without bumping
    # ``PROMPT_VERSION`` and updating the tracked hash. Hash values are
    # 16-char sha256 prefixes — see ``src/app/agents/prompts/_hashing.py``.
    expected_prompt_hashes: dict[str, str] = {}

    # --- Eval-cost ceiling (P4.10) ---
    # A/B tests and jury ensembles can balloon cost. Tag every eval-purpose
    # LLM call with ``purpose="evaluation"`` in structlog so we can split
    # eval spend from product spend. The hourly cost-alerts worker compares
    # 24h eval spend to this ceiling independently of the overall daily
    # ceiling. Default £1.00 covers ~30 hours of Haiku auto-judge +
    # occasional jury runs.
    eval_daily_ceiling_gbp: float = 1.0

    # MCP is disabled in the first public release. No API credential or
    # wildcard destination may implicitly enable a subprocess/network server.
    mcp_tool_allowlist: dict[str, list[str]] = {}
    # When True, startup preflight includes the MCP registry verification step.
    mcp_registry_verification_enabled: bool = False

    # --- MCP OAuth 2.1 (P6.0) ---
    # Master secret used to derive the AES-GCM key that protects per-server
    # OAuth tokens on disk (``data/mcp_oauth/<server>.json``). Must be at
    # least 16 characters. Required once any remote (streamable-http) MCP
    # server is configured; stdio-only deployments can leave this empty.
    mcp_oauth_master_secret: SecretStr = SecretStr("")

    @property
    def startup_preflight_enabled(self) -> bool:
        """Backward-compatible alias for the always-on startup preflight."""
        return True

    @property
    def allowed_user_ids(self) -> list[int]:
        """Parse comma-separated user IDs into a list of ints."""
        return [
            int(uid.strip()) for uid in self.telegram_allowed_user_ids.split(",") if uid.strip()
        ]

    @property
    def google_configured(self) -> bool:
        """Check if Google OAuth is configured."""
        return bool(self.google_client_id and self.google_refresh_token.get_secret_value())

    @property
    def tavily_configured(self) -> bool:
        """Check if Tavily search is configured."""
        return bool(self.tavily_api_key.get_secret_value())

    @property
    def github_configured(self) -> bool:
        """Check if GitHub MCP server is configured."""
        return bool(self.github_token.get_secret_value())

    @property
    def telegram_configured(self) -> bool:
        """Check if Telegram bot credentials are configured."""
        token = self.telegram_bot_token.get_secret_value()
        return bool(token and ":" in token)

    @property
    def llm_configured(self) -> bool:
        """Return whether the selected model provider can serve requests."""
        if self.llm_provider == "disabled":
            return False
        return bool(self.anthropic_api_key.get_secret_value().strip())

    @property
    def sentry_configured(self) -> bool:
        """Check if Sentry DSN is configured."""
        return _looks_like_sentry_dsn(self.sentry_dsn.get_secret_value())

    @property
    def posthog_configured(self) -> bool:
        """Check if PostHog ingestion has both a key and explicit destination."""
        return bool(self.posthog_api_key.get_secret_value().strip() and self.posthog_host.strip())

    @property
    def otel_configured(self) -> bool:
        """Check if OpenTelemetry OTLP export is configured.

        When False, :func:`src.app.core.otel.setup_otel` installs a no-op
        TracerProvider so all tracer.start_as_current_span calls become
        essentially free — the span is allocated but never exported.
        """
        return self.otel_enabled and bool(self.otel_exporter_otlp_endpoint.strip())

    @property
    def web_push_configured(self) -> bool:
        """Check if VAPID-backed web push delivery is configured."""
        return bool(
            self.web_push_public_key.strip()
            and self.web_push_private_key.get_secret_value().strip()
            and self.web_push_subject.strip()
        )

    @property
    def workflow_shadow_specialist_names(self) -> list[str]:
        """Parse configured shadow specialists into normalized names."""
        return [
            value.strip().lower()
            for value in self.workflow_shadow_mode_specialists.split(",")
            if value.strip()
        ]

    @property
    def workflow_live_runtime_specialist_names(self) -> list[str]:
        """Parse configured live-runtime specialists into normalized names."""
        return [
            value.strip().lower()
            for value in self.workflow_live_runtime_specialists.split(",")
            if value.strip()
        ]

    @property
    def hitl_auto_approve_destinations(self) -> list[str]:
        """Trusted destinations that skip the HITL approval gate.

        Normalised to lowercase and stripped. See src/app/core/hitl.py.
        """
        return [
            value.strip().lower()
            for value in self.hitl_auto_approve_destinations_raw.split(",")
            if value.strip()
        ]

    @field_validator(
        "anthropic_api_key",
        "chat_api_key",
        "database_url",
        "telegram_bot_token",
        "telegram_webhook_secret",
        "redis_url",
        "telegram_webhook_url",
        "web_push_private_key",
        "web_push_public_key",
        mode="after",
    )
    @classmethod
    def reject_placeholders(cls, v: str | SecretStr) -> str | SecretStr:
        raw = v.get_secret_value() if isinstance(v, SecretStr) else v
        if raw.startswith("PLACEHOLDER"):
            msg = (
                f"Config value is still a placeholder: '{raw}'. "
                "Set the real value in your .env file."
            )
            raise ValueError(msg)
        return v

    @field_validator("public_hostname", mode="after")
    @classmethod
    def validate_public_hostname(cls, value: str) -> str:
        """Accept one exact hostname/IP, never a URL, wildcard, port, or list."""
        hostname = value.strip()
        if not hostname:
            return ""
        if value != hostname:
            raise ValueError("PUBLIC_HOSTNAME must not contain surrounding whitespace")
        unbracketed = hostname.removeprefix("[").removesuffix("]")
        try:
            address = ipaddress.ip_address(unbracketed)
        except ValueError:
            address = None
        if address is not None:
            if address.version != 4:
                raise ValueError("PUBLIC_HOSTNAME accepts DNS hostnames or IPv4 only")
            return unbracketed
        if (
            hostname != unbracketed
            or hostname.endswith(".")
            or len(hostname) > 253
            or any(char in hostname for char in ":/,\\* \t\r\n")
        ):
            raise ValueError(
                "PUBLIC_HOSTNAME must be one exact DNS hostname or IPv4 address without "
                "scheme, port, path, wildcard, or list"
            )
        labels = hostname.rstrip(".").split(".")
        if not all(
            1 <= len(label) <= 63
            and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
            for label in labels
        ):
            raise ValueError("PUBLIC_HOSTNAME is not a valid exact hostname")
        return hostname.rstrip(".").casefold()

    @model_validator(mode="after")
    def validate_budget_pct_sum(self) -> "Settings":
        total = (
            self.budget_system_pct
            + self.budget_rag_pct
            + self.budget_history_pct
            + self.budget_user_pct
            + self.budget_output_pct
            + self.budget_safety_pct
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Context budget percentages must sum to 1.0 (±0.01), got {total:.4f}. "
                "Check budget_system_pct, budget_rag_pct, budget_history_pct, "
                "budget_user_pct, budget_output_pct, and budget_safety_pct."
            )
        return self


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get cached settings instance. Crashes on missing/placeholder config."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _looks_like_sentry_dsn(value: str) -> bool:
    """Return True when the value resembles a valid Sentry DSN."""
    dsn = value.strip()
    if not dsn:
        return False
    try:
        parsed = urlparse(dsn)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    if not parsed.path:
        return False

    project_id = parsed.path.rsplit("/", 1)[-1]
    return project_id.isdigit()
