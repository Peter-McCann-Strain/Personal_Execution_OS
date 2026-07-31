"""Reviews API routes — paginated listing, detail, and generation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.core.exceptions import NotFoundError
from src.app.domain.constants import OPEN_COMMITMENT_STATUSES, GoalStatus
from src.app.persistence.jsonb_schemas import ReviewContent
from src.app.persistence.models import Commitment, Episode, Goal, Review

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class GoalProgressItem(BaseModel):
    title: str
    progress: float
    status: str


class OpenCommitmentItem(BaseModel):
    action: str
    status: str


class ReviewDTO(BaseModel):
    """Review DTO matching frontend WeeklyReview type."""

    id: str
    period: str
    accomplishments: list[str]
    mood_summary: str | None
    average_mood: float | None
    goal_progress: list[GoalProgressItem]
    open_commitments: list[OpenCommitmentItem]
    relationship_alerts: list[str]
    patterns_noticed: list[str]
    recommendations: list[str]
    key_insight: str | None
    created_at: str


class GenerateReviewBody(BaseModel):
    """Body for POST /reviews/generate."""

    type: Literal["weekly", "quarterly"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _review_to_dto(review: Review) -> ReviewDTO:
    """Convert an ORM Review to a ReviewDTO.

    The Review model stores structured data in a JSONB ``content`` column.
    We extract individual fields from there, falling back to sensible defaults.
    """
    content: dict = review.content or {}

    return ReviewDTO(
        id=str(review.id),
        period=review.period,
        accomplishments=content.get("accomplishments", []),
        mood_summary=content.get("mood_summary"),
        average_mood=content.get("average_mood"),
        goal_progress=[GoalProgressItem(**gp) for gp in content.get("goal_progress", [])],
        open_commitments=[OpenCommitmentItem(**oc) for oc in content.get("open_commitments", [])],
        relationship_alerts=content.get("relationship_alerts", []),
        patterns_noticed=content.get("patterns_noticed", []),
        recommendations=content.get("recommendations", []),
        key_insight=content.get("key_insight"),
        created_at=review.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/reviews", response_model=PaginatedResponse[ReviewDTO])
async def list_reviews(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    review_type: Literal["weekly", "quarterly"] | None = Query(None),
    sort: Literal["created_at", "period"] = Query("created_at"),
    order: Literal["asc", "desc"] = Query("desc"),
) -> PaginatedResponse[ReviewDTO]:
    """Paginated reviews list with optional type filter and sorting."""
    stmt = select(Review)

    if review_type is not None:
        stmt = stmt.where(Review.review_type == review_type)

    # Count total before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    # Sorting
    sort_column = getattr(Review, sort)
    if order == "desc":
        stmt = stmt.order_by(sort_column.desc().nulls_last())
    else:
        stmt = stmt.order_by(sort_column.asc().nulls_last())

    # Pagination
    stmt = stmt.offset(offset).limit(limit)

    result = await session.execute(stmt)
    reviews = list(result.scalars().all())

    items = [_review_to_dto(r) for r in reviews]
    return paginate(items=items, total=total, offset=offset, limit=limit)


@router.get("/reviews/{review_id}", response_model=ReviewDTO)
async def get_review(
    review_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> ReviewDTO:
    """Get a single review by ID."""
    review = await session.get(Review, review_id)
    if review is None:
        raise NotFoundError(f"Review not found: {review_id}")
    return _review_to_dto(review)


@router.post("/reviews/generate", response_model=ReviewDTO, status_code=201)
async def generate_review(
    body: GenerateReviewBody,
    session: AsyncSession = Depends(get_db),
) -> ReviewDTO:
    """Generate a new review by collecting recent data.

    Collects episodes, goals, and commitments for the relevant period, then
    assembles a review record. In a future iteration this will invoke the
    Review specialist agent for AI-powered analysis.
    """
    now = datetime.now(UTC)

    if body.type == "weekly":
        period_start = now - timedelta(days=7)
        period_label = f"{period_start.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}"
    else:
        period_start = now - timedelta(days=90)
        period_label = f"{period_start.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}"

    # --- Collect episodes for the period ---
    episodes_result = await session.execute(
        select(Episode)
        .where(Episode.created_at >= period_start)
        .order_by(Episode.created_at.desc())
    )
    episodes = list(episodes_result.scalars().all())

    # Extract accomplishments from episode summaries
    accomplishments: list[str] = []
    for ep in episodes:
        if ep.summary:
            accomplishments.append(ep.summary)
    # Cap to a reasonable number
    accomplishments = accomplishments[:20]

    # --- Mood analysis ---
    mood_scores = [ep.mood_score for ep in episodes if ep.mood_score is not None]
    average_mood = round(sum(mood_scores) / len(mood_scores), 2) if mood_scores else None
    mood_summary: str | None = None
    if average_mood is not None:
        if average_mood >= 7:
            mood_summary = "Generally positive mood this period."
        elif average_mood >= 4:
            mood_summary = "Mixed mood this period, some ups and downs."
        else:
            mood_summary = "Mood has been lower than usual this period."

    # --- Goal progress ---
    goals_result = await session.execute(select(Goal).where(Goal.status == GoalStatus.ACTIVE))
    goals = list(goals_result.scalars().all())
    goal_progress = [
        {
            "title": g.title,
            "progress": g.progress,
            "status": g.status,
        }
        for g in goals
    ]

    # --- Open commitments ---
    commitments_result = await session.execute(
        select(Commitment).where(Commitment.status.in_(OPEN_COMMITMENT_STATUSES))
    )
    commitments = list(commitments_result.scalars().all())
    open_commitments = [
        {
            "action": c.normalized_action,
            "status": c.status,
        }
        for c in commitments
    ]

    # --- Assemble content JSONB ---
    content = {
        "accomplishments": accomplishments,
        "mood_summary": mood_summary,
        "average_mood": average_mood,
        "goal_progress": goal_progress,
        "open_commitments": open_commitments,
        "relationship_alerts": [],
        "patterns_noticed": [],
        "recommendations": [],
        "key_insight": None,
    }

    # Validate content against the JSONB schema before persisting
    ReviewContent.model_validate(content)

    # --- Persist review ---
    review = Review(
        review_type=body.type,
        period=period_label,
        content=content,
    )
    session.add(review)
    await session.flush()
    await session.commit()

    logger.info(
        "review_generated",
        review_id=str(review.id),
        review_type=body.type,
        period=period_label,
        episode_count=len(episodes),
        goal_count=len(goals),
    )

    return _review_to_dto(review)
