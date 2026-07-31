"""CLI tool for generating per-agent quality summary reports.

Produces a readable markdown report with score distributions, trends,
and per-dimension analysis for Claude Code to review.

Usage:
    # 30-day quality report for diary agent
    uv run python -m scripts.quality_report --agent diary --days 30

    # 7-day report for all agents
    uv run python -m scripts.quality_report --days 7

    # Last 90 days for research agent
    uv run python -m scripts.quality_report --agent research --days 90
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from src.app.config import get_settings
from src.app.persistence.database import init_engine, init_session_factory

logger = structlog.get_logger()

_DIMENSIONS = ("relevance", "actionability", "tone", "conciseness")


async def _generate_report(args: argparse.Namespace) -> None:
    """Generate a quality report for one or all agents."""
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.app.domain.constants import EvalStatus
    from src.app.persistence.models import InteractionRecord

    settings = get_settings()
    engine = init_engine(settings.database_url.get_secret_value())
    session_factory = init_session_factory(engine)

    now = datetime.now(UTC)
    start = now - timedelta(days=args.days)

    async with session_factory() as session:
        session: AsyncSession

        # Base conditions
        base_conditions = [
            InteractionRecord.eval_status.in_([EvalStatus.AUTO_SCORED, EvalStatus.DEEP_SCORED]),
            InteractionRecord.created_at >= start,
        ]
        if args.agent:
            base_conditions.append(InteractionRecord.specialist == args.agent)

        # Overall averages
        avg_stmt = select(
            func.avg(InteractionRecord.score_relevance).label("avg_rel"),
            func.avg(InteractionRecord.score_actionability).label("avg_act"),
            func.avg(InteractionRecord.score_tone).label("avg_tone"),
            func.avg(InteractionRecord.score_conciseness).label("avg_conc"),
            func.count(InteractionRecord.id).label("total"),
        ).where(*base_conditions)
        avg_row = (await session.execute(avg_stmt)).one()

        # Per-specialist breakdown
        specialist_stmt = (
            select(
                InteractionRecord.specialist,
                func.avg(InteractionRecord.score_relevance).label("avg_rel"),
                func.avg(InteractionRecord.score_actionability).label("avg_act"),
                func.avg(InteractionRecord.score_tone).label("avg_tone"),
                func.avg(InteractionRecord.score_conciseness).label("avg_conc"),
                func.count(InteractionRecord.id).label("count"),
            )
            .where(*base_conditions)
            .group_by(InteractionRecord.specialist)
            .order_by(func.count(InteractionRecord.id).desc())
        )
        specialist_rows = (await session.execute(specialist_stmt)).all()

        # Feedback summary
        feedback_stmt = (
            select(
                InteractionRecord.feedback_rating,
                func.count(InteractionRecord.id).label("count"),
            )
            .where(
                *base_conditions,
                InteractionRecord.feedback_rating.isnot(None),
            )
            .group_by(InteractionRecord.feedback_rating)
        )
        feedback_rows = (await session.execute(feedback_stmt)).all()

        # Optimizer trigger rate
        optimizer_stmt = select(
            func.count(InteractionRecord.id).label("triggered"),
        ).where(
            *base_conditions,
            InteractionRecord.optimizer_triggered.is_(True),
        )
        optimizer_count = (await session.execute(optimizer_stmt)).scalar() or 0

        # Worst interactions (for Claude Code attention)
        worst_stmt = (
            select(InteractionRecord)
            .where(*base_conditions)
            .order_by(InteractionRecord.score_relevance.asc().nullslast())
            .limit(10)
        )
        worst_records = list((await session.execute(worst_stmt)).scalars().all())

        # Best interactions (for golden dataset candidates)
        best_stmt = (
            select(InteractionRecord)
            .where(*base_conditions)
            .order_by(InteractionRecord.score_relevance.desc().nullslast())
            .limit(5)
        )
        best_records = list((await session.execute(best_stmt)).scalars().all())

    # Build markdown report
    agent_label = args.agent or "all"
    date_str = now.strftime("%Y-%m-%d")
    lines: list[str] = [
        f"# Quality Report — {agent_label} — {args.days}d — {date_str}",
        "",
        f"Generated at: {now.isoformat()}",
        f"Period: {start.strftime('%Y-%m-%d')} to {date_str}",
        f"Total scored interactions: {avg_row.total}",
        "",
    ]

    # Overall scores
    if avg_row.total > 0:
        lines.extend(
            [
                "## Overall Scores",
                "",
                "| Dimension | Average |",
                "|-----------|---------|",
                f"| Relevance | {avg_row.avg_rel:.3f} |"
                if avg_row.avg_rel
                else "| Relevance | N/A |",
                (
                    f"| Actionability | {avg_row.avg_act:.3f} |"
                    if avg_row.avg_act
                    else "| Actionability | N/A |"
                ),
                (f"| Tone | {avg_row.avg_tone:.3f} |" if avg_row.avg_tone else "| Tone | N/A |"),
                (
                    f"| Conciseness | {avg_row.avg_conc:.3f} |"
                    if avg_row.avg_conc
                    else "| Conciseness | N/A |"
                ),
                "",
            ]
        )
    else:
        lines.extend(["## No scored interactions in this period.", ""])

    # Per-specialist breakdown
    if specialist_rows and not args.agent:
        lines.extend(
            [
                "## Per-Specialist Breakdown",
                "",
                "| Specialist | Count | Relevance | Actionability | Tone | Conciseness |",
                "|------------|-------|-----------|---------------|------|-------------|",
            ]
        )
        for row in specialist_rows:
            lines.append(
                f"| {row.specialist} | {row.count} | {row.avg_rel:.3f}"
                if row.avg_rel
                else f"| N/A | {row.avg_act:.3f}"
                if row.avg_act
                else f" | N/A | {row.avg_tone:.3f}"
                if row.avg_tone
                else f" | N/A | {row.avg_conc:.3f} |"
                if row.avg_conc
                else " | N/A |",
            )
        lines.append("")

    # Feedback summary
    if feedback_rows:
        lines.extend(["## User Feedback", ""])
        for row in feedback_rows:
            lines.append(f"- {row.feedback_rating}: {row.count}")
        lines.append("")

    # Optimizer stats
    total = avg_row.total or 1
    lines.extend(
        [
            "## Optimizer Trigger Rate",
            "",
            f"- Triggered: {optimizer_count}/{total} ({optimizer_count / total * 100:.1f}%)",
            "",
        ]
    )

    # Worst interactions
    if worst_records:
        lines.extend(
            [
                "## Worst Interactions (lowest relevance)",
                "",
                "These need the most attention:",
                "",
            ]
        )
        for record in worst_records:
            scores = {
                d: getattr(record, f"score_{d}")
                for d in _DIMENSIONS
                if getattr(record, f"score_{d}") is not None
            }
            record_data = {
                "id": str(record.id),
                "specialist": record.specialist,
                "scores": scores,
                "user_message": record.user_message[:300],
                "response": record.response_content[:500],
            }
            if record.auto_judge_reasoning:
                record_data["reasoning"] = record.auto_judge_reasoning
            lines.extend(
                [
                    "```json",
                    json.dumps(record_data, indent=2),
                    "```",
                    "",
                ]
            )

    # Best interactions (golden dataset candidates)
    if best_records:
        lines.extend(
            [
                "## Best Interactions (golden dataset candidates)",
                "",
                "Consider adding these to the golden dataset:",
                "",
            ]
        )
        for record in best_records:
            scores = {
                d: getattr(record, f"score_{d}")
                for d in _DIMENSIONS
                if getattr(record, f"score_{d}") is not None
            }
            lines.extend(
                [
                    f"- **{record.specialist}** (rel={scores.get('relevance', 'N/A')}): "
                    f"{record.user_message[:100]}...",
                ]
            )
        lines.append("")

    content = "\n".join(lines)

    # Write report
    reports_dir = Path("data/evaluation/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    export_path = reports_dir / f"{agent_label}_quality_{args.days}d.md"
    export_path.write_text(content, encoding="utf-8")
    print(f"Report written to {export_path}")

    from src.app.persistence.database import close_engine

    await close_engine()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate per-agent quality summary reports",
    )
    parser.add_argument("--agent", type=str, default=None, help="Specialist agent name")
    parser.add_argument("--days", type=int, default=30, help="Report period in days (default: 30)")

    args = parser.parse_args()
    asyncio.run(_generate_report(args))


if __name__ == "__main__":
    main()
