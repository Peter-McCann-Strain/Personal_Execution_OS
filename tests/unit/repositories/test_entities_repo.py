"""Tests for the entities repository — upsert, relationships, mentions, search."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.persistence.models import Entity, EntityMention, EntityRelationship
from src.app.persistence.repositories.entities import (
    add_mention,
    add_relationship,
    find_related_entities,
    search_entities,
    upsert_entity,
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


def _make_entity(
    name: str = "Python",
    entity_type: str = "technology",
    mention_count: int = 1,
) -> Entity:
    """Create a test Entity ORM object."""
    e = Entity()
    e.id = uuid.uuid4()
    e.name = name
    e.entity_type = entity_type
    e.canonical_name = name
    e.mention_count = mention_count
    e.first_seen = datetime.now(UTC)
    e.last_seen = datetime.now(UTC)
    e.metadata_ = {}
    e.created_at = datetime.now(UTC)
    return e


# ---------------------------------------------------------------------------
# upsert_entity — new entity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_entity_creates_new():
    """upsert_entity should create a new entity when none matches."""
    session = _make_session()

    # Simulate no existing entity found
    mock_result = MagicMock()
    mock_result.first.return_value = None
    session.execute.return_value = mock_result

    await upsert_entity(session, "FastAPI", "technology")

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    # The added object should be an Entity
    added_entity = session.add.call_args[0][0]
    assert isinstance(added_entity, Entity)
    assert added_entity.name == "FastAPI"
    assert added_entity.entity_type == "technology"
    assert added_entity.mention_count == 1


@pytest.mark.asyncio
async def test_upsert_entity_creates_with_canonical_name():
    """New entity should have canonical_name set to the provided name."""
    session = _make_session()

    mock_result = MagicMock()
    mock_result.first.return_value = None
    session.execute.return_value = mock_result

    await upsert_entity(session, "Claude Opus", "model")

    added_entity = session.add.call_args[0][0]
    assert added_entity.canonical_name == "Claude Opus"


# ---------------------------------------------------------------------------
# upsert_entity — existing entity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_entity_updates_existing():
    """upsert_entity should update mention_count when entity exists."""
    session = _make_session()
    existing_id = uuid.uuid4()

    # Simulate existing entity found
    mock_row = MagicMock()
    mock_row.id = existing_id
    mock_row.mention_count = 3

    mock_result = MagicMock()
    mock_result.first.return_value = mock_row
    session.execute.return_value = mock_result

    result_id = await upsert_entity(session, "Python", "technology")

    assert result_id == existing_id
    # Should have called execute twice: once to find, once to update
    assert session.execute.await_count == 2
    # Should NOT have called session.add (no new entity)
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_entity_returns_existing_uuid():
    """upsert_entity should return the existing entity's UUID when it exists."""
    session = _make_session()
    existing_id = uuid.uuid4()

    mock_row = MagicMock()
    mock_row.id = existing_id
    mock_row.mention_count = 1

    mock_result = MagicMock()
    mock_result.first.return_value = mock_row
    session.execute.return_value = mock_result

    result = await upsert_entity(session, "Example Database", "service")

    assert isinstance(result, uuid.UUID)
    assert result == existing_id


# ---------------------------------------------------------------------------
# add_relationship
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_relationship_creates_new():
    """add_relationship should create a new relationship when none exists."""
    session = _make_session()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    # Simulate no existing relationship
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    await add_relationship(session, source_id, target_id, "depends_on")

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, EntityRelationship)
    assert added.source_entity_id == source_id
    assert added.target_entity_id == target_id
    assert added.relationship_type == "depends_on"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_relationship_skips_duplicate():
    """add_relationship should silently skip if relationship already exists."""
    session = _make_session()

    # Simulate existing relationship found
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = uuid.uuid4()
    session.execute.return_value = mock_result

    await add_relationship(session, uuid.uuid4(), uuid.uuid4(), "works_with")

    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_relationship_different_types_allowed():
    """Two entities can have multiple relationships of different types."""
    session = _make_session()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()

    # First call: no existing relationship
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    await add_relationship(session, source_id, target_id, "mentions")
    session.add.assert_called_once()


# ---------------------------------------------------------------------------
# add_mention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_mention_creates_new():
    """add_mention should create a new mention when none exists."""
    session = _make_session()
    entity_id = uuid.uuid4()
    episode_id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    await add_mention(session, entity_id, episode_id, "mentioned in diary")

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, EntityMention)
    assert added.entity_id == entity_id
    assert added.episode_id == episode_id
    assert added.context_snippet == "mentioned in diary"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_mention_skips_duplicate():
    """add_mention should silently skip if mention already exists."""
    session = _make_session()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = uuid.uuid4()
    session.execute.return_value = mock_result

    await add_mention(session, uuid.uuid4(), uuid.uuid4())

    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_mention_without_context():
    """add_mention should work without a context_snippet."""
    session = _make_session()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    await add_mention(session, uuid.uuid4(), uuid.uuid4())

    added = session.add.call_args[0][0]
    assert added.context_snippet is None


# ---------------------------------------------------------------------------
# find_related_entities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_related_entities_returns_dicts():
    """find_related_entities should return a list of dicts."""
    session = _make_session()
    related_id = uuid.uuid4()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = [
        {
            "id": related_id,
            "name": "SQLAlchemy",
            "entity_type": "technology",
            "relationship_type": "uses",
            "depth": 1,
        }
    ]
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    results = await find_related_entities(session, uuid.uuid4())

    assert len(results) == 1
    assert results[0]["name"] == "SQLAlchemy"
    assert results[0]["depth"] == 1


@pytest.mark.asyncio
async def test_find_related_entities_empty():
    """find_related_entities should return empty list when no relationships."""
    session = _make_session()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    results = await find_related_entities(session, uuid.uuid4())

    assert results == []


@pytest.mark.asyncio
async def test_find_related_entities_passes_params():
    """find_related_entities should pass entity_id, max_depth, and limit."""
    session = _make_session()
    entity_id = uuid.uuid4()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    await find_related_entities(session, entity_id, max_depth=3, limit=5)

    call_args = session.execute.call_args
    params = call_args[0][1]
    assert params["entity_id"] == entity_id
    assert params["max_depth"] == 3
    assert params["limit"] == 5


# ---------------------------------------------------------------------------
# search_entities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_entities_returns_dicts():
    """search_entities should return a list of dicts with similarity scores."""
    session = _make_session()
    entity_id = uuid.uuid4()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = [
        {
            "id": entity_id,
            "name": "Python",
            "entity_type": "technology",
            "mention_count": 42,
            "sim": 0.9,
        }
    ]
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    results = await search_entities(session, "Python")

    assert len(results) == 1
    assert results[0]["name"] == "Python"
    assert results[0]["sim"] == 0.9


@pytest.mark.asyncio
async def test_search_entities_with_type_filter():
    """search_entities should include type filter when entity_type is provided."""
    session = _make_session()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    await search_entities(session, "Claude", entity_type="model")

    call_args = session.execute.call_args
    params = call_args[0][1]
    assert params["query"] == "Claude"
    assert params["entity_type"] == "model"
    assert params["limit"] == 10


@pytest.mark.asyncio
async def test_search_entities_empty():
    """search_entities should return empty list when no matches."""
    session = _make_session()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    results = await search_entities(session, "xyznonexistent")

    assert results == []


@pytest.mark.asyncio
async def test_search_entities_without_type_filter():
    """search_entities should not include type filter when entity_type is None."""
    session = _make_session()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    await search_entities(session, "FastAPI", entity_type=None, limit=5)

    call_args = session.execute.call_args
    params = call_args[0][1]
    assert params["query"] == "FastAPI"
    assert params["entity_type"] is None
    assert params["limit"] == 5
