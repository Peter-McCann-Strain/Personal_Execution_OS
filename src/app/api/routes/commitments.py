"""Commitments API routes -- tracking promises and follow-ups."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_principal, get_db
from src.app.api.transactions import session_transaction
from src.app.core.exceptions import NotFoundError
from src.app.domain.services.handlers._common import enqueue_reflection_pack_refresh
from src.app.persistence.repositories.commitments import (
    create_commitment as repo_create_commitment,
)
from src.app.persistence.repositories.commitments import (
    get_open_commitments as repo_get_open_commitments,
)
from src.app.persistence.repositories.commitments import (
    get_overdue_commitments as repo_get_overdue_commitments,
)
from src.app.persistence.repositories.commitments import (
    update_commitment_status as repo_update_commitment_status,
)

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class CommitmentDTO(BaseModel):
    id: str
    verbatim_text: str
    normalized_action: str
    who_committed: str
    who_to: str | None
    temporal_expression_raw: str | None
    temporal_normalized: str | None
    commitment_type: str
    confidence_score: float
    status: str
    created_at: str
    updated_at: str


class CreateCommitmentBody(BaseModel):
    verbatim_text: str
    normalized_action: str
    who_committed: str
    who_to: str | None = None
    temporal_expression: str | None = None
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)


class UpdateCommitmentStatusBody(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _commitment_to_dto(c) -> CommitmentDTO:
    return CommitmentDTO(
        id=str(c.id),
        verbatim_text=c.verbatim_text,
        normalized_action=c.normalized_action,
        who_committed=c.who_committed,
        who_to=c.who_to,
        temporal_expression_raw=c.temporal_expression_raw,
        temporal_normalized=c.temporal_normalized.isoformat() if c.temporal_normalized else None,
        commitment_type=c.commitment_type,
        confidence_score=c.confidence_score,
        status=c.status,
        created_at=c.created_at.isoformat(),
        updated_at=c.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/commitments", response_model=CommitmentDTO, status_code=201)
async def create_commitment(
    body: CreateCommitmentBody,
    session: AsyncSession = Depends(get_db),
) -> CommitmentDTO:
    """Create a new tracked commitment."""
    async with session_transaction(session):
        commitment = await repo_create_commitment(
            session,
            verbatim_text=body.verbatim_text,
            normalized_action=body.normalized_action,
            who_committed=body.who_committed,
            who_to=body.who_to,
            temporal_expression=body.temporal_expression,
            confidence_score=body.confidence_score,
        )
    await session.refresh(commitment)
    try:
        await enqueue_reflection_pack_refresh("commitment_created")
    except Exception:
        logger.warning(
            "commitment_reflection_pack_refresh_degraded",
            commitment_id=str(commitment.id),
            exc_info=True,
        )
    logger.info("commitment_created_via_api", commitment_id=str(commitment.id))
    return _commitment_to_dto(commitment)


@router.get("/commitments/overdue", response_model=list[CommitmentDTO])
async def get_overdue_commitments(
    session: AsyncSession = Depends(get_db),
) -> list[CommitmentDTO]:
    """Get commitments past their temporal deadline."""
    commitments = await repo_get_overdue_commitments(session)
    return [_commitment_to_dto(c) for c in commitments]


@router.get("/commitments/open", response_model=list[CommitmentDTO])
async def get_open_commitments(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
) -> list[CommitmentDTO]:
    """Get all open (non-completed) commitments."""
    commitments = await repo_get_open_commitments(session, limit=limit)
    return [_commitment_to_dto(c) for c in commitments]


@router.patch("/commitments/{commitment_id}/status", response_model=CommitmentDTO)
async def update_commitment_status(
    commitment_id: uuid.UUID,
    body: UpdateCommitmentStatusBody,
    session: AsyncSession = Depends(get_db),
) -> CommitmentDTO:
    """Update a commitment's status."""
    async with session_transaction(session):
        try:
            commitment = await repo_update_commitment_status(
                session,
                commitment_id=commitment_id,
                status=body.status,
            )
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc
    await session.refresh(commitment)
    try:
        await enqueue_reflection_pack_refresh("commitment_status_updated")
    except Exception:
        logger.warning(
            "commitment_reflection_pack_refresh_degraded",
            commitment_id=str(commitment.id),
            exc_info=True,
        )
    logger.info(
        "commitment_status_updated_via_api",
        commitment_id=str(commitment_id),
        status=body.status,
    )
    return _commitment_to_dto(commitment)
