"""Auto-judge worker — scores pending InteractionRecords via Haiku.

Runs as an ARQ cron job (default: every 4 hours). Processes a batch of
pending records, scoring each on 4 universal dimensions plus the specialist
binary sub-checks parsed from ``data/evaluation/rubrics/<agent>.md``.
Failures are logged loudly but don't block other records in the batch.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from anthropic import AsyncAnthropic

from src.app.config import Settings
from src.app.core.auto_judge import (
    score_interaction,
    summarize_specialist_dimensions,
)
from src.app.core.rubric_loader import load_specialist_rubric
from src.app.domain.models import Specialist
from src.app.persistence.repositories.interactions import (
    get_pending_interactions,
    update_auto_judge_scores,
)

logger = structlog.get_logger()


def _specialist_summary(specialist: str, scores) -> dict[str, dict[str, object]] | None:
    """Compute the specialist dimension summary (per-check booleans + sums).

    Returns None if the rubric could not be loaded for the specialist — in which
    case nothing specialist-specific is stored. Universal scores are unaffected.
    """
    try:
        enum_value = Specialist(specialist)
    except ValueError:
        return None
    try:
        rubric = load_specialist_rubric(enum_value)
    except (KeyError, FileNotFoundError, ValueError):
        return None
    return summarize_specialist_dimensions(rubric, scores)


async def run_auto_judge(ctx: dict) -> None:
    """Score pending interactions with the auto-judge.

    Called by ARQ cron. Processes up to batch_size records per run.
    Each record is scored independently — one failure doesn't block others.
    """
    settings: Settings = ctx["settings"]
    session_factory = ctx["session_factory"]

    if not settings.auto_judge_enabled:
        logger.info("auto_judge_disabled")
        return

    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
    )

    scored = 0
    failed = 0

    try:
        async with session_factory() as session:
            pending = await get_pending_interactions(
                session,
                limit=settings.auto_judge_batch_size,
            )

            if not pending:
                logger.info("auto_judge_no_pending")
                return

            logger.info("auto_judge_batch_start", count=len(pending))

            for record in pending:
                try:
                    scores = await score_interaction(
                        client,
                        model=settings.auto_judge_model,
                        max_tokens=settings.auto_judge_max_tokens,
                        user_message=record.user_message,
                        response_content=record.response_content,
                        specialist=record.specialist,
                    )

                    specialist_summary = _specialist_summary(record.specialist, scores)

                    await update_auto_judge_scores(
                        session,
                        record.id,
                        score_relevance=scores.relevance,
                        score_actionability=scores.actionability,
                        score_tone=scores.tone,
                        score_conciseness=scores.conciseness,
                        reasoning=scores.reasoning,
                        scored_at=datetime.now(UTC),
                        specialist_summary=specialist_summary,
                    )
                    scored += 1

                except Exception:
                    failed += 1
                    logger.error(
                        "auto_judge_record_failed",
                        interaction_id=str(record.id),
                        exc_info=True,
                    )

            await session.commit()

    finally:
        await client.close()

    logger.info(
        "auto_judge_batch_complete",
        scored=scored,
        failed=failed,
        total=scored + failed,
    )
