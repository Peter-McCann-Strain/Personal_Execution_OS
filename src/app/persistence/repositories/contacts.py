"""Contacts repository -- CRM with relationship health scoring.

All functions require the caller to manage session.commit(). Use
``async with session.begin():`` for automatic transaction management.
"""

import math
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import Contact, Interaction

logger = structlog.get_logger()


async def create_contact(
    session: AsyncSession,
    first_name: str,
    last_name: str | None = None,
    email: str | None = None,
    tags: list[str] | None = None,
    how_we_met: str | None = None,
    interaction_frequency_days: int | None = None,
) -> Contact:
    """Create a new contact. Returns the ORM model instance."""
    contact = Contact(
        first_name=first_name,
        last_name=last_name,
        email=email,
        tags=tags,
        how_we_met=how_we_met,
        interaction_frequency_days=interaction_frequency_days,
        relationship_score=50.0,
    )
    session.add(contact)
    await session.flush()
    logger.info("contact_created", contact_id=str(contact.id))
    return contact


async def get_contact_by_id(
    session: AsyncSession,
    contact_id: uuid.UUID,
) -> Contact | None:
    """Get a single contact by ID, or None if not found."""
    result = await session.execute(
        select(Contact).where(Contact.id == contact_id, Contact.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def log_interaction(
    session: AsyncSession,
    contact_id: uuid.UUID,
    interaction_type: str,
    summary: str,
    channel: str = "manual",
    direction: str = "outgoing",
    topics: list[str] | None = None,
    interaction_at: datetime | None = None,
) -> Interaction:
    """Log an interaction with a contact. Returns the ORM model instance."""
    occurred_at = interaction_at or datetime.now(UTC)
    interaction = Interaction(
        contact_id=contact_id,
        interaction_type=interaction_type,
        direction=direction,
        channel=channel,
        summary=summary,
        topics=topics,
        interaction_at=occurred_at,
    )
    session.add(interaction)
    await session.flush()

    # Update last interaction timestamp on the contact
    await session.execute(
        update(Contact)
        .where(Contact.id == contact_id)
        .values(
            last_interaction_at=occurred_at,
            updated_at=func.now(),
        )
    )
    return interaction


def calculate_relationship_decay(
    last_interaction: datetime | None,
    expected_frequency_days: int | None,
    base_score: float = 50.0,
) -> float:
    """Calculate relationship health score based on interaction frequency.

    Score decays exponentially: score = base * exp(-days_overdue / expected)
    """
    if last_interaction is None or expected_frequency_days is None:
        return base_score

    days_since = (datetime.now(UTC) - last_interaction).days
    if days_since <= expected_frequency_days:
        return base_score  # Still within expected frequency

    days_overdue = days_since - expected_frequency_days
    decay_factor = math.exp(-days_overdue / expected_frequency_days)
    return round(base_score * decay_factor, 1)


async def get_decaying_relationships(
    session: AsyncSession,
    threshold: float = 30.0,
    limit: int = 10,
) -> list[Contact]:
    """Find contacts whose relationship score has decayed below threshold."""
    stmt = (
        select(Contact)
        .where(
            Contact.deleted_at.is_(None),
            Contact.relationship_score < threshold,
            Contact.interaction_frequency_days.is_not(None),
        )
        .order_by(Contact.relationship_score.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def search_contacts(
    session: AsyncSession,
    query: str,
    limit: int = 10,
) -> list[dict]:
    """Search contacts by name using trigram similarity.

    Uses the pg_trgm ``similarity()`` function which requires the
    pg_trgm extension. Returns dicts because the result includes the
    computed similarity column.
    """
    result = await session.execute(
        text("""
            SELECT id, first_name, last_name, email, tags, relationship_score
            FROM contacts
            WHERE deleted_at IS NULL
              AND similarity(first_name || ' ' || COALESCE(last_name, ''), :query) > 0.2
            ORDER BY similarity(first_name || ' ' || COALESCE(last_name, ''), :query) DESC
            LIMIT :limit
        """),
        {"query": query, "limit": limit},
    )
    return [dict(row) for row in result.mappings().all()]
