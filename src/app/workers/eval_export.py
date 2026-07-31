"""Daily evaluation data export — dumps interaction records to markdown files.

Runs daily via ARQ cron. Exports the last 24 hours of interaction records
to data/evaluation/exports/ as structured markdown files. These files are
designed for Claude Code to read during deep analysis sessions.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from src.app.config import Settings
from src.app.persistence.repositories.interactions import get_interactions_for_export

logger = structlog.get_logger()


async def run_eval_export(ctx: dict) -> None:
    """Export recent interaction records to markdown for Claude Code analysis.

    Called by ARQ cron (daily). Creates one file per day in the configured
    export directory.
    """
    settings: Settings = ctx["settings"]
    session_factory = ctx["session_factory"]

    if not bool(getattr(settings, "eval_export_enabled", False)):
        logger.info("eval_export_disabled")
        return

    export_dir = Path(settings.evaluation_export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240

    now = datetime.now(UTC)
    start = now - timedelta(hours=24)
    date_str = now.strftime("%Y-%m-%d")
    export_path = export_dir / f"interactions_{date_str}.md"

    async with session_factory() as session:
        records = await get_interactions_for_export(
            session,
            start=start,
            end=now,
        )

    if not records:
        logger.info("eval_export_no_records", date=date_str)
        return

    lines: list[str] = [
        f"# Interaction Records — {date_str}",
        "",
        f"Exported at: {now.isoformat()}",
        f"Records: {len(records)}",
        "",
    ]

    # Summary statistics
    scored = [r for r in records if r.score_relevance is not None]
    if scored:
        avg_rel = sum(r.score_relevance for r in scored) / len(scored)
        avg_act = sum(r.score_actionability for r in scored) / len(scored)
        avg_tone = sum(r.score_tone for r in scored) / len(scored)
        avg_conc = sum(r.score_conciseness for r in scored) / len(scored)
        lines.extend(
            [
                "## Summary Scores",
                "",
                f"- Avg Relevance: {avg_rel:.3f}",
                f"- Avg Actionability: {avg_act:.3f}",
                f"- Avg Tone: {avg_tone:.3f}",
                f"- Avg Conciseness: {avg_conc:.3f}",
                f"- Scored: {len(scored)}/{len(records)}",
                "",
            ]
        )

    # Feedback summary
    feedback_up = sum(1 for r in records if r.feedback_rating == "thumbs_up")
    feedback_down = sum(1 for r in records if r.feedback_rating == "thumbs_down")
    if feedback_up or feedback_down:
        lines.extend(
            [
                "## User Feedback",
                "",
                f"- Thumbs up: {feedback_up}",
                f"- Thumbs down: {feedback_down}",
                "",
            ]
        )

    # Individual records
    lines.append("## Records")
    lines.append("")

    for record in records:
        scores_str = "not scored"
        if record.score_relevance is not None:
            scores_str = (
                f"rel={record.score_relevance:.2f} "
                f"act={record.score_actionability:.2f} "
                f"tone={record.score_tone:.2f} "
                f"conc={record.score_conciseness:.2f}"
            )

        feedback_str = record.feedback_rating or "none"
        optimizer_str = (
            f"triggered ({record.optimizer_issue})" if record.optimizer_triggered else "no"
        )

        record_data = {
            "id": str(record.id),
            "specialist": record.specialist,
            "intent": record.intent_type,
            "confidence": record.routing_confidence,
            "duration_ms": record.duration_ms,
            "scores": scores_str,
            "feedback": feedback_str,
            "optimizer": optimizer_str,
            "user_message": record.user_message[:200],
            "response": record.response_content[:500],
        }

        if record.auto_judge_reasoning:
            record_data["judge_reasoning"] = record.auto_judge_reasoning

        lines.extend(
            [
                f"### {record.specialist} — {record.created_at.isoformat()}",
                "",
                "```json",
                json.dumps(record_data, indent=2),
                "```",
                "",
            ]
        )

    content = "\n".join(lines)
    export_path.write_text(content, encoding="utf-8")

    logger.info(
        "eval_export_complete",
        date=date_str,
        records=len(records),
        path=str(export_path),
    )
