"""Contacts / CRM endpoints — CRUD contacts and log interactions."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.api.transactions import session_transaction
from src.app.api.utils import format_datetime, paginated_count
from src.app.core.exceptions import NotFoundError
from src.app.persistence.models import Contact, Interaction
from src.app.persistence.repositories.contacts import (
    calculate_relationship_decay,
)
from src.app.persistence.repositories.contacts import (
    create_contact as repo_create_contact,
)
from src.app.persistence.repositories.contacts import (
    get_contact_by_id as repo_get_contact_by_id,
)
from src.app.persistence.repositories.contacts import (
    get_decaying_relationships as repo_get_decaying_relationships,
)
from src.app.persistence.repositories.contacts import (
    log_interaction as repo_log_interaction,
)
from src.app.persistence.repositories.contacts import (
    search_contacts as repo_search_contacts,
)

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ContactDTO(BaseModel):
    id: str
    first_name: str
    last_name: str | None
    email: str | None
    tags: list[str]
    how_we_met: str | None
    interaction_frequency_days: int | None
    relationship_score: float
    relationship_health: float | None
    last_interaction_at: str | None
    created_at: str
    updated_at: str


class ContactSearchResultDTO(BaseModel):
    id: str
    first_name: str
    last_name: str | None
    email: str | None
    tags: list[str]
    relationship_score: float


class InteractionDTO(BaseModel):
    id: str
    contact_id: str
    interaction_type: str
    direction: str
    channel: str
    summary: str
    topics: list[str]
    interaction_at: str
    created_at: str


_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


class CreateContactBody(BaseModel):
    first_name: str
    last_name: str | None = None
    email: str | None = None
    tags: list[str] | None = None
    how_we_met: str | None = None
    interaction_frequency_days: int | None = None

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str | None) -> str | None:
        if v is not None and not _EMAIL_RE.match(v):
            raise ValueError(f"Invalid email format: {v!r}")
        return v


class LogInteractionBody(BaseModel):
    interaction_type: str
    direction: str
    channel: str = "manual"
    summary: str
    topics: list[str] | None = None
    interaction_at: datetime | None = None

    @field_validator("interaction_at")
    @classmethod
    def require_aware_interaction_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("interaction_at must include a timezone")
        return value.astimezone(UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Keep module-level alias so existing test imports continue to work.
_fmt_dt = format_datetime


def _contact_to_dto(c: Contact) -> ContactDTO:
    health = calculate_relationship_decay(
        last_interaction=c.last_interaction_at,
        expected_frequency_days=c.interaction_frequency_days,
        base_score=c.relationship_score,
    )
    return ContactDTO(
        id=str(c.id),
        first_name=c.first_name,
        last_name=c.last_name,
        email=c.email,
        tags=c.tags or [],
        how_we_met=c.how_we_met,
        interaction_frequency_days=c.interaction_frequency_days,
        relationship_score=c.relationship_score,
        relationship_health=health,
        last_interaction_at=_fmt_dt(c.last_interaction_at),
        created_at=c.created_at.isoformat(),
        updated_at=c.updated_at.isoformat(),
    )


def _interaction_to_dto(i: Interaction) -> InteractionDTO:
    return InteractionDTO(
        id=str(i.id),
        contact_id=str(i.contact_id),
        interaction_type=i.interaction_type,
        direction=i.direction,
        channel=i.channel,
        summary=i.summary or "",
        topics=i.topics or [],
        interaction_at=_fmt_dt(i.interaction_at) or "",
        created_at=i.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/contacts/search", response_model=list[ContactSearchResultDTO])
async def search_contacts_endpoint(
    session: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=1, description="Search query for contacts by name"),
    limit: int = Query(10, ge=1, le=50),
) -> list[ContactSearchResultDTO]:
    """Search contacts by name using trigram similarity (pg_trgm)."""
    rows = await repo_search_contacts(session, query=q, limit=limit)
    return [
        ContactSearchResultDTO(
            id=str(row["id"]),
            first_name=row["first_name"],
            last_name=row.get("last_name"),
            email=row.get("email"),
            tags=row.get("tags") or [],
            relationship_score=float(row.get("relationship_score", 0)),
        )
        for row in rows
    ]


@router.get("/contacts/decaying", response_model=list[ContactDTO])
async def decaying_relationships(
    session: AsyncSession = Depends(get_db),
    threshold: float = Query(30.0, description="Score threshold for decay detection"),
    limit: int = Query(10, ge=1, le=50),
) -> list[ContactDTO]:
    """Get contacts with decaying relationship scores below threshold."""
    contacts = await repo_get_decaying_relationships(
        session,
        threshold=threshold,
        limit=limit,
    )
    return [_contact_to_dto(c) for c in contacts]


@router.get("/contacts", response_model=PaginatedResponse[ContactDTO])
async def list_contacts(
    session: AsyncSession = Depends(get_db),
    tags: str | None = Query(None, description="Comma-separated tags to filter by"),
    score_min: float | None = Query(None),
    score_max: float | None = Query(None),
    sort: str = Query("score_desc"),
    search: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[ContactDTO]:
    """List contacts with filtering, sorting, and pagination."""
    query = select(Contact).where(Contact.deleted_at.is_(None))

    # --- Filters ---
    if search:
        pattern = f"%{search}%"
        query = query.where(Contact.first_name.ilike(pattern) | Contact.last_name.ilike(pattern))

    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            query = query.where(Contact.tags.overlap(tag_list))

    if score_min is not None:
        query = query.where(Contact.relationship_score >= score_min)
    if score_max is not None:
        query = query.where(Contact.relationship_score <= score_max)

    # --- Sorting ---
    sort_map = {
        "score_asc": Contact.relationship_score.asc(),
        "score_desc": Contact.relationship_score.desc(),
        "last_interaction": Contact.last_interaction_at.desc().nullslast(),
        "name": Contact.first_name.asc(),
    }
    order_clause = sort_map.get(sort, Contact.relationship_score.desc())
    query = query.order_by(order_clause)

    # --- Count ---
    total = await paginated_count(session, query)

    # --- Paginate ---
    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    contacts = list(result.scalars().all())

    items = [_contact_to_dto(c) for c in contacts]
    return paginate(items=items, total=total, offset=offset, limit=limit)


@router.get("/contacts/{contact_id}", response_model=ContactDTO)
async def get_contact(
    contact_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> ContactDTO:
    """Get a single contact by ID."""
    contact = await repo_get_contact_by_id(session, contact_id)
    if contact is None:
        raise NotFoundError(f"Contact {contact_id} not found")
    return _contact_to_dto(contact)


@router.post("/contacts", response_model=ContactDTO, status_code=201)
async def create_contact(
    body: CreateContactBody,
    session: AsyncSession = Depends(get_db),
) -> ContactDTO:
    """Create a new contact."""
    async with session_transaction(session):
        contact = await repo_create_contact(
            session=session,
            first_name=body.first_name,
            last_name=body.last_name,
            email=body.email,
            tags=body.tags,
            how_we_met=body.how_we_met,
            interaction_frequency_days=body.interaction_frequency_days,
        )
    await session.refresh(contact)
    logger.info("contact_created_via_api", contact_id=str(contact.id))
    return _contact_to_dto(contact)


@router.get(
    "/contacts/{contact_id}/interactions",
    response_model=list[InteractionDTO],
)
async def list_contact_interactions(
    contact_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> list[InteractionDTO]:
    """List all interactions for a contact, newest first."""
    # Verify contact exists
    contact = await repo_get_contact_by_id(session, contact_id)
    if contact is None:
        raise NotFoundError(f"Contact {contact_id} not found")

    query = (
        select(Interaction)
        .where(Interaction.contact_id == contact_id)
        .order_by(Interaction.interaction_at.desc())
    )
    result = await session.execute(query)
    interactions = list(result.scalars().all())
    return [_interaction_to_dto(i) for i in interactions]


@router.post(
    "/contacts/{contact_id}/interactions",
    response_model=InteractionDTO,
    status_code=201,
)
async def log_interaction(
    contact_id: uuid.UUID,
    body: LogInteractionBody,
    session: AsyncSession = Depends(get_db),
) -> InteractionDTO:
    """Log a new interaction with a contact."""
    # Verify contact exists
    contact = await repo_get_contact_by_id(session, contact_id)
    if contact is None:
        raise NotFoundError(f"Contact {contact_id} not found")

    async with session_transaction(session):
        interaction = await repo_log_interaction(
            session=session,
            contact_id=contact_id,
            interaction_type=body.interaction_type,
            summary=body.summary,
            channel=body.channel,
            direction=body.direction,
            topics=body.topics,
            interaction_at=body.interaction_at,
        )
    await session.refresh(interaction)
    logger.info(
        "interaction_logged_via_api",
        contact_id=str(contact_id),
        interaction_id=str(interaction.id),
    )
    return _interaction_to_dto(interaction)
