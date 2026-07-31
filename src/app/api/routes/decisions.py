"""Decision journal endpoints — CRUD decisions and record outcomes."""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.api.transactions import session_transaction
from src.app.api.utils import format_datetime
from src.app.core.exceptions import NotFoundError
from src.app.persistence.repositories.decisions import (
    create_decision as repo_create_decision,
)
from src.app.persistence.repositories.decisions import (
    get_decision_by_id as repo_get_decision_by_id,
)
from src.app.persistence.repositories.decisions import (
    get_decisions as repo_get_decisions,
)
from src.app.persistence.repositories.decisions import (
    get_decisions_due_for_review as repo_get_decisions_due_for_review,
)
from src.app.persistence.repositories.decisions import (
    update_decision_outcome as repo_update_decision_outcome,
)

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class DecisionDTO(BaseModel):
    id: str
    title: str
    context: str | None
    options_considered: list[str]
    decision_made: str
    reasoning: str | None
    expected_outcome: str | None
    actual_outcome: str | None
    outcome_rating: float | None
    tags: list[str]
    review_date: str | None
    status: str
    created_at: str
    updated_at: str


class CreateDecisionBody(BaseModel):
    title: str
    decision_made: str
    context: str | None = None
    options_considered: list[str] | None = None
    reasoning: str | None = None
    expected_outcome: str | None = None
    tags: list[str] | None = None
    review_date: str | None = None

    @field_validator("review_date")
    @classmethod
    def validate_review_date(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                datetime.fromisoformat(v)
            except (ValueError, TypeError) as e:
                msg = f"Invalid ISO 8601 datetime: {v!r}"
                raise ValueError(msg) from e
        return v


class UpdateOutcomeBody(BaseModel):
    actual_outcome: str
    outcome_rating: float | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Keep module-level alias so any existing imports continue to work.
_fmt_dt = format_datetime


def _decision_to_dto(d) -> DecisionDTO:
    return DecisionDTO(
        id=str(d.id),
        title=d.title,
        context=d.context,
        options_considered=d.options_considered or [],
        decision_made=d.decision_made,
        reasoning=d.reasoning,
        expected_outcome=d.expected_outcome,
        actual_outcome=d.actual_outcome,
        outcome_rating=d.outcome_rating,
        tags=d.tags or [],
        review_date=_fmt_dt(d.review_date),
        status=d.status,
        created_at=d.created_at.isoformat(),
        updated_at=d.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/decisions/due-review", response_model=list[DecisionDTO])
async def list_decisions_due_review(
    session: AsyncSession = Depends(get_db),
) -> list[DecisionDTO]:
    """List decisions that are past their review date and still pending review."""
    decisions = await repo_get_decisions_due_for_review(session)
    return [_decision_to_dto(d) for d in decisions]


@router.get("/decisions", response_model=PaginatedResponse[DecisionDTO])
async def list_decisions(
    session: AsyncSession = Depends(get_db),
    status: str | None = Query(
        None, description="Filter by status: pending_review, reviewed, archived"
    ),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[DecisionDTO]:
    """List decisions with optional status filter and pagination."""
    decisions, total = await repo_get_decisions(session, status=status, limit=limit, offset=offset)
    items = [_decision_to_dto(d) for d in decisions]
    return paginate(items=items, total=total, offset=offset, limit=limit)


@router.get("/decisions/{decision_id}", response_model=DecisionDTO)
async def get_decision(
    decision_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> DecisionDTO:
    """Get a single decision by ID."""
    decision = await repo_get_decision_by_id(session, decision_id)
    if decision is None:
        raise NotFoundError(f"Decision {decision_id} not found")
    return _decision_to_dto(decision)


@router.post("/decisions", response_model=DecisionDTO, status_code=201)
async def create_decision(
    body: CreateDecisionBody,
    session: AsyncSession = Depends(get_db),
) -> DecisionDTO:
    """Create a new decision journal entry."""
    # Parse review_date if provided
    review_date: datetime | None = None
    if body.review_date:
        review_date = datetime.fromisoformat(body.review_date)

    async with session_transaction(session):
        decision = await repo_create_decision(
            session=session,
            title=body.title,
            decision_made=body.decision_made,
            context=body.context,
            options_considered=body.options_considered,
            reasoning=body.reasoning,
            expected_outcome=body.expected_outcome,
            tags=body.tags,
            review_date=review_date,
        )
    await session.refresh(decision)
    logger.info("decision_created_via_api", decision_id=str(decision.id))
    return _decision_to_dto(decision)


@router.patch("/decisions/{decision_id}/outcome", response_model=DecisionDTO)
async def record_outcome(
    decision_id: uuid.UUID,
    body: UpdateOutcomeBody,
    session: AsyncSession = Depends(get_db),
) -> DecisionDTO:
    """Record the actual outcome and optional rating for a decision."""
    async with session_transaction(session):
        decision = await repo_update_decision_outcome(
            session=session,
            decision_id=decision_id,
            actual_outcome=body.actual_outcome,
            outcome_rating=body.outcome_rating,
        )
    if decision is None:
        raise NotFoundError(f"Decision {decision_id} not found")
    await session.refresh(decision)
    logger.info(
        "decision_outcome_recorded_via_api",
        decision_id=str(decision_id),
        outcome_rating=body.outcome_rating,
    )
    return _decision_to_dto(decision)
