"""Commitments repository -- tracking promises and follow-ups.

All functions require the caller to manage session.commit(). Use
``async with session.begin():`` for automatic transaction management.
"""

import uuid

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.domain.constants import (
    CLOSED_COMMITMENT_STATUSES,
    OPEN_COMMITMENT_STATUSES,
    CommitmentStatus,
)
from src.app.persistence.models import Commitment

logger = structlog.get_logger()


async def create_commitment(
    session: AsyncSession,
    verbatim_text: str,
    normalized_action: str,
    who_committed: str,
    who_to: str | None = None,
    temporal_expression: str | None = None,
    confidence_score: float = 1.0,
) -> Commitment:
    """Create a new tracked commitment. Returns the ORM model instance."""
    commitment = Commitment(
        verbatim_text=verbatim_text,
        normalized_action=normalized_action,
        who_committed=who_committed,
        who_to=who_to,
        temporal_expression_raw=temporal_expression,
        commitment_type="promise",
        confidence_score=confidence_score,
        status=CommitmentStatus.DETECTED,
    )
    session.add(commitment)
    await session.flush()
    logger.info("commitment_created", commitment_id=str(commitment.id))
    return commitment


async def get_overdue_commitments(session: AsyncSession) -> list[Commitment]:
    """Get commitments past their temporal deadline."""
    stmt = (
        select(Commitment)
        .where(
            Commitment.status.in_(OPEN_COMMITMENT_STATUSES),
            Commitment.temporal_normalized.is_not(None),
            Commitment.temporal_normalized < func.now(),
        )
        .order_by(Commitment.temporal_normalized.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_open_commitments(
    session: AsyncSession,
    limit: int = 20,
) -> list[Commitment]:
    """Get all open (non-completed) commitments."""
    stmt = (
        select(Commitment)
        .where(Commitment.status.not_in(CLOSED_COMMITMENT_STATUSES))
        .order_by(Commitment.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_commitment_status(
    session: AsyncSession,
    commitment_id: uuid.UUID,
    status: str,
) -> Commitment:
    """Update commitment status.

    Raises ValueError if the status is invalid or the commitment is not found.
    """
    valid = set(CommitmentStatus)
    if status not in valid:
        msg = f"Invalid commitment status: {status}"
        raise ValueError(msg)

    stmt = (
        update(Commitment)
        .where(Commitment.id == commitment_id)
        .values(status=status, updated_at=func.now())
        .returning(Commitment)
    )
    result = await session.execute(stmt)
    commitment = result.scalar_one_or_none()
    if commitment is None:
        msg = f"Commitment not found: {commitment_id}"
        raise ValueError(msg)
    return commitment
