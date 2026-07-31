"""Tests for the Zettelkasten link discoverer — entity and embedding based link discovery."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.second_brain.link_discoverer import (
    discover_links_by_embedding,
    discover_links_by_entities,
)


def _make_mock_session(rows: list[dict]) -> AsyncMock:
    """Build a mock AsyncSession that returns predefined query results."""
    session = AsyncMock()
    # Build mock mappings result
    mock_result = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = [MagicMock(**{k: v for k, v in row.items()}) for row in rows]
    # Make each mapping dict-convertible by returning the row dicts directly
    # dict(row) is called on each mapping, so we need __iter__ and keys
    mapping_objects = []
    for row in rows:
        m = MagicMock()
        m.keys.return_value = row.keys()
        m.__iter__ = MagicMock(return_value=iter(row.keys()))
        m.__getitem__ = MagicMock(side_effect=lambda k, r=row: r[k])
        mapping_objects.append(m)
    mock_mappings.all.return_value = mapping_objects
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result
    return session


# ---------------------------------------------------------------------------
# discover_links_by_entities
# ---------------------------------------------------------------------------


async def test_discover_links_by_entities_with_shared_entities():
    """Notes sharing entities should be returned as links."""
    note_id = uuid.uuid4()
    linked_id = uuid.uuid4()
    rows = [
        {"id": linked_id, "summary": "Related note about Sarah", "shared_entities": 2},
    ]
    session = _make_mock_session(rows)

    result = await discover_links_by_entities(session, note_id, limit=5)

    assert len(result) == 1
    assert result[0]["id"] == linked_id
    assert result[0]["shared_entities"] == 2
    # Verify the SQL was executed with the right parameters
    session.execute.assert_awaited_once()
    call_args = session.execute.call_args
    assert call_args[0][1]["note_id"] == note_id
    assert call_args[0][1]["limit"] == 5


async def test_discover_links_by_entities_no_shared_entities():
    """When no notes share entities, an empty list should be returned."""
    note_id = uuid.uuid4()
    session = _make_mock_session([])

    result = await discover_links_by_entities(session, note_id)

    assert result == []
    session.execute.assert_awaited_once()


async def test_discover_links_by_entities_multiple_results():
    """Multiple related notes should be returned, ordered by shared entity count."""
    note_id = uuid.uuid4()
    rows = [
        {"id": uuid.uuid4(), "summary": "Most related note", "shared_entities": 5},
        {"id": uuid.uuid4(), "summary": "Second related", "shared_entities": 3},
        {"id": uuid.uuid4(), "summary": "Third related", "shared_entities": 1},
    ]
    session = _make_mock_session(rows)

    result = await discover_links_by_entities(session, note_id, limit=3)

    assert len(result) == 3
    assert result[0]["shared_entities"] == 5
    assert result[2]["shared_entities"] == 1


async def test_discover_links_by_entities_custom_limit():
    """The limit parameter should be passed through to the query."""
    note_id = uuid.uuid4()
    session = _make_mock_session([])

    await discover_links_by_entities(session, note_id, limit=10)

    call_args = session.execute.call_args
    assert call_args[0][1]["limit"] == 10


async def test_discover_links_by_entities_db_error():
    """Database errors should propagate — no silent swallowing."""
    note_id = uuid.uuid4()
    session = AsyncMock()
    session.execute.side_effect = Exception("connection refused")

    with pytest.raises(Exception, match="connection refused"):
        await discover_links_by_entities(session, note_id)


# ---------------------------------------------------------------------------
# discover_links_by_embedding
# ---------------------------------------------------------------------------


async def test_discover_links_by_embedding_similar_notes():
    """Notes with similar embeddings should be returned with similarity scores."""
    note_id = uuid.uuid4()
    linked_id = uuid.uuid4()
    rows = [
        {
            "id": linked_id,
            "title": "Similar Note",
            "executive_summary": "A related topic",
            "similarity": 0.92,
        },
    ]
    session = _make_mock_session(rows)

    result = await discover_links_by_embedding(session, note_id, limit=5)

    assert len(result) == 1
    assert result[0]["id"] == linked_id
    assert result[0]["similarity"] == 0.92
    session.execute.assert_awaited_once()


async def test_discover_links_by_embedding_no_embeddings():
    """When no notes have embeddings, an empty list should be returned."""
    note_id = uuid.uuid4()
    session = _make_mock_session([])

    result = await discover_links_by_embedding(session, note_id)

    assert result == []


async def test_discover_links_by_embedding_multiple_results():
    """Multiple similar notes should be returned ordered by similarity."""
    note_id = uuid.uuid4()
    rows = [
        {
            "id": uuid.uuid4(),
            "title": "Very similar",
            "executive_summary": "s1",
            "similarity": 0.95,
        },
        {
            "id": uuid.uuid4(),
            "title": "Somewhat similar",
            "executive_summary": "s2",
            "similarity": 0.80,
        },
        {
            "id": uuid.uuid4(),
            "title": "Weakly similar",
            "executive_summary": "s3",
            "similarity": 0.60,
        },
    ]
    session = _make_mock_session(rows)

    result = await discover_links_by_embedding(session, note_id, limit=3)

    assert len(result) == 3
    assert result[0]["similarity"] == 0.95
    assert result[2]["similarity"] == 0.60


async def test_discover_links_by_embedding_custom_limit():
    """The limit parameter should be forwarded to the SQL query."""
    note_id = uuid.uuid4()
    session = _make_mock_session([])

    await discover_links_by_embedding(session, note_id, limit=20)

    call_args = session.execute.call_args
    assert call_args[0][1]["limit"] == 20


async def test_discover_links_by_embedding_db_error():
    """Database errors should propagate."""
    note_id = uuid.uuid4()
    session = AsyncMock()
    session.execute.side_effect = Exception("timeout")

    with pytest.raises(Exception, match="timeout"):
        await discover_links_by_embedding(session, note_id)
