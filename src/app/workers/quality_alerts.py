"""Quality degradation alerts — detects score drops and notifies via Telegram.

Runs daily. Compares each agent's average scores over the last 24 hours
against their trailing 7-day baseline. If any dimension drops by more
than the configured threshold, sends a Telegram alert.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from aiogram import Bot

from src.app.config import Settings
from src.app.persistence.repositories.interactions import (
    get_specialist_score_averages,
)
from src.app.workers.github_filer import AlertRecord, file_github_issue

logger = structlog.get_logger()

_SCORE_DIMENSIONS = ("avg_relevance", "avg_actionability", "avg_tone", "avg_conciseness")
_DIMENSION_LABELS = {
    "avg_relevance": "Relevance",
    "avg_actionability": "Actionability",
    "avg_tone": "Tone",
    "avg_conciseness": "Conciseness",
}


async def run_quality_alerts(ctx: dict) -> None:
    """Compare recent scores to baseline and alert on degradation.

    Called by ARQ cron (daily). Uses the bot from worker context to send
    Telegram messages to the first allowed user.
    """
    settings: Settings = ctx["settings"]
    bot: Bot | None = ctx.get("bot")
    session_factory = ctx["session_factory"]

    if not bool(getattr(settings, "quality_alerts_enabled", False)):
        logger.info("quality_alerts_disabled")
        return
    if bot is None:
        logger.warning("quality_alerts_no_bot", hint="Telegram not configured")
        return

    now = datetime.now(UTC)
    recent_start = now - timedelta(hours=settings.quality_alert_window_hours)
    baseline_start = now - timedelta(days=settings.quality_alert_baseline_days)
    baseline_end = recent_start  # baseline is everything before the recent window

    async with session_factory() as session:
        recent_by_agent = await get_specialist_score_averages(
            session,
            start=recent_start,
            end=now,
        )
        baseline_by_agent = await get_specialist_score_averages(
            session,
            start=baseline_start,
            end=baseline_end,
        )

    # Index baseline by specialist for quick lookup
    baseline_map: dict[str, dict] = {row["specialist"]: row for row in baseline_by_agent}

    alerts: list[str] = []

    for recent in recent_by_agent:
        specialist = recent["specialist"]
        baseline = baseline_map.get(specialist)
        if baseline is None:
            continue  # No baseline data yet — skip

        # Need minimum sample sizes to avoid noise
        if recent["count"] < 3 or baseline["count"] < 5:
            continue

        for dim in _SCORE_DIMENSIONS:
            recent_val = recent.get(dim)
            baseline_val = baseline.get(dim)
            if recent_val is None or baseline_val is None:
                continue

            drop = baseline_val - recent_val
            if drop >= settings.quality_alert_threshold:
                label = _DIMENSION_LABELS.get(dim, dim)
                alerts.append(
                    f"  {specialist}: {label} dropped {drop:.2f} "
                    f"({baseline_val:.2f} -> {recent_val:.2f})"
                )

    if not alerts:
        logger.info("quality_alerts_none")
        return

    # Send alert to the first allowed user
    user_ids = settings.allowed_user_ids
    if not user_ids:
        logger.warning("quality_alerts_no_user_ids")
        return

    message = (
        "Quality Degradation Alert\n\n"
        f"Comparing last {settings.quality_alert_window_hours}h "
        f"vs {settings.quality_alert_baseline_days}d baseline:\n\n"
        + "\n".join(alerts)
        + "\n\nRun deep analysis with Claude Code to investigate."
    )

    try:
        await bot.send_message(chat_id=user_ids[0], text=message)
        logger.info("quality_alert_sent", alert_count=len(alerts))
    except Exception:
        logger.exception("quality_alert_send_failed")
        raise

    # --- Secondary fan-out: GitHub issue (Phase 3.9) ----------------------
    try:
        alert = AlertRecord(
            category="quality",
            title=f"Quality degradation across {len(alerts)} dimension(s)"[:120],
            summary=(
                f"Comparing last {settings.quality_alert_window_hours}h "
                f"vs {settings.quality_alert_baseline_days}d baseline; "
                f"{len(alerts)} agent/dimension pairs dropped below threshold."
            ),
            # Dimensions + agents form the fingerprint so a rebound in
            # one dimension doesn't wipe the issue for a persistent drop
            # in another.
            key_fields={"alerts": "|".join(sorted(alerts))},
            context={"Detail": message},
        )
        await file_github_issue(
            alert,
            settings=settings,
            session_factory=session_factory,
        )
    except Exception:
        logger.warning("quality_alert_github_filer_failed", exc_info=True)
