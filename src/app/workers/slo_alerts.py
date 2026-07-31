"""SLO burn-rate Telegram alerts (P3.6).

Runs at user-local 09:15 daily — *before* the 09:30 quality-gate cron
and the 09:00 quality alerts — so the first operator notification of
the day is about objective breaches, not derivative signals.

Alerting contract:

* Compute all five SLOs (latency / error / quality / goodput / cost)
  over the last 24 hours.
* For each SLO with ``burn_rate >= slo_alert_burn_rate_threshold``
  (default 2.0 — double the acceptable consumption rate), include it
  in the alert.
* One Telegram message per run listing every breach. No dedup — this
  is a daily cron and the user expects at most one message per day.
* Bot not configured / no user IDs / db down → log and skip.

The actual SLO math lives in :mod:`src.app.core.slo`. This worker is
deliberately thin: fetch the report, compute burn-rate breaches, render
a message, send it.
"""

from __future__ import annotations

import structlog
from aiogram import Bot

from src.app.config import Settings
from src.app.core.slo import (
    DEFAULT_BURN_RATE_ALERT,
    SLOReport,
    SLOValue,
    collect_slo_report,
)
from src.app.workers.github_filer import AlertRecord, file_github_issue

logger = structlog.get_logger()


def _format_slo_line(slo: SLOValue) -> str:
    """Render one breach into a readable, grep-friendly line."""
    return (
        f"  {slo.name}: current={slo.current}{_unit_suffix(slo.unit)} "
        f"target={slo.target}{_unit_suffix(slo.unit)} "
        f"burn_rate={slo.burn_rate:.2f}x (n={slo.sample_size})"
    )


def _unit_suffix(unit: str) -> str:
    match unit:
        case "seconds":
            return "s"
        case "gbp":
            return "\u00a3"  # £
        case _:
            return ""


def format_alert_message(report: SLOReport, breaches: list[SLOValue]) -> str:
    """Assemble the final Telegram message."""
    header = (
        f"SLO Burn-Rate Alert ({report.window_hours}h window)\n"
        f"Generated at: {report.generated_at.isoformat()}\n"
        f"{len(breaches)} SLO(s) over {DEFAULT_BURN_RATE_ALERT:g}x error-budget burn:\n"
    )
    lines = [_format_slo_line(b) for b in breaches]
    footer = (
        "\nInvestigate with Claude Code: check traces for latency /"
        " error spikes, run quality_report for degraded agents, and"
        " inspect cost_alerts for spend regressions."
    )
    return header + "\n".join(lines) + footer


async def run_slo_alerts(ctx: dict) -> None:
    """Cron entry point — compute SLO report and alert on burn-rate breaches."""
    settings: Settings = ctx["settings"]
    bot: Bot | None = ctx.get("bot")
    session_factory = ctx.get("session_factory")

    if not bool(getattr(settings, "slo_alerts_enabled", False)):
        logger.info("slo_alerts_disabled")
        return
    if bot is None:
        logger.warning("slo_alerts_no_bot", hint="Telegram not configured")
        return
    if session_factory is None:
        logger.warning("slo_alerts_no_session_factory")
        return

    user_ids = settings.allowed_user_ids
    if not user_ids:
        logger.warning("slo_alerts_no_user_ids")
        return

    threshold = float(getattr(settings, "slo_alert_burn_rate_threshold", DEFAULT_BURN_RATE_ALERT))

    try:
        async with session_factory() as session:
            report = await collect_slo_report(session, settings)
    except Exception:
        logger.exception("slo_alerts_report_failed")
        return

    breaches = report.breaches(threshold=threshold)
    if not breaches:
        logger.info(
            "slo_alerts_none",
            window_hours=report.window_hours,
            slo_count=len(report.slos),
        )
        return

    message = format_alert_message(report, breaches)
    try:
        await bot.send_message(chat_id=user_ids[0], text=message)
        logger.warning(
            "slo_alert_sent",
            breaches=[b.name for b in breaches],
            threshold=threshold,
        )
    except Exception:
        logger.exception("slo_alert_send_failed")
        raise

    # --- Secondary fan-out: GitHub issue (Phase 3.9) ----------------------
    try:
        breach_names = sorted(b.name for b in breaches)
        alert = AlertRecord(
            category="slo_burn",
            title=(
                "SLO burn-rate breach: "
                + ", ".join(breach_names[:3])
                + (" + more" if len(breach_names) > 3 else "")
            )[:120],
            summary=(
                f"{len(breaches)} SLO(s) burning error budget at "
                f">= {threshold:g}x over the last "
                f"{report.window_hours}h window."
            ),
            key_fields={"breaches": "|".join(breach_names)},
            context={"Detail": message},
        )
        await file_github_issue(
            alert,
            settings=settings,
            session_factory=session_factory,
        )
    except Exception:
        logger.warning("slo_alert_github_filer_failed", exc_info=True)


__all__ = ["format_alert_message", "run_slo_alerts"]
