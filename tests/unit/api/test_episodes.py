"""Tests for the episodes API routes — listing, detail, stats, and filters."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.episodes import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from tests.unit.api.auth_helpers import override_current_principal

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _mock_get_db():
    """Yield a mock session so the route doesn't need a real DB."""
    yield AsyncMock()


def _build_app(*, override_auth: bool = True) -> FastAPI:
    """Create a minimal FastAPI app with the episodes router for testing."""
    app = FastAPI()
    app.dependency_overrides[get_db] = _mock_get_db

    if override_auth:
        override_current_principal(app)

    # Register the AppError exception handler so NotFoundError returns 404.
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.include_router(router, prefix="/api")
    return app


def _make_mock_episode(
    *,
    ep_id: uuid.UUID | None = None,
    content: str = "Had a great morning walk today.",
    summary: str | None = "Morning walk entry",
    episode_type: str = "diary",
    para_category: str | None = "area",
    mood_score: float | None = 7.5,
    energy_rating: float | None = 8.0,
    tags: list[str] | None = None,
    people_mentioned: list[str] | None = None,
    source: str = "api",
    created_at: datetime | None = None,
) -> MagicMock:
    """Create a mock Episode ORM object with the required attributes."""
    mock = MagicMock()
    mock.id = ep_id or uuid.uuid4()
    mock.content = content
    mock.summary = summary
    mock.episode_type = episode_type
    mock.para_category = para_category
    mock.mood_score = mood_score
    mock.energy_rating = energy_rating
    mock.tags = tags or ["exercise", "morning"]
    mock.people_mentioned = people_mentioned or []
    mock.source = source
    mock.created_at = created_at or datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)
    return mock


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


async def test_list_episodes_success():
    """GET /episodes returns 200 with PaginatedResponse shape."""
    ep1 = _make_mock_episode(content="Entry one")
    ep2 = _make_mock_episode(content="Entry two")

    mock_db = AsyncMock()

    # Mock count query: total_result.scalar() -> 2
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 2

    # Mock data query: result.scalars().all() -> [ep1, ep2]
    mock_data_result = MagicMock()
    mock_data_result.scalars.return_value.all.return_value = [ep1, ep2]

    # session.execute is called twice: first for count, then for data
    mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])

    async def _db_with_mock():
        yield mock_db

    app = _build_app()
    app.dependency_overrides[get_db] = _db_with_mock

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/episodes")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "has_more" in data
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["content"] == "Entry one"
    assert data["items"][1]["content"] == "Entry two"


async def test_get_episode_by_id_success():
    """GET /episodes/{id} returns 200 with the episode DTO."""
    ep_id = uuid.uuid4()
    mock_ep = _make_mock_episode(ep_id=ep_id, content="Specific entry")

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_ep
    mock_db.execute = AsyncMock(return_value=result)

    async def _db_with_mock():
        yield mock_db

    app = _build_app()
    app.dependency_overrides[get_db] = _db_with_mock

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/episodes/{ep_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(ep_id)
    assert data["content"] == "Specific entry"
    assert data["episode_type"] == "diary"
    assert isinstance(data["tags"], list)


async def test_get_episode_not_found():
    """GET /episodes/{id} returns 404 when episode does not exist."""
    ep_id = uuid.uuid4()

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=result)

    async def _db_with_mock():
        yield mock_db

    app = _build_app()
    app.dependency_overrides[get_db] = _db_with_mock

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/episodes/{ep_id}")

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "not_found"


async def test_get_episode_stats():
    """GET /episodes/stats returns 200 with the expected stats shape."""
    mock_db = AsyncMock()

    # 1) total count
    mock_total = MagicMock()
    mock_total.scalar.return_value = 10

    # 2) avg mood/energy
    mock_avg = MagicMock()
    mock_avg_row = MagicMock()
    mock_avg_row.__getitem__ = lambda self, idx: {0: 7.25, 1: 6.80}[idx]
    mock_avg.one.return_value = mock_avg_row

    # 3) mood trend (daily)
    mock_trend_row = MagicMock()
    mock_trend_row.date = "2026-03-15"
    mock_trend_row.mood = 7.5
    mock_trend_row.energy = 8.0
    mock_trend_row.count = 3
    mock_trend = MagicMock()
    mock_trend.all.return_value = [mock_trend_row]

    # 4) tag frequency
    mock_tag_row = MagicMock()
    mock_tag_row.tag = "exercise"
    mock_tag_row.cnt = 5
    mock_tags = MagicMock()
    mock_tags.all.return_value = [mock_tag_row]

    # 5) PARA distribution
    mock_para_row = MagicMock()
    mock_para_row.category = "area"
    mock_para_row.count = 4
    mock_para = MagicMock()
    mock_para.all.return_value = [mock_para_row]

    mock_db.execute = AsyncMock(
        side_effect=[mock_total, mock_avg, mock_trend, mock_tags, mock_para]
    )

    async def _db_with_mock():
        yield mock_db

    app = _build_app()
    app.dependency_overrides[get_db] = _db_with_mock

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/episodes/stats", params={"days": 30})

    assert resp.status_code == 200
    data = resp.json()
    # Check camelCase serialization aliases
    assert data["totalEntries"] == 10
    assert data["averageMood"] == 7.25
    assert data["averageEnergy"] == 6.8
    assert isinstance(data["moodTrend"], list)
    assert len(data["moodTrend"]) == 1
    assert data["moodTrend"][0]["date"] == "2026-03-15"
    assert isinstance(data["tagFrequency"], list)
    assert data["tagFrequency"][0]["tag"] == "exercise"
    assert isinstance(data["paraDistribution"], list)
    assert data["paraDistribution"][0]["category"] == "area"


async def test_list_episodes_with_filters():
    """GET /episodes with filter query params is accepted (no 422)."""
    mock_db = AsyncMock()

    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 0

    mock_data_result = MagicMock()
    mock_data_result.scalars.return_value.all.return_value = []

    mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])

    async def _db_with_mock():
        yield mock_db

    app = _build_app()
    app.dependency_overrides[get_db] = _db_with_mock

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/episodes",
            params={
                "limit": 10,
                "offset": 0,
                "sort": "mood_score",
                "order": "asc",
                "date_from": "2026-01-01T00:00:00",
                "date_to": "2026-03-15T23:59:59",
                "para_category": "project",
                "episode_type": "diary",
                "tags": "exercise,health",
                "people": "Alice,Bob",
                "mood_min": 5.0,
                "mood_max": 9.0,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["has_more"] is False


async def test_list_episodes_ignores_blank_tag_and_people_filters():
    """Blank comma-separated filters should not apply overlap clauses."""
    mock_db = AsyncMock()

    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 0

    mock_data_result = MagicMock()
    mock_data_result.scalars.return_value.all.return_value = []

    mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])

    async def _db_with_mock():
        yield mock_db

    app = _build_app()
    app.dependency_overrides[get_db] = _db_with_mock

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/episodes",
            params={
                "tags": " , , ",
                "people": " , ",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


async def test_get_episodes_by_date_range():
    """GET /episodes/date-range returns DTOs from the repository helper."""
    ep_id = uuid.uuid4()
    mock_ep = _make_mock_episode(ep_id=ep_id, content="Range match")
    mock_db = AsyncMock()

    with patch(
        "src.app.api.routes.episodes.repo_get_episodes_by_date_range",
        new_callable=AsyncMock,
        return_value=[mock_ep],
    ) as mock_repo:
        from src.app.api.routes.episodes import get_episodes_by_date_range

        result = await get_episodes_by_date_range(
            mock_db,
            start="2026-03-01T00:00:00",
            end="2026-03-31T23:59:59",
            limit=10,
        )

    assert len(result) == 1
    assert result[0].id == str(ep_id)
    assert result[0].content == "Range match"
    mock_repo.assert_awaited_once()


async def test_update_episode_success_and_not_found():
    """PATCH /episodes/{id} updates fields and translates missing rows to 404."""
    ep_id = uuid.uuid4()
    mock_ep = _make_mock_episode(ep_id=ep_id, content="Updated content")

    @asynccontextmanager
    async def _tx():
        yield

    db = AsyncMock()
    db.begin = _tx
    db.refresh = AsyncMock()

    body = {
        "content": "Updated content",
        "summary": None,
        "episode_type": "note",
        "para_category": None,
        "mood_score": 8.0,
        "energy_rating": None,
        "tags": ["focus"],
        "people_mentioned": None,
        "source": "api",
    }

    with patch(
        "src.app.api.routes.episodes.repo_update_episode",
        new_callable=AsyncMock,
        return_value=mock_ep,
    ) as mock_repo:
        from src.app.api.routes.episodes import UpdateEpisodeBody, update_episode

        result = await update_episode(ep_id, UpdateEpisodeBody(**body), db)

    assert result.id == str(ep_id)
    assert result.content == "Updated content"
    mock_repo.assert_awaited_once()
    assert mock_repo.call_args.kwargs == {
        "content": "Updated content",
        "episode_type": "note",
        "mood_score": 8.0,
        "tags": ["focus"],
        "source": "api",
    }
    db.refresh.assert_awaited_once_with(mock_ep)

    db_not_found = AsyncMock()
    db_not_found.begin = _tx
    db_not_found.refresh = AsyncMock()

    with patch(
        "src.app.api.routes.episodes.repo_update_episode",
        new_callable=AsyncMock,
        side_effect=ValueError(f"Episode not found: {ep_id}"),
    ):
        from src.app.api.routes.episodes import UpdateEpisodeBody, update_episode
        from src.app.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError, match=str(ep_id)):
            await update_episode(ep_id, UpdateEpisodeBody(content="x"), db_not_found)


async def test_delete_episode_success_and_not_found():
    """DELETE /episodes/{id} soft-deletes rows and raises 404 when missing."""
    ep_id = uuid.uuid4()
    episode = _make_mock_episode(ep_id=ep_id)
    episode.soft_delete = MagicMock()

    @asynccontextmanager
    async def _tx():
        yield

    db = AsyncMock()
    db.begin = _tx
    result = MagicMock()
    result.scalar_one_or_none.return_value = episode
    db.execute = AsyncMock(return_value=result)

    from src.app.api.routes.episodes import delete_episode

    await delete_episode(ep_id, db)
    episode.soft_delete.assert_called_once()

    db_not_found = AsyncMock()
    db_not_found.begin = _tx
    not_found_result = MagicMock()
    not_found_result.scalar_one_or_none.return_value = None
    db_not_found.execute = AsyncMock(return_value=not_found_result)

    from src.app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError, match=str(ep_id)):
        await delete_episode(ep_id, db_not_found)
