"""Tests for the contacts repository — CRM with relationship decay."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.persistence.models import Contact, Interaction
from src.app.persistence.repositories.contacts import (
    calculate_relationship_decay,
    create_contact,
    get_contact_by_id,
    get_decaying_relationships,
    log_interaction,
    search_contacts,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _make_contact(**overrides) -> Contact:
    """Create a test Contact ORM object."""
    c = Contact()
    c.id = overrides.get("id", uuid.uuid4())
    c.first_name = overrides.get("first_name", "Alice")
    c.last_name = overrides.get("last_name", "Smith")
    c.email = overrides.get("email", "alice@example.com")
    c.tags = overrides.get("tags", ["friend"])
    c.how_we_met = overrides.get("how_we_met", "University")
    c.interaction_frequency_days = overrides.get("interaction_frequency_days", 14)
    c.relationship_score = overrides.get("relationship_score", 50.0)
    c.last_interaction_at = overrides.get("last_interaction_at")
    c.created_at = overrides.get("created_at", datetime.now(UTC))
    c.updated_at = overrides.get("updated_at", datetime.now(UTC))
    return c


# ---------------------------------------------------------------------------
# create_contact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_contact_adds_and_flushes():
    """create_contact should call session.add() and session.flush()."""
    session = _make_session()

    result = await create_contact(session, first_name="Bob")

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert isinstance(result, Contact)


@pytest.mark.asyncio
async def test_create_contact_sets_all_fields():
    """create_contact should set all provided fields on the Contact."""
    session = _make_session()

    result = await create_contact(
        session,
        first_name="Charlie",
        last_name="Brown",
        email="charlie@example.com",
        tags=["colleague", "engineering"],
        how_we_met="Conference 2025",
        interaction_frequency_days=7,
    )

    assert result.first_name == "Charlie"
    assert result.last_name == "Brown"
    assert result.email == "charlie@example.com"
    assert result.tags == ["colleague", "engineering"]
    assert result.how_we_met == "Conference 2025"
    assert result.interaction_frequency_days == 7
    assert result.relationship_score == 50.0


@pytest.mark.asyncio
async def test_create_contact_defaults():
    """create_contact should use default values for optional fields."""
    session = _make_session()

    result = await create_contact(session, first_name="Dave")

    assert result.last_name is None
    assert result.email is None
    assert result.tags is None
    assert result.how_we_met is None
    assert result.interaction_frequency_days is None
    assert result.relationship_score == 50.0


# ---------------------------------------------------------------------------
# get_contact_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_contact_by_id_found():
    """get_contact_by_id should return the contact when it exists."""
    session = _make_session()
    contact = _make_contact(first_name="Eve")
    result_row = MagicMock()
    result_row.scalar_one_or_none.return_value = contact
    session.execute = AsyncMock(return_value=result_row)

    result = await get_contact_by_id(session, contact.id)

    session.execute.assert_awaited_once()
    assert result is contact
    assert result.first_name == "Eve"


@pytest.mark.asyncio
async def test_get_contact_by_id_not_found():
    """get_contact_by_id should return None when contact doesn't exist."""
    session = _make_session()
    result_row = MagicMock()
    result_row.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_row)

    result = await get_contact_by_id(session, uuid.uuid4())

    assert result is None


# ---------------------------------------------------------------------------
# log_interaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_interaction_creates_and_flushes():
    """log_interaction should create an Interaction and flush."""
    session = _make_session()
    contact_id = uuid.uuid4()

    await log_interaction(
        session,
        contact_id=contact_id,
        interaction_type="coffee",
        summary="Caught up over coffee downtown",
    )

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, Interaction)
    assert added.contact_id == contact_id
    assert added.interaction_type == "coffee"
    assert added.summary == "Caught up over coffee downtown"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_interaction_sets_defaults():
    """log_interaction should use defaults for channel and direction."""
    session = _make_session()

    await log_interaction(
        session,
        contact_id=uuid.uuid4(),
        interaction_type="email",
        summary="Sent project update",
    )

    added = session.add.call_args[0][0]
    assert added.channel == "manual"
    assert added.direction == "outgoing"


@pytest.mark.asyncio
async def test_log_interaction_with_custom_fields():
    """log_interaction should accept custom channel, direction, and topics."""
    session = _make_session()

    await log_interaction(
        session,
        contact_id=uuid.uuid4(),
        interaction_type="call",
        summary="Discussed roadmap",
        channel="zoom",
        direction="incoming",
        topics=["roadmap", "hiring"],
    )

    added = session.add.call_args[0][0]
    assert added.channel == "zoom"
    assert added.direction == "incoming"
    assert added.topics == ["roadmap", "hiring"]


@pytest.mark.asyncio
async def test_log_interaction_persists_explicit_timestamp():
    session = _make_session()
    occurred_at = datetime(2026, 3, 16, 9, 30, tzinfo=UTC)

    await log_interaction(
        session,
        contact_id=uuid.uuid4(),
        interaction_type="call",
        summary="Historical interaction",
        interaction_at=occurred_at,
    )

    added = session.add.call_args[0][0]
    assert added.interaction_at == occurred_at


@pytest.mark.asyncio
async def test_log_interaction_updates_contact_last_interaction():
    """log_interaction should update the contact's last_interaction_at."""
    session = _make_session()
    contact_id = uuid.uuid4()

    await log_interaction(
        session,
        contact_id=contact_id,
        interaction_type="meeting",
        summary="Sprint planning",
    )

    # Should have called execute at least once for the Contact update
    assert session.execute.await_count >= 1


# ---------------------------------------------------------------------------
# calculate_relationship_decay
# ---------------------------------------------------------------------------


def test_decay_returns_base_when_no_last_interaction():
    """calculate_relationship_decay should return base_score when last_interaction is None."""
    score = calculate_relationship_decay(None, 14, base_score=50.0)
    assert score == 50.0


def test_decay_returns_base_when_no_frequency():
    """calculate_relationship_decay should return base_score when frequency is None."""
    score = calculate_relationship_decay(datetime.now(UTC), None, base_score=50.0)
    assert score == 50.0


def test_decay_within_frequency_returns_base():
    """No decay should occur when interaction is within the expected frequency."""
    last_interaction = datetime.now(UTC) - timedelta(days=5)
    score = calculate_relationship_decay(last_interaction, 14, base_score=50.0)
    assert score == 50.0


def test_decay_overdue_reduces_score():
    """Score should decay when interaction is overdue."""
    last_interaction = datetime.now(UTC) - timedelta(days=28)
    score = calculate_relationship_decay(last_interaction, 14, base_score=50.0)
    assert score < 50.0
    assert score > 0.0


def test_decay_very_overdue_approaches_zero():
    """Score should approach zero when very overdue."""
    last_interaction = datetime.now(UTC) - timedelta(days=365)
    score = calculate_relationship_decay(last_interaction, 7, base_score=50.0)
    assert score < 1.0


def test_decay_exact_boundary():
    """Score should equal base when days_since == expected_frequency."""
    last_interaction = datetime.now(UTC) - timedelta(days=14)
    score = calculate_relationship_decay(last_interaction, 14, base_score=50.0)
    assert score == 50.0


def test_decay_custom_base_score():
    """calculate_relationship_decay should use a custom base score."""
    last_interaction = datetime.now(UTC) - timedelta(days=60)
    score = calculate_relationship_decay(last_interaction, 14, base_score=100.0)
    assert score < 100.0
    assert score > 0.0


# ---------------------------------------------------------------------------
# get_decaying_relationships
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_decaying_relationships_returns_contacts():
    """get_decaying_relationships should return contacts below the threshold."""
    session = _make_session()
    contact = _make_contact(relationship_score=15.0)

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [contact]
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    results = await get_decaying_relationships(session, threshold=30.0)

    assert len(results) == 1
    assert results[0].relationship_score == 15.0


@pytest.mark.asyncio
async def test_get_decaying_relationships_empty():
    """get_decaying_relationships should return empty list when all contacts healthy."""
    session = _make_session()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    results = await get_decaying_relationships(session)

    assert results == []


@pytest.mark.asyncio
async def test_get_decaying_relationships_respects_limit():
    """get_decaying_relationships should pass the limit parameter."""
    session = _make_session()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    await get_decaying_relationships(session, threshold=20.0, limit=5)

    session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# search_contacts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_contacts_returns_dicts():
    """search_contacts should return a list of dicts."""
    session = _make_session()
    contact_id = uuid.uuid4()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = [
        {
            "id": contact_id,
            "first_name": "Alice",
            "last_name": "Smith",
            "email": "alice@example.com",
            "tags": ["friend"],
            "relationship_score": 45.0,
        }
    ]
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    results = await search_contacts(session, "Alice")

    assert len(results) == 1
    assert results[0]["first_name"] == "Alice"
    assert results[0]["relationship_score"] == 45.0


@pytest.mark.asyncio
async def test_search_contacts_passes_params():
    """search_contacts should pass query and limit to SQL."""
    session = _make_session()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    await search_contacts(session, "Bob", limit=5)

    call_args = session.execute.call_args
    params = call_args[0][1]
    assert params["query"] == "Bob"
    assert params["limit"] == 5


@pytest.mark.asyncio
async def test_search_contacts_empty():
    """search_contacts should return empty list when no matches."""
    session = _make_session()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    results = await search_contacts(session, "xyznonexistent")

    assert results == []
