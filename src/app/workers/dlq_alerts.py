"""Hourly cron that fires a Telegram alert when un-replayed DLQ rows age out.

Scheduled at minute :50 (offset from other alert jobs that run on :00/:15/:25).
A single alert is sent whenever any dlq_jobs row has ``failed_at`` older than
``dlq_alert_age_threshold_hours`` AND ``replayed_at IS NULL``.
"""

from __future__ import annotations

import structlog
from aiogram import Bot

from src.app.config import Settings
from src.app.persistence.repositories.dlq_jobs import count_unreplayed_older_than
from src.app.workers.github_filer import AlertRecord, file_github_issue

logger = structlog.get_logger()


async def run_dlq_alerts(ctx: dict) -> None:
    """Alert via Telegram when aged, un-replayed DLQ rows exist.

    Called by ARQ cron (hourly at :50). Uses the bot from worker context.
    """
    settings: Settings = ctx["settings"]
    if not settings.dlq_alert_enabled:
        logger.info("dlq_alerts_disabled")
        return

    bot: Bot | None = ctx.get("bot")
    if bot is None:
        logger.warning("dlq_alerts_no_bot", hint="Telegram not configured")
        return

    session_factory = ctx.get("session_factory")
    if session_factory is None:
        logger.error("dlq_alerts_no_session_factory")
        return

    threshold_hours = settings.dlq_alert_age_threshold_hours
    threshold_count = max(1, settings.dlq_alert_threshold_count)

    async with session_factory() as session:
        counts = await count_unreplayed_older_than(session, hours=threshold_hours)

    total = sum(counts.values())
    if total < threshold_count:
        logger.info(
            "dlq_alerts_under_threshold",
            total=total,
            threshold=threshold_count,
            age_hours=threshold_hours,
        )
        return

    user_ids = settings.allowed_user_ids
    if not user_ids:
        logger.warning("dlq_alerts_no_user_ids")
        return

    lines = [f"  {fn}: {count}" for fn, count in sorted(counts.items())]
    message = (
        "Dead-Letter Queue Alert\n\n"
        f"{total} un-replayed job(s) older than {threshold_hours}h:\n\n"
        + "\n".join(lines)
        + "\n\nInspect with `uv run python -m scripts.dlq_replay list`."
    )

    try:
        await bot.send_message(chat_id=user_ids[0], text=message)
        logger.info(
            "dlq_alert_sent",
            total=total,
            functions=sorted(counts.keys()),
        )
    except Exception:
        logger.exception("dlq_alert_send_failed")
        raise

    # --- Secondary fan-out: GitHub issue (Phase 3.9) ----------------------
    # Telegram is the fast path; GitHub is the durable backlog the next
    # Claude Code session will triage. Wrapped in a broad try/except so a
    # GitHub-side failure can never break the alert flow.
    try:
        # Fingerprint includes the top offending functions so a DLQ storm
        # in a single handler dedups to one issue, but a new failing
        # handler gets its own issue.
        top_fns = sorted(counts.keys())
        alert = AlertRecord(
            category="dlq",
            title=(
                "DLQ: "
                + ", ".join(f"{fn} x{counts[fn]}" for fn in top_fns[:3])
                + (" + more" if len(top_fns) > 3 else "")
            )[:120],
            summary=(
                f"{total} un-replayed ARQ job(s) older than "
                f"{threshold_hours}h in the dead-letter queue."
            ),
            key_fields={"functions": ",".join(top_fns)},
            context={"Message": message},
        )
        await file_github_issue(
            alert,
            settings=settings,
            session_factory=session_factory,
        )
    except Exception:
        logger.warning("dlq_alert_github_filer_failed", exc_info=True)
