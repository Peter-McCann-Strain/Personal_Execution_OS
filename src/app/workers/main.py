"""ARQ worker settings and entry point."""

from collections.abc import Iterator, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import structlog
from aiogram import Bot
from anthropic import AsyncAnthropic
from arq import cron

from src.app.config import get_settings
from src.app.core.exceptions import ConfigError
from src.app.core.llm import create_llm_provider
from src.app.core.redis import close_redis_clients
from src.app.persistence.database import init_engine, init_session_factory
from src.app.workers.agent_tasks import init_fatigue_manager, process_agent_task
from src.app.workers.auto_judge import run_auto_judge
from src.app.workers.consolidation import run_consolidation
from src.app.workers.cost_alerts import run_cost_alerts
from src.app.workers.dataset_curation import run_weekly_dataset_curation
from src.app.workers.dlq_alerts import run_dlq_alerts
from src.app.workers.eval_export import run_eval_export
from src.app.workers.eval_pipeline import run_daily_eval_pipeline
from src.app.workers.github_filer import run_github_issue_sync
from src.app.workers.heartbeat import run_heartbeat
from src.app.workers.idempotency_cleanup import run_idempotency_cleanup
from src.app.workers.patterns import detect_patterns
from src.app.workers.quality_alerts import run_quality_alerts
from src.app.workers.quality_gates_alerts import run_quality_gates_alerts
from src.app.workers.scheduled import (
    annual_review,
    monthly_review,
    morning_briefing,
    quarterly_review,
    weekly_review,
)
from src.app.workers.scheduled_actions_runtime import run_due_scheduled_actions
from src.app.workers.schema_drift_alerts import run_schema_drift_alerts
from src.app.workers.session_maintenance import run_session_maintenance
from src.app.workers.slo_alerts import run_slo_alerts
from src.app.workers.spotcheck import run_weekly_spotcheck_nudge

logger = structlog.get_logger()


def _local_time_to_utc(
    local_hour: int,
    local_minute: int,
    tz_name: str,
    *,
    offset_minutes: int = 0,
    on_date: date | None = None,
) -> tuple[int, int]:
    """Convert a user-local time to a UTC hour/minute pair for cron scheduling."""
    tz = ZoneInfo(tz_name)
    local_dt = datetime.combine(
        on_date or datetime.now(tz).date(),
        time(local_hour, local_minute),
        tzinfo=tz,
    ) - timedelta(minutes=offset_minutes)
    utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
    return utc_dt.hour, utc_dt.minute


def _local_hour_to_utc(
    local_hour: int,
    local_minute: int,
    tz_name: str,
    *,
    on_date: date | None = None,
) -> int:
    """Convert a user-local hour to UTC hour for cron scheduling."""
    return _local_time_to_utc(local_hour, local_minute, tz_name, on_date=on_date)[0]


async def startup(ctx: dict) -> None:
    """Worker startup — initialise resources."""
    settings = get_settings()
    ctx["settings"] = settings

    # --- Telegram bot for sending scheduled messages ---
    if settings.telegram_configured:
        try:
            bot = Bot(token=settings.telegram_bot_token.get_secret_value())
            ctx["bot"] = bot
            logger.info("worker_telegram_initialized")
        except Exception as exc:
            logger.exception("worker_telegram_init_failed")
            raise ConfigError(f"Worker Telegram initialization failed: {exc}") from exc
    else:
        logger.warning(
            "worker_telegram_not_configured",
            hint="Set TELEGRAM_BOT_TOKEN in .env — scheduled messages will be skipped",
        )
        ctx["bot"] = None

    # --- FatigueManager with Redis persistence ---
    init_fatigue_manager(settings.redis_url.get_secret_value())

    # --- Database engine + session factory ---
    engine = init_engine(settings.database_url.get_secret_value())
    session_factory = init_session_factory(engine)
    ctx["session_factory"] = session_factory

    # --- Optional model provider for background execution ---
    llm_provider = create_llm_provider(
        settings,
        anthropic_client_factory=AsyncAnthropic,
    )
    ctx["llm_provider"] = llm_provider
    # Compatibility key for jobs that have not yet renamed their argument.
    ctx["anthropic_client"] = llm_provider

    logger.info(
        "worker_started",
        llm_provider=llm_provider.name,
        llm_configured=llm_provider.configured,
    )


async def shutdown(ctx: dict) -> None:
    """Worker shutdown — cleanup."""
    from src.app.persistence.database import close_engine

    # Close bot session if it was initialised
    bot: Bot | None = ctx.get("bot")
    if bot is not None:
        try:
            await bot.session.close()
        except Exception:
            logger.warning("worker_bot_session_close_failed", exc_info=True)

    llm_provider = ctx.get("llm_provider")
    if llm_provider is not None:
        try:
            await llm_provider.close()
        except Exception:
            logger.warning("worker_llm_provider_close_failed", exc_info=True)

    await close_redis_clients()
    await close_engine()
    logger.info("worker_shutdown")


async def run_pattern_detection(ctx: dict) -> None:
    """Wrapper for pattern detection — runs daily before evening review."""
    await detect_patterns(ctx)


def _build_cron_schedule() -> list:
    """Build the cron job list at first access, not at import time.

    This avoids calling ``get_settings()`` at module level — which crashes
    with an obscure import error if ``.env`` is missing.
    """
    settings = get_settings()
    tz = settings.user_timezone

    utc_morning_hour, utc_morning_minute = _local_time_to_utc(8, 0, tz)
    utc_patterns_hour, utc_patterns_minute = _local_time_to_utc(20, 0, tz)
    utc_weekly_hour, utc_weekly_minute = _local_time_to_utc(19, 0, tz)
    utc_monthly_hour, utc_monthly_minute = _local_time_to_utc(10, 0, tz)
    utc_quality_alerts_hour, utc_quality_alerts_minute = _local_time_to_utc(9, 0, tz)
    utc_slo_alerts_hour, utc_slo_alerts_minute = _local_time_to_utc(9, 15, tz)
    utc_quality_gates_hour, utc_quality_gates_minute = _local_time_to_utc(9, 30, tz)
    utc_schema_drift_hour, utc_schema_drift_minute = _local_time_to_utc(9, 45, tz)
    utc_session_maintenance_hour, utc_session_maintenance_minute = _local_time_to_utc(2, 30, tz)
    utc_eval_export_hour, utc_eval_export_minute = _local_time_to_utc(3, 0, tz)
    utc_eval_pipeline_hour, utc_eval_pipeline_minute = _local_time_to_utc(3, 5, tz)
    utc_consolidation_hour, utc_consolidation_minute = _local_time_to_utc(3, 30, tz)
    utc_idempotency_cleanup_hour, utc_idempotency_cleanup_minute = _local_time_to_utc(3, 45, tz)
    utc_dataset_curation_hour, utc_dataset_curation_minute = _local_time_to_utc(4, 0, tz)
    utc_spotcheck_hour, utc_spotcheck_minute = _local_time_to_utc(14, 0, tz)
    utc_issue_sync_hour, utc_issue_sync_minute = _local_time_to_utc(6, 15, tz)

    core_jobs = [
        # Heartbeat every 30 minutes
        cron(run_heartbeat, minute={0, 30}),
        # Quality degradation alerts — daily at user-local 9:00
        cron(
            run_quality_alerts,
            hour={utc_quality_alerts_hour},
            minute={utc_quality_alerts_minute},
        ),
        # SLO burn-rate alerts — daily at user-local 9:15 (before quality alerts
        # so the first ops signal is objective breaches, not derivatives).
        cron(
            run_slo_alerts,
            hour={utc_slo_alerts_hour},
            minute={utc_slo_alerts_minute},
        ),
        # Quality-gate alerts — daily at user-local 9:30
        cron(
            run_quality_gates_alerts,
            hour={utc_quality_gates_hour},
            minute={utc_quality_gates_minute},
        ),
        # Schema-drift alerts — daily at user-local 9:45 (table.column not found)
        cron(
            run_schema_drift_alerts,
            hour={utc_schema_drift_hour},
            minute={utc_schema_drift_minute},
        ),
        # Cost-ceiling alerts — hourly at :25 (off-cycle from other alert jobs).
        # Catches silent spend escalation (e.g. Anthropic cache-TTL flips)
        # before it compounds. Dedup is handled in-worker via Redis.
        cron(run_cost_alerts, minute={25}),
        # Dead-letter queue alerts — hourly at :50. Fires a Telegram alert
        # when any dlq_jobs row has failed_at older than the configured
        # threshold and replayed_at is still NULL.
        cron(run_dlq_alerts, minute={50}),
        # Session maintenance — daily at user-local 2:30
        cron(
            run_session_maintenance,
            hour={utc_session_maintenance_hour},
            minute={utc_session_maintenance_minute},
        ),
        # Evaluation data export — daily at user-local 3:00
        cron(run_eval_export, hour={utc_eval_export_hour}, minute={utc_eval_export_minute}),
        # Daily eval pipeline — per-agent exports, failures, summary + Telegram
        # at user-local 3:05 (runs right after the raw export above).
        cron(
            run_daily_eval_pipeline,
            hour={utc_eval_pipeline_hour},
            minute={utc_eval_pipeline_minute},
        ),
        # Idempotency key cleanup — daily at user-local 3:45
        # Drops rows whose 24h TTL has elapsed so the active-key partial index
        # stays small and future cache hits remain O(log n).
        cron(
            run_idempotency_cleanup,
            hour={utc_idempotency_cleanup_hour},
            minute={utc_idempotency_cleanup_minute},
        ),
        # Weekly golden-dataset curation (Phase 4.5) — Monday user-local 04:00.
        # Clusters last 7 days of scored interactions per agent and writes
        # diverse-sample proposals to data/evaluation/datasets/proposals/.
        # Human approves via scripts/dataset_promote.py before vN+1 rolls.
        cron(
            run_weekly_dataset_curation,
            weekday={0},
            hour={utc_dataset_curation_hour},
            minute={utc_dataset_curation_minute},
        ),
        # GitHub issue sync (Phase 3.9) — daily user-local 06:15.
        # Auto-closes issues with no recurrence in
        # ``github_issue_dedup_window_days`` (default 7) and wipes
        # dedup rows whose GitHub issue was already human-closed so a
        # future recurrence opens a fresh issue. No-op if the filer
        # settings are unconfigured.
        cron(
            run_github_issue_sync,
            hour={utc_issue_sync_hour},
            minute={utc_issue_sync_minute},
        ),
        # Weekly spot-check nudge (Phase 4.9) — Friday user-local 14:00.
        # Samples 5 recent interactions, writes a markdown queue file, and
        # sends a Telegram nudge pointing the operator at it. Completed via the
        # `scripts/spotcheck.py score` CLI.
        cron(
            run_weekly_spotcheck_nudge,
            weekday={4},
            hour={utc_spotcheck_hour},
            minute={utc_spotcheck_minute},
        ),
    ]

    if not settings.llm_configured or not settings.proactive_automation_enabled:
        reason = (
            "model provider is not configured"
            if not settings.llm_configured
            else "proactive automation is not enabled"
        )
        logger.info(
            "worker_model_cron_jobs_disabled",
            reason=reason,
        )
        return core_jobs

    model_jobs = [
        cron(run_due_scheduled_actions, minute=set(range(60))),
        cron(morning_briefing, hour={utc_morning_hour}, minute={utc_morning_minute}),
        cron(run_pattern_detection, hour={utc_patterns_hour}, minute={utc_patterns_minute}),
        cron(weekly_review, weekday={6}, hour={utc_weekly_hour}, minute={utc_weekly_minute}),
        cron(monthly_review, day={1}, hour={utc_monthly_hour}, minute={utc_monthly_minute}),
        cron(
            quarterly_review,
            month={1, 4, 7, 10},
            day={1},
            hour={utc_monthly_hour},
            minute={utc_monthly_minute},
        ),
        cron(
            annual_review,
            month={1},
            day={1},
            hour={utc_monthly_hour},
            minute={utc_monthly_minute},
        ),
        cron(
            run_auto_judge,
            hour={h % 24 for h in range(0, 24, settings.auto_judge_cron_interval_hours)},
            minute={15},
        ),
        cron(
            run_consolidation,
            hour={utc_consolidation_hour},
            minute={utc_consolidation_minute},
        ),
    ]
    return [*core_jobs, *model_jobs]


class WorkerSettings:
    """ARQ worker configuration."""

    functions: ClassVar[list] = [process_agent_task]
    cron_jobs: ClassVar[Sequence[Any]]
    redis_settings: ClassVar[Any]
    on_startup = startup
    on_shutdown = shutdown

    max_jobs = 5
    max_tries = 3  # ARQ-level max tries per job
    job_timeout = 300  # 5 minutes max per job


class _LazyCronJobs(Sequence):
    """Build cron jobs on first access, not on module import."""

    def _build(self) -> list:
        return _build_cron_schedule()

    def __len__(self) -> int:
        return len(self._build())

    def __iter__(self) -> Iterator:
        return iter(self._build())

    def __getitem__(self, index):
        return self._build()[index]


class _RedisSettingsProxy:
    """Resolve Redis settings lazily from the current environment."""

    def __call__(self):
        from arq.connections import RedisSettings

        settings = get_settings()
        return RedisSettings.from_dsn(settings.redis_url.get_secret_value())

    def __getattr__(self, name: str):
        return getattr(self(), name)


WorkerSettings.cron_jobs = _LazyCronJobs()
WorkerSettings.redis_settings = _RedisSettingsProxy()
