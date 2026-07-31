"""Tutorial session repository — CRUD for Socratic tutorial sessions.

All functions require the caller to manage session.commit().
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.jsonb_schemas import (
    AssessorLogEntry,
    DialogueTurnRecord,
    TutorialAnalysisRecord,
)
from src.app.persistence.models import TutorialSession

logger = structlog.get_logger()


async def create_tutorial_session(
    session: AsyncSession,
    *,
    user_id: str,
    topic: str,
    submitted_work: str,
    work_type: str = "other",
) -> TutorialSession:
    """Create a new tutorial session."""
    tutorial = TutorialSession(
        user_id=user_id,
        topic=topic,
        submitted_work=submitted_work,
        work_type=work_type,
        phase="submitted",
    )
    session.add(tutorial)
    await session.flush()
    logger.info(
        "tutorial_session_created",
        session_id=str(tutorial.id),
        topic=topic,
        work_type=work_type,
    )
    return tutorial


async def get_tutorial_session(
    session: AsyncSession,
    tutorial_id: uuid.UUID,
) -> TutorialSession | None:
    """Get a tutorial session by ID."""
    return await session.get(TutorialSession, tutorial_id)


async def get_active_tutorial(
    session: AsyncSession,
    user_id: str,
) -> TutorialSession | None:
    """Get the user's active (non-complete) tutorial session, if any."""
    stmt = (
        select(TutorialSession)
        .where(
            TutorialSession.user_id == user_id,
            TutorialSession.phase.notin_(["complete"]),
        )
        .order_by(TutorialSession.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_tutorial_phase(
    session: AsyncSession,
    tutorial_id: uuid.UUID,
    phase: str,
) -> None:
    """Update the phase of a tutorial session."""
    stmt = update(TutorialSession).where(TutorialSession.id == tutorial_id).values(phase=phase)
    await session.execute(stmt)


async def store_preparation(
    session: AsyncSession,
    tutorial_id: uuid.UUID,
    *,
    propositions: list[dict[str, Any]],
    preparation: dict[str, Any],
) -> None:
    """Store preparation results in the tutorial session."""
    stmt = (
        update(TutorialSession)
        .where(TutorialSession.id == tutorial_id)
        .values(
            propositions=propositions,
            preparation=preparation,
            phase="ready",
        )
    )
    await session.execute(stmt)


async def store_tutorial_results(
    session: AsyncSession,
    tutorial_id: uuid.UUID,
    *,
    transcript: list[dict[str, Any]],
    assessor_log: list[dict[str, Any]],
    analysis: dict[str, Any],
    turn_count: int,
    speaking_ratio_student_pct: float | None = None,
    bloom_start: str | None = None,
    bloom_end: str | None = None,
    knowledge_gaps_found: int | None = None,
    knowledge_gaps_addressed: int | None = None,
) -> None:
    """Store completed tutorial results and analysis."""
    # --- Validate JSONB payloads before writing ---
    _failed_turn_idx = -1
    try:
        for _failed_turn_idx, turn in enumerate(transcript):
            DialogueTurnRecord.model_validate(turn)
    except ValidationError:
        logger.warning(
            "tutorial_transcript_validation_failed",
            session_id=str(tutorial_id),
            turn_index=_failed_turn_idx,
            exc_info=True,
        )

    _failed_entry_idx = -1
    try:
        for _failed_entry_idx, entry in enumerate(assessor_log):
            AssessorLogEntry.model_validate(entry)
    except ValidationError:
        logger.warning(
            "tutorial_assessor_log_validation_failed",
            session_id=str(tutorial_id),
            entry_index=_failed_entry_idx,
            exc_info=True,
        )

    try:
        TutorialAnalysisRecord.model_validate(analysis)
    except ValidationError:
        logger.warning(
            "tutorial_analysis_validation_failed",
            session_id=str(tutorial_id),
            exc_info=True,
        )

    stmt = (
        update(TutorialSession)
        .where(TutorialSession.id == tutorial_id)
        .values(
            transcript=transcript,
            assessor_log=assessor_log,
            analysis=analysis,
            turn_count=turn_count,
            speaking_ratio_student_pct=speaking_ratio_student_pct,
            bloom_start=bloom_start,
            bloom_end=bloom_end,
            knowledge_gaps_found=knowledge_gaps_found,
            knowledge_gaps_addressed=knowledge_gaps_addressed,
            phase="complete",
            completed_at=datetime.now(UTC),
        )
    )
    await session.execute(stmt)
    logger.info(
        "tutorial_results_stored",
        session_id=str(tutorial_id),
        turn_count=turn_count,
        gaps_found=knowledge_gaps_found,
    )


async def get_past_tutorials(
    session: AsyncSession,
    user_id: str,
    limit: int = 10,
) -> list[TutorialSession]:
    """Get past completed tutorials for a user."""
    stmt = (
        select(TutorialSession)
        .where(
            TutorialSession.user_id == user_id,
            TutorialSession.phase == "complete",
        )
        .order_by(TutorialSession.completed_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
