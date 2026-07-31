"""CLI tool for exporting sample interactions for A/B testing prompt changes.

Exports a random sample of recent interactions with their scores. Claude Code
reads these samples, judges whether a new prompt would produce better responses,
and makes a keep/revert decision.

Usage:
    # Export 20 random diary samples for A/B comparison
    uv run python -m scripts.quick_eval --agent diary --samples 20

    # Export samples scored below 0.7 (focus on improvement opportunities)
    uv run python -m scripts.quick_eval --agent diary --samples 20 --max-score 0.7
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


async def _export_samples(args: argparse.Namespace) -> None:
    """Export random sample interactions for A/B testing."""
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

        conditions = [
            InteractionRecord.eval_status.in_([EvalStatus.AUTO_SCORED, EvalStatus.DEEP_SCORED]),
            InteractionRecord.created_at >= start,
        ]
        if args.agent:
            conditions.append(InteractionRecord.specialist == args.agent)

        if args.max_score is not None:
            # Focus on lower-scoring records for improvement analysis
            conditions.append(
                InteractionRecord.score_relevance <= args.max_score,
            )

        # Random sample using database ordering
        stmt = (
            select(InteractionRecord).where(*conditions).order_by(func.random()).limit(args.samples)
        )
        result = await session.execute(stmt)
        records = list(result.scalars().all())

    if not records:
        print("No scored interactions found matching criteria.")
        from src.app.persistence.database import close_engine

        await close_engine()
        return

    # Build markdown output for A/B testing
    agent_label = args.agent or "all"
    date_str = now.strftime("%Y-%m-%d")
    lines: list[str] = [
        f"# A/B Test Samples — {agent_label} — {date_str}",
        "",
        f"Generated at: {now.isoformat()}",
        f"Samples: {len(records)}",
        f"Period: last {args.days} days",
        "",
        "## Instructions for Claude Code",
        "",
        "For each sample below:",
        "1. Read the user message",
        "2. Read the current response and its scores",
        "3. Consider: would the NEW prompt produce a better response?",
        "4. Score the expected new response on the same dimensions",
        "5. Record: WIN (new better), LOSS (old better), or TIE",
        "",
        "Decision threshold: if new prompt wins >60% of samples, commit the change.",
        "",
        "---",
        "",
    ]

    for i, record in enumerate(records, 1):
        scores = {
            d: getattr(record, f"score_{d}")
            for d in _DIMENSIONS
            if getattr(record, f"score_{d}") is not None
        }

        sample_data = {
            "sample_number": i,
            "id": str(record.id),
            "specialist": record.specialist,
            "current_scores": scores,
            "user_message": record.user_message,
            "current_response": record.response_content,
        }

        if record.auto_judge_reasoning:
            sample_data["judge_reasoning"] = record.auto_judge_reasoning

        lines.extend(
            [
                f"### Sample {i}/{len(records)}",
                "",
                "```json",
                json.dumps(sample_data, indent=2, ensure_ascii=False),
                "```",
                "",
                f"**Current scores:** {json.dumps(scores)}",
                "",
                "**New prompt verdict:** [ WIN / LOSS / TIE ]",
                "**New expected scores:** {{ fill in }}",
                "**Notes:** {{ fill in }}",
                "",
                "---",
                "",
            ]
        )

    content = "\n".join(lines)

    # Write to ab_tests directory
    ab_dir = Path("data/evaluation/ab_tests")
    ab_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    export_path = ab_dir / f"{agent_label}_samples_{date_str}.md"
    export_path.write_text(content, encoding="utf-8")
    print(f"Exported {len(records)} samples to {export_path}")

    from src.app.persistence.database import close_engine

    await close_engine()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export sample interactions for A/B testing prompt changes",
    )
    parser.add_argument("--agent", type=str, default=None, help="Specialist agent name")
    parser.add_argument("--samples", type=int, default=20, help="Number of samples (default: 20)")
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Sample from last N days (default: 14)",
    )
    parser.add_argument(
        "--max-score",
        type=float,
        default=None,
        help="Only include records scoring at or below this threshold",
    )

    args = parser.parse_args()
    asyncio.run(_export_samples(args))


if __name__ == "__main__":
    main()
