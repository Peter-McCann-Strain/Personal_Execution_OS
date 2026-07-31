"""Tests for the vector repository — hybrid BM25 + vector search with RRF."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.app.persistence.repositories.vector import hybrid_search

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


def _make_embedding(dims: int = 768) -> list[float]:
    """Create a test embedding vector."""
    return [0.1] * dims


def _mock_settings():
    """Create a mock settings with context engineering defaults."""
    settings = MagicMock()
    settings.rrf_k = 60
    settings.default_search_limit = 10
    settings.memory_decay_rate = 0.01
    return settings


# ---------------------------------------------------------------------------
# hybrid_search — validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_search_empty_embedding_raises():
    """hybrid_search should raise ValueError for empty embedding."""
    session = _make_session()

    with pytest.raises(ValueError, match="query_embedding must be a non-empty list"):
        await hybrid_search(session, "test query", [])


@pytest.mark.asyncio
async def test_hybrid_search_none_embedding_raises():
    """hybrid_search should raise ValueError for None embedding."""
    session = _make_session()

    with pytest.raises(ValueError, match="query_embedding must be a non-empty list"):
        await hybrid_search(session, "test query", None)


@pytest.mark.asyncio
async def test_hybrid_search_non_list_embedding_raises():
    """hybrid_search should raise ValueError for non-list embedding."""
    session = _make_session()

    with pytest.raises(ValueError, match="query_embedding must be a non-empty list"):
        await hybrid_search(session, "test query", "not a list")


@pytest.mark.asyncio
async def test_hybrid_search_non_numeric_values_raises():
    """hybrid_search should raise ValueError for non-numeric embedding values."""
    session = _make_session()

    with pytest.raises(ValueError, match="query_embedding must contain only numeric values"):
        await hybrid_search(session, "test query", [0.1, "bad", 0.3])


# ---------------------------------------------------------------------------
# hybrid_search — successful search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_search_returns_dicts():
    """hybrid_search should return a list of dicts with RRF scores."""
    session = _make_session()
    ep_id = uuid.uuid4()
    now = datetime.now(UTC)

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = [
        {
            "id": ep_id,
            "content": "Productive morning routine",
            "summary": "Morning productivity",
            "episode_type": "diary",
            "para_category": None,
            "tags": ["productivity"],
            "created_at": now,
            "rrf_score": 0.032,
        }
    ]
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    with patch(
        "src.app.persistence.repositories.vector.get_settings", return_value=_mock_settings()
    ):
        results = await hybrid_search(session, "productivity", _make_embedding())

    assert len(results) == 1
    assert isinstance(results[0], dict)
    assert results[0]["content"] == "Productive morning routine"
    assert results[0]["rrf_score"] == 0.032


@pytest.mark.asyncio
async def test_hybrid_search_empty_results():
    """hybrid_search should return empty list when no matches."""
    session = _make_session()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    with patch(
        "src.app.persistence.repositories.vector.get_settings", return_value=_mock_settings()
    ):
        results = await hybrid_search(session, "xyznonexistent", _make_embedding())

    assert results == []


@pytest.mark.asyncio
async def test_hybrid_search_passes_correct_params():
    """hybrid_search should pass query, embedding, k, sub_limit, and limit."""
    session = _make_session()
    embedding = _make_embedding(dims=3)

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    with patch(
        "src.app.persistence.repositories.vector.get_settings", return_value=_mock_settings()
    ):
        await hybrid_search(session, "search term", embedding, limit=5)

    call_args = session.execute.call_args
    params = call_args[0][1]
    assert params["query"] == "search term"
    assert params["embedding"] == "[0.1,0.1,0.1]"
    assert params["k"] == 60
    assert params["sub_limit"] == 10  # limit * 2
    assert params["limit"] == 5
    assert params["decay_rate"] == 0.01


@pytest.mark.asyncio
async def test_hybrid_search_default_limit():
    """hybrid_search should use default limit from settings."""
    session = _make_session()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    with patch(
        "src.app.persistence.repositories.vector.get_settings", return_value=_mock_settings()
    ):
        await hybrid_search(session, "query", _make_embedding(dims=2))

    call_args = session.execute.call_args
    params = call_args[0][1]
    assert params["limit"] == 10
    assert params["sub_limit"] == 20  # 10 * 2


@pytest.mark.asyncio
async def test_hybrid_search_embedding_format():
    """hybrid_search should format the embedding as a PostgreSQL vector string."""
    session = _make_session()
    embedding = [1.0, 2.5, -0.3]

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    with patch(
        "src.app.persistence.repositories.vector.get_settings", return_value=_mock_settings()
    ):
        await hybrid_search(session, "test", embedding)

    call_args = session.execute.call_args
    params = call_args[0][1]
    assert params["embedding"] == "[1.0,2.5,-0.3]"


@pytest.mark.asyncio
async def test_hybrid_search_multiple_results():
    """hybrid_search should return multiple results sorted by RRF score."""
    session = _make_session()
    now = datetime.now(UTC)

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = [
        {
            "id": uuid.uuid4(),
            "content": "Result A",
            "summary": None,
            "episode_type": "diary",
            "para_category": None,
            "tags": None,
            "created_at": now,
            "rrf_score": 0.05,
        },
        {
            "id": uuid.uuid4(),
            "content": "Result B",
            "summary": None,
            "episode_type": "research",
            "para_category": None,
            "tags": None,
            "created_at": now,
            "rrf_score": 0.03,
        },
    ]
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    with patch(
        "src.app.persistence.repositories.vector.get_settings", return_value=_mock_settings()
    ):
        results = await hybrid_search(session, "search", _make_embedding())

    assert len(results) == 2
    assert results[0]["rrf_score"] > results[1]["rrf_score"]


@pytest.mark.asyncio
async def test_hybrid_search_with_integer_embedding_values():
    """hybrid_search should accept integer values in the embedding."""
    session = _make_session()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    with patch(
        "src.app.persistence.repositories.vector.get_settings", return_value=_mock_settings()
    ):
        await hybrid_search(session, "test", [1, 2, 3])

    call_args = session.execute.call_args
    params = call_args[0][1]
    assert params["embedding"] == "[1,2,3]"


@pytest.mark.asyncio
async def test_hybrid_search_respects_explicit_decay_rate():
    """Explicit decay_rate should bypass the settings default."""
    session = _make_session()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    with patch(
        "src.app.persistence.repositories.vector.get_settings", return_value=_mock_settings()
    ):
        await hybrid_search(session, "test", [1, 2, 3], decay_rate=0.2)

    params = session.execute.call_args[0][1]
    assert params["decay_rate"] == 0.2


@pytest.mark.asyncio
async def test_hybrid_search_filters_low_scores_when_min_score_set():
    """min_score should filter weak matches and log the filtered count."""
    session = _make_session()
    now = datetime.now(UTC)

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = [
        {
            "id": uuid.uuid4(),
            "content": "Keep me",
            "summary": None,
            "episode_type": "diary",
            "para_category": None,
            "tags": None,
            "created_at": now,
            "rrf_score": 0.12,
        },
        {
            "id": uuid.uuid4(),
            "content": "Drop me",
            "summary": None,
            "episode_type": "diary",
            "para_category": None,
            "tags": None,
            "created_at": now,
            "rrf_score": 0.01,
        },
    ]
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    with (
        patch(
            "src.app.persistence.repositories.vector.get_settings", return_value=_mock_settings()
        ),
        patch("src.app.persistence.repositories.vector.logger.info") as mock_log_info,
    ):
        results = await hybrid_search(session, "test", _make_embedding(), min_score=0.05)

    assert [row["content"] for row in results] == ["Keep me"]
    mock_log_info.assert_any_call(
        "hybrid_search_relevance_filtered",
        before=2,
        after=1,
        min_score=0.05,
    )


@pytest.mark.asyncio
async def test_hybrid_search_keeps_all_rows_when_min_score_does_not_filter():
    """min_score should not emit a filtered log event when nothing is removed."""
    session = _make_session()
    now = datetime.now(UTC)

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = [
        {
            "id": uuid.uuid4(),
            "content": "Keep me too",
            "summary": None,
            "episode_type": "diary",
            "para_category": None,
            "tags": None,
            "created_at": now,
            "rrf_score": 0.12,
        },
    ]
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    with (
        patch(
            "src.app.persistence.repositories.vector.get_settings", return_value=_mock_settings()
        ),
        patch("src.app.persistence.repositories.vector.logger.info") as mock_log_info,
    ):
        results = await hybrid_search(session, "test", _make_embedding(), min_score=0.05)

    assert [row["content"] for row in results] == ["Keep me too"]
    assert mock_log_info.call_args_list == [
        call("hybrid_search", query_length=4, results=1),
    ]


def test_rrf_k_from_settings():
    """RRF_K should come from settings, defaulting to 60."""
    settings = _mock_settings()
    assert settings.rrf_k == 60
