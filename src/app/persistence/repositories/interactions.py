"""InteractionRecord repository — CRUD + query for evaluation pipeline.

All functions require the caller to manage session.commit(). Use
``async with session.begin():`` for automatic transaction management.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from inspect import isawaitable
from typing import TypedDict

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.async_utils import affected_rows, maybe_await
from src.app.domain.constants import EvalStatus, FeedbackRating
from src.app.persistence.models import InteractionRecord

logger = structlog.get_logger()


class AverageScores(TypedDict):
    """Typed aggregate returned by the monitoring quality-score query."""

    relevance: float | None
    actionability: float | None
    tone: float | None
    conciseness: float | None
    count: int


def _aggregate_field(row: object, name: str) -> object:
    """Read a labelled SQLAlchemy value without tuple-method collisions."""
    mapping = getattr(row, "_mapping", None)
    if isinstance(mapping, Mapping):
        return mapping.get(name)
    return getattr(row, name, None)


def _aggregate_score(row: object, name: str) -> float | None:
    value = _aggregate_field(row, name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _aggregate_count(row: object) -> int:
    value = _aggregate_field(row, "count")
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("quality-score count query returned a non-integer value")
    if value < 0:
        raise ValueError("quality-score count query returned a negative value")
    return value


async def create_interaction(
    session: AsyncSession,
    *,
    user_id: str,
    user_message: str,
    source: str,
    intent_type: str,
    specialist: str,
    routing_confidence: float,
    response_content: str,
    response_agent: str,
    optimizer_triggered: bool,
    optimizer_issue: str | None,
    duration_ms: int,
    trace_id: str | None = None,
    workflow_id: str | None = None,
    workflow_status: str | None = None,
    response_id: str | None = None,
    quality_scores: dict | None = None,
    channel_metrics: dict | None = None,
    eval_status: str = EvalStatus.PENDING,
) -> InteractionRecord:
    """Create a new InteractionRecord after a successful process_message cycle."""
    record = InteractionRecord(
        user_id=user_id,
        user_message=user_message,
        source=source,
        intent_type=intent_type,
        specialist=specialist,
        routing_confidence=routing_confidence,
        response_content=response_content,
        response_agent=response_agent,
        optimizer_triggered=optimizer_triggered,
        optimizer_issue=optimizer_issue,
        duration_ms=duration_ms,
        eval_status=eval_status,
        trace_id=trace_id,
        workflow_id=workflow_id,
        workflow_status=workflow_status,
        response_id=response_id,
        quality_scores=quality_scores,
        channel_metrics=channel_metrics,
    )
    add_result = session.add(record)
    if isawaitable(add_result):
        await add_result
    await session.flush()
    logger.info(
        "interaction_recorded",
        interaction_id=str(record.id),
        specialist=specialist,
        duration_ms=duration_ms,
    )
    return record


async def get_interaction_by_id(
    session: AsyncSession,
    interaction_id: uuid.UUID,
) -> InteractionRecord | None:
    """Get a single interaction record by ID."""
    return await session.get(InteractionRecord, interaction_id)


async def get_pending_interactions(
    session: AsyncSession,
    limit: int,
) -> list[InteractionRecord]:
    """Get interactions awaiting auto-judge scoring, oldest first."""
    stmt = (
        select(InteractionRecord)
        .where(InteractionRecord.eval_status == EvalStatus.PENDING)
        .order_by(InteractionRecord.created_at.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    scalars = await maybe_await(result.scalars())
    rows = await maybe_await(scalars.all())
    return list(rows)


async def update_auto_judge_scores(
    session: AsyncSession,
    interaction_id: uuid.UUID,
    *,
    score_relevance: float,
    score_actionability: float,
    score_tone: float,
    score_conciseness: float,
    reasoning: str,
    scored_at: datetime,
    specialist_summary: dict | None = None,
) -> None:
    """Update an interaction with auto-judge scores.

    ``specialist_summary`` is the per-dimension binary-check summary returned
    by ``summarize_specialist_dimensions``. When present it is stored under
    ``quality_scores["async_judge"]["specialist_dimensions"]`` so downstream
    tooling can see both the per-check booleans and the summed dimension
    scores without a schema change.
    """
    record = await session.get(InteractionRecord, interaction_id)
    if record is None:
        logger.warning("auto_judge_scores_missing_record", interaction_id=str(interaction_id))
        return

    record.eval_status = EvalStatus.AUTO_SCORED
    record.score_relevance = score_relevance
    record.score_actionability = score_actionability
    record.score_tone = score_tone
    record.score_conciseness = score_conciseness
    record.auto_judge_reasoning = reasoning
    record.scored_at = scored_at

    existing_quality = record.quality_scores or {}
    async_final = round(
        (score_relevance + score_actionability + score_tone + score_conciseness) / 4,
        3,
    )
    async_channel_style = round((score_tone + score_conciseness) / 2, 3)
    async_judge_payload: dict = {
        "relevance": score_relevance,
        "actionability": score_actionability,
        "tone": score_tone,
        "conciseness": score_conciseness,
        "reasoning": reasoning,
        "final_response_quality": async_final,
        "channel_style": async_channel_style,
        "scored_at": scored_at.isoformat(),
    }
    if specialist_summary:
        async_judge_payload["specialist_dimensions"] = specialist_summary

    record.quality_scores = {
        **existing_quality,
        "async_judge": async_judge_payload,
    }

    logger.info(
        "auto_judge_scores_updated",
        interaction_id=str(interaction_id),
        relevance=score_relevance,
        actionability=score_actionability,
        tone=score_tone,
        conciseness=score_conciseness,
        specialist_dims=list(specialist_summary.keys()) if specialist_summary else [],
    )


async def update_feedback(
    session: AsyncSession,
    interaction_id: uuid.UUID,
    *,
    rating: FeedbackRating,
    feedback_at: datetime,
) -> bool:
    """Record user feedback on an interaction. Returns True if the record was found."""
    stmt = (
        update(InteractionRecord)
        .where(InteractionRecord.id == interaction_id)
        .values(
            feedback_rating=rating,
            feedback_at=feedback_at,
        )
    )
    result = await session.execute(stmt)
    updated = affected_rows(result) > 0
    if updated:
        logger.info(
            "feedback_recorded",
            interaction_id=str(interaction_id),
            rating=rating,
        )
    return updated


async def update_channel_metrics(
    session: AsyncSession,
    interaction_id: uuid.UUID,
    *,
    channel_metrics: dict,
) -> bool:
    """Replace channel metrics for a recorded interaction."""
    stmt = (
        update(InteractionRecord)
        .where(InteractionRecord.id == interaction_id)
        .values(channel_metrics=channel_metrics)
    )
    result = await session.execute(stmt)
    updated = affected_rows(result) > 0
    if updated:
        logger.info(
            "interaction_channel_metrics_updated",
            interaction_id=str(interaction_id),
        )
    return updated


async def get_avg_scores_in_window(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    specialist: str | None = None,
) -> AverageScores:
    """Get average auto-judge scores within a time window.

    Returns dict with keys: relevance, actionability, tone, conciseness, count.
    All values are None if no scored interactions exist in the window.
    """
    stmt = select(
        func.avg(InteractionRecord.score_relevance).label("relevance"),
        func.avg(InteractionRecord.score_actionability).label("actionability"),
        func.avg(InteractionRecord.score_tone).label("tone"),
        func.avg(InteractionRecord.score_conciseness).label("conciseness"),
        func.count(InteractionRecord.id).label("count"),
    ).where(
        InteractionRecord.eval_status.in_([EvalStatus.AUTO_SCORED, EvalStatus.DEEP_SCORED]),
        InteractionRecord.created_at >= start,
        InteractionRecord.created_at <= end,
    )
    if specialist:
        stmt = stmt.where(InteractionRecord.specialist == specialist)

    result = await session.execute(stmt)
    row = result.one()
    return {
        "relevance": _aggregate_score(row, "relevance"),
        "actionability": _aggregate_score(row, "actionability"),
        "tone": _aggregate_score(row, "tone"),
        "conciseness": _aggregate_score(row, "conciseness"),
        "count": _aggregate_count(row),
    }


async def get_interactions_for_export(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    limit: int = 500,
) -> list[InteractionRecord]:
    """Get interaction records in a date range for export, newest first."""
    stmt = (
        select(InteractionRecord)
        .where(
            InteractionRecord.created_at >= start,
            InteractionRecord.created_at <= end,
        )
        .order_by(InteractionRecord.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_recent_interactions_for_user(
    session: AsyncSession,
    *,
    user_id: str,
    limit: int = 25,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[InteractionRecord]:
    """Get recent interaction records for one user, newest first."""
    stmt = (
        select(InteractionRecord)
        .where(InteractionRecord.user_id == user_id)
        .order_by(InteractionRecord.created_at.desc())
        .limit(limit)
    )
    if start is not None:
        stmt = stmt.where(InteractionRecord.created_at >= start)
    if end is not None:
        stmt = stmt.where(InteractionRecord.created_at < end)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_specialist_score_averages(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Get average scores grouped by specialist within a time window.

    Returns list of dicts with specialist name and average scores.
    Used by quality alerts to detect per-agent degradation.
    """
    stmt = (
        select(
            InteractionRecord.specialist,
            func.avg(InteractionRecord.score_relevance).label("avg_relevance"),
            func.avg(InteractionRecord.score_actionability).label("avg_actionability"),
            func.avg(InteractionRecord.score_tone).label("avg_tone"),
            func.avg(InteractionRecord.score_conciseness).label("avg_conciseness"),
            func.count(InteractionRecord.id).label("count"),
        )
        .where(
            InteractionRecord.eval_status.in_([EvalStatus.AUTO_SCORED, EvalStatus.DEEP_SCORED]),
            InteractionRecord.created_at >= start,
            InteractionRecord.created_at <= end,
        )
        .group_by(InteractionRecord.specialist)
    )
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.all()]
