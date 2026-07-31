"""Decisions repository -- decision journal CRUD.

All functions require the caller to manage session.commit(). Use
``async with session.begin():`` for automatic transaction management.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import Decision

logger = structlog.get_logger()


async def create_decision(
    session: AsyncSession,
    title: str,
    decision_made: str,
    context: str | None = None,
    options_considered: list[str] | None = None,
    reasoning: str | None = None,
    expected_outcome: str | None = None,
    tags: list[str] | None = None,
    review_date: datetime | None = None,
) -> Decision:
    """Create a new decision journal entry. Returns the ORM model instance."""
    decision = Decision(
        title=title,
        decision_made=decision_made,
        context=context,
        options_considered=options_considered,
        reasoning=reasoning,
        expected_outcome=expected_outcome,
        tags=tags,
        review_date=review_date,
        status="pending_review",
    )
    session.add(decision)
    await session.flush()
    logger.info("decision_created", decision_id=str(decision.id))
    return decision


async def get_decisions(
    session: AsyncSession,
    status: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[Decision], int]:
    """List decisions with optional status filter and pagination.

    Returns (decisions, total_count).
    """
    query = select(Decision)

    if status:
        query = query.where(Decision.status == status)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar_one()

    # Fetch page
    query = query.order_by(Decision.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    decisions = list(result.scalars().all())

    return decisions, total


async def get_decision_by_id(
    session: AsyncSession,
    decision_id: uuid.UUID,
) -> Decision | None:
    """Get a single decision by ID, or None if not found."""
    return await session.get(Decision, decision_id)


async def update_decision_outcome(
    session: AsyncSession,
    decision_id: uuid.UUID,
    actual_outcome: str,
    outcome_rating: float | None = None,
) -> Decision | None:
    """Record the actual outcome and optional rating for a decision.

    Sets status to 'reviewed'. Returns the updated Decision or None if not found.
    """
    decision = await session.get(Decision, decision_id)
    if decision is None:
        return None

    await session.execute(
        update(Decision)
        .where(Decision.id == decision_id)
        .values(
            actual_outcome=actual_outcome,
            outcome_rating=outcome_rating,
            status="reviewed",
        )
    )
    await session.flush()

    # Refresh to get updated values
    await session.refresh(decision)
    logger.info(
        "decision_outcome_recorded",
        decision_id=str(decision_id),
        outcome_rating=outcome_rating,
    )
    return decision


async def get_decisions_due_for_review(
    session: AsyncSession,
) -> list[Decision]:
    """Return decisions where review_date <= now and status = pending_review."""
    now = datetime.now(tz=UTC)
    query = (
        select(Decision)
        .where(
            Decision.status == "pending_review",
            Decision.review_date.is_not(None),
            Decision.review_date <= now,
        )
        .order_by(Decision.review_date.asc())
    )
    result = await session.execute(query)
    return list(result.scalars().all())
