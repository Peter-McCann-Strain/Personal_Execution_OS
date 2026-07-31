"""CLI tool for exporting low-scoring interactions grouped by failure pattern.

Exports interactions that scored below a threshold on any dimension, grouped by
the lowest-scoring dimension. Designed for Claude Code to analyse and identify
improvement opportunities.

Usage:
    # Export diary failures from the last 7 days
    uv run python -m scripts.failures --agent diary --days 7

    # Export all failures below 0.5 threshold
    uv run python -m scripts.failures --days 14 --threshold 0.5

    # Export failures for a specific dimension
    uv run python -m scripts.failures --agent diary --dimension relevance --days 7
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


async def _export_failures(args: argparse.Namespace) -> None:
    """Export low-scoring interactions grouped by failure pattern."""
    from sqlalchemy import or_, select
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.app.domain.constants import EvalStatus
    from src.app.persistence.models import InteractionRecord

    settings = get_settings()
    engine = init_engine(settings.database_url.get_secret_value())
    session_factory = init_session_factory(engine)

    now = datetime.now(UTC)
    start = now - timedelta(days=args.days)
    threshold = args.threshold

    async with session_factory() as session:
        session: AsyncSession

        # Build query for records below threshold on any dimension
        conditions = [
            InteractionRecord.created_at >= start,
            InteractionRecord.eval_status.in_([EvalStatus.AUTO_SCORED, EvalStatus.DEEP_SCORED]),
        ]

        if args.agent:
            conditions.append(InteractionRecord.specialist == args.agent)

        if args.dimension:
            # Filter by specific dimension
            dim_col = getattr(InteractionRecord, f"score_{args.dimension}")
            conditions.append(dim_col < threshold)
        else:
            # Any dimension below threshold
            conditions.append(
                or_(
                    InteractionRecord.score_relevance < threshold,
                    InteractionRecord.score_actionability < threshold,
                    InteractionRecord.score_tone < threshold,
                    InteractionRecord.score_conciseness < threshold,
                ),
            )

        stmt = (
            select(InteractionRecord)
            .where(*conditions)
            .order_by(InteractionRecord.created_at.desc())
            .limit(args.limit)
        )
        result = await session.execute(stmt)
        records = list(result.scalars().all())

    if not records:
        print("No failures found matching criteria.")
        from src.app.persistence.database import close_engine

        await close_engine()
        return

    # Group by lowest-scoring dimension
    grouped: dict[str, list] = {dim: [] for dim in _DIMENSIONS}
    for record in records:
        lowest_dim = min(
            _DIMENSIONS,
            key=lambda d: getattr(record, f"score_{d}") or 1.0,
        )
        grouped[lowest_dim].append(record)

    # Build markdown output
    agent_label = args.agent or "all"
    date_str = now.strftime("%Y-%m-%d")
    lines: list[str] = [
        f"# Failure Analysis — {agent_label} — {date_str}",
        "",
        f"Exported at: {now.isoformat()}",
        f"Period: last {args.days} days",
        f"Threshold: < {threshold}",
        f"Total failures: {len(records)}",
        "",
        "## Failure Distribution",
        "",
    ]

    for dim in _DIMENSIONS:
        count = len(grouped[dim])
        if count > 0:
            lines.append(f"- **{dim}**: {count} records (lowest dimension)")
    lines.append("")

    # Per-dimension sections
    for dim in _DIMENSIONS:
        dim_records = grouped[dim]
        if not dim_records:
            continue

        lines.extend(
            [
                f"## Failures: {dim.title()} (lowest dimension)",
                "",
                f"**{len(dim_records)} records** where {dim} was the weakest score.",
                "",
            ]
        )

        for record in dim_records:
            score_val = getattr(record, f"score_{dim}")
            all_scores = {
                d: getattr(record, f"score_{d}")
                for d in _DIMENSIONS
                if getattr(record, f"score_{d}") is not None
            }

            record_data = {
                "id": str(record.id),
                "specialist": record.specialist,
                "weakest_dimension": dim,
                "weakest_score": score_val,
                "all_scores": all_scores,
                "user_message": record.user_message[:500],
                "response": record.response_content[:1000],
            }

            if record.auto_judge_reasoning:
                record_data["judge_reasoning"] = record.auto_judge_reasoning

            if record.optimizer_triggered:
                record_data["optimizer_issue"] = record.optimizer_issue

            lines.extend(
                [
                    f"### {record.specialist} — {dim}={score_val:.2f}",
                    "",
                    "```json",
                    json.dumps(record_data, indent=2),
                    "```",
                    "",
                ]
            )

    content = "\n".join(lines)

    # Write to failures directory
    failures_dir = Path("data/evaluation/failures")
    failures_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    filename = f"{agent_label}_{date_str}.md"
    if args.dimension:
        filename = f"{agent_label}_{args.dimension}_{date_str}.md"
    export_path = failures_dir / filename
    export_path.write_text(content, encoding="utf-8")
    print(f"Exported {len(records)} failure records to {export_path}")

    from src.app.persistence.database import close_engine

    await close_engine()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export low-scoring interactions for failure analysis",
    )
    parser.add_argument("--agent", type=str, default=None, help="Filter by specialist agent")
    parser.add_argument("--days", type=int, default=7, help="Look back N days (default: 7)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="Score threshold — records below this are failures (default: 0.6)",
    )
    parser.add_argument(
        "--dimension",
        type=str,
        default=None,
        choices=list(_DIMENSIONS),
        help="Filter by specific dimension",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max records to export (default: 200)",
    )

    args = parser.parse_args()
    asyncio.run(_export_failures(args))


if __name__ == "__main__":
    main()
