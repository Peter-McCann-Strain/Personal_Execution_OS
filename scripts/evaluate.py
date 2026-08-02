"""CLI tool for evaluation data flow — export interactions and store deep scores.

Usage:
    # Export interactions with auto-judge scores for independent review
    uv run python -m scripts.evaluate export --agent diary --last 50

    # Export all agents
    uv run python -m scripts.evaluate export --last 100

    # Store deep evaluation scores back to the database
    uv run python -m scripts.evaluate store --file data/evaluation/scored/diary_2026-03-18.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from src.app.config import get_settings
from src.app.persistence.database import init_engine, init_session_factory

logger = structlog.get_logger()


async def _export(args: argparse.Namespace) -> None:
    """Export interactions to Markdown for independent review."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.app.persistence.models import InteractionRecord

    settings = get_settings()
    engine = init_engine(settings.database_url.get_secret_value())
    session_factory = init_session_factory(engine)

    now = datetime.now(UTC)
    start = now - timedelta(hours=args.last * 24) if args.days else now

    # If --last is specified, it's a record count limit; if --days, it's a time range
    async with session_factory() as session:
        session: AsyncSession
        stmt = (
            select(InteractionRecord)
            .where(InteractionRecord.created_at >= start)
            .order_by(InteractionRecord.created_at.desc())
        )
        if args.agent:
            stmt = stmt.where(InteractionRecord.specialist == args.agent)
        stmt = stmt.limit(args.last)

        result = await session.execute(stmt)
        records = list(result.scalars().all())

    if not records:
        print("No interactions found matching criteria.")
        return

    # Build markdown output
    agent_label = args.agent or "all"
    date_str = now.strftime("%Y-%m-%d")
    lines: list[str] = [
        f"# Interaction Export — {agent_label} — {date_str}",
        "",
        f"Exported at: {now.isoformat()}",
        f"Records: {len(records)}",
        f"Filter: agent={agent_label}, last={args.last}",
        "",
    ]

    # Summary stats for scored records
    scored = [r for r in records if r.score_relevance is not None]
    if scored:
        avg_rel = sum(r.score_relevance for r in scored) / len(scored)
        avg_act = sum(r.score_actionability for r in scored) / len(scored)
        avg_tone = sum(r.score_tone for r in scored) / len(scored)
        avg_conc = sum(r.score_conciseness for r in scored) / len(scored)
        lines.extend(
            [
                "## Auto-Judge Summary",
                "",
                f"- Avg Relevance: {avg_rel:.3f}",
                f"- Avg Actionability: {avg_act:.3f}",
                f"- Avg Tone: {avg_tone:.3f}",
                f"- Avg Conciseness: {avg_conc:.3f}",
                f"- Scored: {len(scored)}/{len(records)}",
                "",
            ]
        )

    # Low-scoring interactions flagged for review
    low_scoring = [
        r
        for r in scored
        if any(
            getattr(r, f"score_{dim}") < 0.6
            for dim in ("relevance", "actionability", "tone", "conciseness")
            if getattr(r, f"score_{dim}") is not None
        )
    ]
    if low_scoring:
        lines.extend(
            [
                f"## Flagged for Review ({len(low_scoring)} records with score < 0.6)",
                "",
            ]
        )

    # Individual records
    lines.extend(["## Records", ""])

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
        eval_str = record.eval_status or "unknown"

        record_data = {
            "id": str(record.id),
            "specialist": record.specialist,
            "intent": record.intent_type,
            "confidence": record.routing_confidence,
            "duration_ms": record.duration_ms,
            "eval_status": eval_str,
            "scores": scores_str,
            "feedback": feedback_str,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "user_message": record.user_message[:500],
            "response": record.response_content[:1000],
        }

        if record.auto_judge_reasoning:
            record_data["judge_reasoning"] = record.auto_judge_reasoning

        if record.optimizer_triggered:
            record_data["optimizer_issue"] = record.optimizer_issue

        lines.extend(
            [
                f"### {record.specialist} — "
                f"{record.created_at.isoformat() if record.created_at else 'unknown'}",
                "",
                "```json",
                json.dumps(record_data, indent=2),
                "```",
                "",
            ]
        )

    content = "\n".join(lines)

    # Write to export directory
    export_dir = Path(settings.evaluation_export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    export_path = export_dir / f"{agent_label}_{date_str}.md"
    export_path.write_text(content, encoding="utf-8")
    print(f"Exported {len(records)} records to {export_path}")

    from src.app.persistence.database import close_engine

    await close_engine()


async def _store(args: argparse.Namespace) -> None:
    """Store deep evaluation scores from a JSON file back to the database."""
    from src.app.domain.constants import EvalStatus
    from src.app.persistence.models import InteractionRecord

    score_file = Path(args.file)
    if not score_file.exists():  # noqa: ASYNC240
        print(f"File not found: {score_file}")
        sys.exit(1)

    data = json.loads(score_file.read_text(encoding="utf-8"))  # noqa: ASYNC240
    if not isinstance(data, list):
        print("Expected a JSON array of scored records.")
        sys.exit(1)

    settings = get_settings()
    engine = init_engine(settings.database_url.get_secret_value())
    session_factory = init_session_factory(engine)

    stored = 0
    failed = 0

    async with session_factory() as session:
        for entry in data:
            try:
                from uuid import UUID

                from sqlalchemy import update

                interaction_id = UUID(entry["id"])
                values: dict = {
                    "eval_status": EvalStatus.DEEP_SCORED,
                    "scored_at": datetime.now(UTC),
                }

                # Store deep eval scores in the deep_scores JSONB field
                deep_scores = {}
                for key in (
                    "relevance",
                    "actionability",
                    "tone",
                    "conciseness",
                    "emotional_attunement",
                    "reflection_depth",
                    "classification_accuracy",
                    "link_quality",
                    "source_quality",
                    "synthesis_depth",
                    "pattern_validity",
                    "insight_novelty",
                    "timing_appropriateness",
                    "signal_vs_noise",
                    "execution_correctness",
                    "feasibility",
                    "prioritisation_quality",
                    "voice_match",
                    "professional_quality",
                ):
                    if key in entry:
                        deep_scores[key] = entry[key]

                if deep_scores:
                    values["deep_scores"] = deep_scores

                if "reasoning" in entry:
                    values["deep_eval_reasoning"] = entry["reasoning"]

                stmt = (
                    update(InteractionRecord)
                    .where(InteractionRecord.id == interaction_id)
                    .values(**values)
                )
                await session.execute(stmt)
                stored += 1

            except Exception as exc:
                failed += 1
                print(f"Failed to store {entry.get('id', '?')}: {exc}")

        await session.commit()

    print(f"Stored {stored} deep scores ({failed} failed)")

    from src.app.persistence.database import close_engine

    await close_engine()


def _validate_assets(_: argparse.Namespace) -> None:
    """Validate rubric and dataset assets used by CI and local eval runs."""
    from src.app.core.evaluation_registry import list_eval_suites, validate_evaluation_assets

    errors = validate_evaluation_assets()
    if errors:
        for error in errors:
            print(f"- {error}")
        sys.exit(1)

    suites = list_eval_suites()
    print(f"Validated {len(suites)} specialist evaluation suites under data/evaluation")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Evaluation data flow — export interactions and store deep scores",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Export subcommand
    export_parser = subparsers.add_parser("export", help="Export interactions for deep evaluation")
    export_parser.add_argument("--agent", type=str, default=None, help="Filter by specialist agent")
    export_parser.add_argument("--last", type=int, default=50, help="Number of records to export")
    export_parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Export records from the last N days (overrides --last as time filter)",
    )

    # Store subcommand
    store_parser = subparsers.add_parser("store", help="Store deep evaluation scores")
    store_parser.add_argument("--file", type=str, required=True, help="Path to scored JSON file")

    subparsers.add_parser(
        "validate-assets",
        help="Validate evaluation rubrics and golden datasets",
    )

    args = parser.parse_args()

    if args.command == "export":
        asyncio.run(_export(args))
    elif args.command == "store":
        asyncio.run(_store(args))
    elif args.command == "validate-assets":
        _validate_assets(args)


if __name__ == "__main__":
    main()
