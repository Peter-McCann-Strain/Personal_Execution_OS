"""Tests for the episodes repository — create, BM25 search, get by ID."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.core.exceptions import NotFoundError
from src.app.domain.constants import EpisodeType
from src.app.persistence.models import Episode
from src.app.persistence.repositories.episodes import (
    create_episode,
    delete_episode,
    get_episode_by_id,
    get_episodes_by_date_range,
    search_episodes_bm25,
    update_episode,
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


def _make_episode(**overrides) -> Episode:
    """Create a test Episode ORM object."""
    ep = Episode()
    ep.id = overrides.get("id", uuid.uuid4())
    ep.content = overrides.get("content", "Had a productive morning.")
    ep.summary = overrides.get("summary")
    ep.episode_type = overrides.get("episode_type", EpisodeType.DIARY)
    ep.para_category = overrides.get("para_category")
    ep.mood_score = overrides.get("mood_score")
    ep.energy_rating = overrides.get("energy_rating")
    ep.tags = overrides.get("tags")
    ep.people_mentioned = overrides.get("people_mentioned")
    ep.source = overrides.get("source", "telegram")
    ep.metadata_ = overrides.get("metadata_", {})
    ep.created_at = overrides.get("created_at", datetime.now(UTC))
    return ep


# ---------------------------------------------------------------------------
# create_episode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_episode_adds_and_flushes():
    """create_episode should call session.add() and session.flush()."""
    session = _make_session()

    result = await create_episode(
        session,
        content="Morning journaling session",
        episode_type=EpisodeType.DIARY,
        source="telegram",
    )

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert isinstance(result, Episode)


@pytest.mark.asyncio
async def test_create_episode_sets_fields():
    """create_episode should set all provided fields on the Episode."""
    session = _make_session()

    result = await create_episode(
        session,
        content="Research on LangGraph",
        episode_type=EpisodeType.RESEARCH,
        source="web",
        summary="LangGraph architecture overview",
        para_category="project",
        mood_score=7.5,
        energy_rating=8.0,
        tags=["langgraph", "ai"],
        people_mentioned=["Harrison Chase"],
        metadata={"url": "https://example.com"},
    )

    assert result.content == "Research on LangGraph"
    assert result.episode_type == EpisodeType.RESEARCH
    assert result.source == "web"
    assert result.summary == "LangGraph architecture overview"
    assert result.para_category == "project"
    assert result.mood_score == 7.5
    assert result.energy_rating == 8.0
    assert result.tags == ["langgraph", "ai"]
    assert result.people_mentioned == ["Harrison Chase"]
    assert result.metadata_ == {"url": "https://example.com"}


@pytest.mark.asyncio
async def test_create_episode_defaults_metadata_to_empty_dict():
    """create_episode should default metadata_ to {} when None."""
    session = _make_session()

    result = await create_episode(
        session,
        content="Quick note",
        episode_type=EpisodeType.NOTE,
        source="telegram",
        metadata=None,
    )

    assert result.metadata_ == {}


# ---------------------------------------------------------------------------
# get_episode_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_episode_by_id_found():
    """get_episode_by_id should return the episode when it exists."""
    session = _make_session()
    episode = _make_episode(content="Found episode")
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = episode
    session.execute.return_value = result_proxy

    result = await get_episode_by_id(session, episode.id)

    session.execute.assert_awaited_once()
    assert result is episode
    assert result.content == "Found episode"


@pytest.mark.asyncio
async def test_get_episode_by_id_not_found():
    """get_episode_by_id should return None when episode doesn't exist."""
    session = _make_session()
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = None
    session.execute.return_value = result_proxy

    result = await get_episode_by_id(session, uuid.uuid4())

    session.execute.assert_awaited_once()
    assert result is None


# ---------------------------------------------------------------------------
# get_episodes_by_date_range
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_episodes_by_date_range_returns_list():
    """get_episodes_by_date_range should return a list of episodes."""
    session = _make_session()
    episodes = [_make_episode(content="Episode A"), _make_episode(content="Episode B")]

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = episodes
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 12, 31, tzinfo=UTC)
    result = await get_episodes_by_date_range(session, start, end)

    assert len(result) == 2
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_episodes_by_date_range_empty():
    """get_episodes_by_date_range should return empty list when no episodes match."""
    session = _make_session()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)
    result = await get_episodes_by_date_range(session, start, end)

    assert result == []


# ---------------------------------------------------------------------------
# search_episodes_bm25
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_bm25_returns_dicts():
    """search_episodes_bm25 should return a list of dicts, not ORM instances."""
    session = _make_session()
    ep_id = uuid.uuid4()
    now = datetime.now(UTC)

    mock_mapping = MagicMock()
    mock_mapping.__iter__ = MagicMock(
        return_value=iter(
            [
                {
                    "id": ep_id,
                    "content": "productive morning",
                    "summary": None,
                    "episode_type": "diary",
                    "para_category": None,
                    "mood_score": 7.0,
                    "energy_rating": 8.0,
                    "tags": None,
                    "people_mentioned": None,
                    "source": "telegram",
                    "metadata": {},
                    "created_at": now,
                    "rank": 0.85,
                }
            ]
        )
    )

    mock_result = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = [
        {
            "id": ep_id,
            "content": "productive morning",
            "summary": None,
            "episode_type": "diary",
            "para_category": None,
            "mood_score": 7.0,
            "energy_rating": 8.0,
            "tags": None,
            "people_mentioned": None,
            "source": "telegram",
            "metadata": {},
            "created_at": now,
            "rank": 0.85,
        }
    ]
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    results = await search_episodes_bm25(session, "productive")

    assert len(results) == 1
    assert isinstance(results[0], dict)
    assert results[0]["content"] == "productive morning"
    assert results[0]["rank"] == 0.85


@pytest.mark.asyncio
async def test_search_bm25_passes_correct_params():
    """search_episodes_bm25 should pass query and limit to the SQL statement."""
    session = _make_session()

    mock_result = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    await search_episodes_bm25(session, "meeting notes", limit=5)

    session.execute.assert_awaited_once()
    call_args = session.execute.call_args
    params = call_args[0][1]
    assert params["query"] == "meeting notes"
    assert params["limit"] == 5


@pytest.mark.asyncio
async def test_search_bm25_empty_results():
    """search_episodes_bm25 should return empty list when no matches."""
    session = _make_session()

    mock_result = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    results = await search_episodes_bm25(session, "xyznonexistent")

    assert results == []


# ---------------------------------------------------------------------------
# update_episode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_episode_with_valid_fields():
    """update_episode should update allowed fields."""
    session = _make_session()
    ep = _make_episode(content="Updated content")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = ep
    session.execute.return_value = mock_result

    result = await update_episode(session, ep.id, content="Updated content")

    session.execute.assert_awaited_once()
    assert result.content == "Updated content"


@pytest.mark.asyncio
async def test_update_episode_not_found_raises():
    """update_episode should raise ValueError if episode not found."""
    session = _make_session()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    with pytest.raises(NotFoundError, match="Episode not found"):
        await update_episode(session, uuid.uuid4(), content="new content")


@pytest.mark.asyncio
async def test_update_episode_no_valid_kwargs_returns_episode():
    """update_episode with no valid kwargs should return the episode unchanged."""
    session = _make_session()
    ep = _make_episode()
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = ep
    session.execute.return_value = result_proxy

    result = await update_episode(session, ep.id, invalid_field="value")

    assert result is ep


@pytest.mark.asyncio
async def test_update_episode_no_valid_kwargs_not_found_raises():
    """update_episode with no valid kwargs should raise if not found."""
    session = _make_session()
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = None
    session.execute.return_value = result_proxy

    with pytest.raises(NotFoundError, match="Episode not found"):
        await update_episode(session, uuid.uuid4(), invalid_field="value")


# ---------------------------------------------------------------------------
# delete_episode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_episode_found():
    """delete_episode should return True when the episode is deleted."""
    session = _make_session()
    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute.return_value = mock_result

    result = await delete_episode(session, uuid.uuid4())

    assert result is True
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_episode_not_found():
    """delete_episode should return False when the episode doesn't exist."""
    session = _make_session()
    mock_result = MagicMock()
    mock_result.rowcount = 0
    session.execute.return_value = mock_result

    result = await delete_episode(session, uuid.uuid4())

    assert result is False
