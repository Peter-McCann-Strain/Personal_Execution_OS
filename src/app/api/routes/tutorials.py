"""Tutorial routes — Socratic tutorial lifecycle management."""

from __future__ import annotations

import uuid

import structlog
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_anthropic_client, get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.core.exceptions import NotFoundError
from src.app.domain.services.handlers.socratic import (
    end_tutorial,
    process_tutorial_turn,
    start_tutorial,
)
from src.app.persistence.models import TutorialSession
from src.app.persistence.repositories.tutorials import (
    get_past_tutorials,
    get_tutorial_session,
)

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class TutorialSummaryDTO(BaseModel):
    """Lightweight tutorial for list views."""

    id: str
    topic: str
    work_type: str
    phase: str
    turn_count: int | None = None
    bloom_start: str | None = None
    bloom_end: str | None = None
    speaking_ratio_student_pct: float | None = None
    knowledge_gaps_found: int | None = None
    knowledge_gaps_addressed: int | None = None
    created_at: str
    completed_at: str | None = None


class TutorialDetailDTO(TutorialSummaryDTO):
    """Full tutorial detail including analysis."""

    submitted_work: str
    propositions: list | None = None
    transcript: list | None = None
    analysis: dict | None = None


class TutorialStartResponse(BaseModel):
    """Response from starting a tutorial."""

    tutorial_id: str
    content: str
    phase: str
    speaker: str = "tutor"


class TutorialTurnRequest(BaseModel):
    """Request body for a tutorial turn."""

    message: str = Field(min_length=1)


class TutorialTurnResponse(BaseModel):
    """Response from a tutorial turn."""

    tutorial_id: str
    content: str
    phase: str
    speaker: str
    turn: int | None = None
    bloom_level: str | None = None
    analysis: dict | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_summary(t: TutorialSession) -> TutorialSummaryDTO:
    return TutorialSummaryDTO(
        id=str(t.id),
        topic=t.topic,
        work_type=t.work_type or "other",
        phase=t.phase or "submitted",
        turn_count=t.turn_count,
        bloom_start=t.bloom_start,
        bloom_end=t.bloom_end,
        speaking_ratio_student_pct=t.speaking_ratio_student_pct,
        knowledge_gaps_found=t.knowledge_gaps_found,
        knowledge_gaps_addressed=t.knowledge_gaps_addressed,
        created_at=t.created_at.isoformat() if t.created_at else "",
        completed_at=t.completed_at.isoformat() if t.completed_at else None,
    )


def _to_detail(t: TutorialSession) -> TutorialDetailDTO:
    return TutorialDetailDTO(
        id=str(t.id),
        topic=t.topic,
        work_type=t.work_type or "other",
        phase=t.phase or "submitted",
        turn_count=t.turn_count,
        bloom_start=t.bloom_start,
        bloom_end=t.bloom_end,
        speaking_ratio_student_pct=t.speaking_ratio_student_pct,
        knowledge_gaps_found=t.knowledge_gaps_found,
        knowledge_gaps_addressed=t.knowledge_gaps_addressed,
        created_at=t.created_at.isoformat() if t.created_at else "",
        completed_at=t.completed_at.isoformat() if t.completed_at else None,
        submitted_work=t.submitted_work,
        propositions=t.propositions,
        transcript=t.transcript,
        analysis=t.analysis,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/tutorials", response_model=PaginatedResponse[TutorialSummaryDTO])
async def list_tutorials(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[TutorialSummaryDTO]:
    """List completed tutorials for the authenticated user."""
    tutorials = await get_past_tutorials(db, user_id="owner", limit=limit)
    items = [_to_summary(t) for t in tutorials]
    return paginate(items=items, total=len(items), offset=offset, limit=limit)


@router.get("/tutorials/{tutorial_id}", response_model=TutorialDetailDTO)
async def get_tutorial(
    tutorial_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> TutorialDetailDTO:
    """Get full details of a single tutorial."""
    tutorial = await get_tutorial_session(db, tutorial_id)
    if tutorial is None:
        raise NotFoundError(f"Tutorial not found: {tutorial_id}")
    return _to_detail(tutorial)


@router.post(
    "/tutorials/{tutorial_id}/start",
    response_model=TutorialStartResponse,
)
async def start_tutorial_endpoint(
    tutorial_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    client: AsyncAnthropic = Depends(get_anthropic_client),
) -> TutorialStartResponse:
    """Start a prepared tutorial — returns the opening question."""
    response = await start_tutorial(tutorial_id, client, db)
    return TutorialStartResponse(
        tutorial_id=str(tutorial_id),
        content=response.content,
        phase=response.metadata.get("phase", "dialogue"),
        speaker=response.metadata.get("speaker", "tutor"),
    )


@router.post(
    "/tutorials/{tutorial_id}/turn",
    response_model=TutorialTurnResponse,
)
async def tutorial_turn_endpoint(
    tutorial_id: uuid.UUID,
    body: TutorialTurnRequest,
    db: AsyncSession = Depends(get_db),
    client: AsyncAnthropic = Depends(get_anthropic_client),
) -> TutorialTurnResponse:
    """Send a message during an active tutorial."""
    response = await process_tutorial_turn(tutorial_id, body.message, client, db)
    meta = response.metadata
    return TutorialTurnResponse(
        tutorial_id=str(tutorial_id),
        content=response.content,
        phase=meta.get("phase", "dialogue"),
        speaker=meta.get("speaker", "tutor"),
        turn=meta.get("turn"),
        bloom_level=meta.get("bloom_level"),
        analysis=meta.get("analysis"),
    )


@router.post(
    "/tutorials/{tutorial_id}/end",
    response_model=TutorialTurnResponse,
)
async def end_tutorial_endpoint(
    tutorial_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    client: AsyncAnthropic = Depends(get_anthropic_client),
) -> TutorialTurnResponse:
    """End a tutorial early and receive the analysis report."""
    response = await end_tutorial(tutorial_id, client, db)
    meta = response.metadata
    return TutorialTurnResponse(
        tutorial_id=str(tutorial_id),
        content=response.content,
        phase=meta.get("phase", "complete"),
        speaker="tutor",
        analysis=meta.get("analysis"),
    )
