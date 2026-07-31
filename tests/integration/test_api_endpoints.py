"""Integration tests for CRUD API endpoints.

Tests key endpoints through the full FastAPI app with mocked database
session and authentication. Validates request/response contracts, pagination,
error handling, and HTTP status codes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Test health check through the full app."""

    async def test_health_returns_ok(self, integration_client):
        """GET /health returns 200 with status and services when DB is reachable."""
        client, mock_session, _ = integration_client

        # Mock the SELECT 1 health check query
        mock_result = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/health")

        # Health endpoint may return 200 (ok/degraded) or 503 (down).
        # With mocked DB execute succeeding, it should be 200.
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded")
        assert "services" in data
        assert "timestamp" in data


# ---------------------------------------------------------------------------
# Episodes endpoints
# ---------------------------------------------------------------------------


class TestEpisodesListEndpoint:
    """Test GET /api/episodes — paginated episode listing."""

    async def test_list_episodes_returns_paginated(self, integration_client):
        """GET /api/episodes returns 200 with PaginatedResponse shape."""
        client, mock_session, _ = integration_client

        ep1 = _make_mock_episode(content="Entry one")
        ep2 = _make_mock_episode(content="Entry two")

        # Mock count query: total_result.scalar() -> 2
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 2

        # Mock data query: result.scalars().all() -> [ep1, ep2]
        mock_data_result = MagicMock()
        mock_data_result.scalars.return_value.all.return_value = [ep1, ep2]

        # session.execute is called twice: first for count, then for data
        mock_session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_data_result],
        )

        response = await client.get("/api/episodes")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["page"] == 1
        assert data["page_size"] == 25  # default limit
        assert data["has_more"] is False
        assert len(data["items"]) == 2
        assert data["items"][0]["content"] == "Entry one"
        assert data["items"][1]["content"] == "Entry two"

    async def test_list_episodes_empty(self, integration_client):
        """GET /api/episodes returns empty items when no episodes exist."""
        client, mock_session, _ = integration_client

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_data_result = MagicMock()
        mock_data_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_data_result],
        )

        response = await client.get("/api/episodes")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert data["has_more"] is False

    async def test_list_episodes_with_pagination_params(self, integration_client):
        """GET /api/episodes respects limit and offset query parameters."""
        client, mock_session, _ = integration_client

        ep = _make_mock_episode(content="Page 2 entry")

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 30

        mock_data_result = MagicMock()
        mock_data_result.scalars.return_value.all.return_value = [ep]

        mock_session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_data_result],
        )

        response = await client.get("/api/episodes", params={"limit": 10, "offset": 10})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 30
        assert data["page"] == 2
        assert data["page_size"] == 10
        assert data["has_more"] is True
        assert len(data["items"]) == 1

    async def test_list_episodes_with_filters(self, integration_client):
        """GET /api/episodes with filter params is accepted (no 422)."""
        client, mock_session, _ = integration_client

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_data_result = MagicMock()
        mock_data_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_data_result],
        )

        response = await client.get(
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

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


class TestEpisodeDetailEndpoint:
    """Test GET /api/episodes/{episode_id} — single episode retrieval."""

    async def test_get_episode_by_id(self, integration_client):
        """GET /api/episodes/{id} returns 200 with the episode DTO."""
        client, mock_session, _ = integration_client

        ep_id = uuid.uuid4()
        mock_ep = _make_mock_episode(ep_id=ep_id, content="Specific entry")
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_ep
        mock_session.execute = AsyncMock(return_value=result)

        response = await client.get(f"/api/episodes/{ep_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(ep_id)
        assert data["content"] == "Specific entry"
        assert data["episode_type"] == "diary"
        assert isinstance(data["tags"], list)

    async def test_get_episode_not_found(self, integration_client):
        """GET /api/episodes/{id} returns 404 when episode does not exist."""
        client, mock_session, _ = integration_client

        ep_id = uuid.uuid4()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=result)

        response = await client.get(f"/api/episodes/{ep_id}")

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "not_found"

    async def test_get_episode_invalid_uuid(self, integration_client):
        """GET /api/episodes/{id} returns 422 for malformed UUID."""
        client, _, _ = integration_client

        response = await client.get("/api/episodes/not-a-uuid")

        assert response.status_code == 422


class TestEpisodeDeleteEndpoint:
    """Test DELETE /api/episodes/{episode_id} — soft delete."""

    async def test_delete_episode_returns_204(self, integration_client):
        """DELETE /api/episodes/{id} returns 204 on success."""
        client, mock_session, _ = integration_client

        ep_id = uuid.uuid4()
        mock_ep = _make_mock_episode(ep_id=ep_id)
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_ep
        mock_session.execute = AsyncMock(return_value=result)

        response = await client.delete(f"/api/episodes/{ep_id}")

        assert response.status_code == 204
        # Verify soft_delete was called on the mock
        mock_ep.soft_delete.assert_called_once()

    async def test_delete_episode_not_found(self, integration_client):
        """DELETE /api/episodes/{id} returns 404 when not found."""
        client, mock_session, _ = integration_client

        ep_id = uuid.uuid4()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=result)

        response = await client.delete(f"/api/episodes/{ep_id}")

        assert response.status_code == 404


class TestEpisodeStatsEndpoint:
    """Test GET /api/episodes/stats — aggregated statistics."""

    async def test_episode_stats_returns_correct_shape(self, integration_client):
        """GET /api/episodes/stats returns 200 with camelCase aliased fields."""
        client, mock_session, _ = integration_client

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

        mock_session.execute = AsyncMock(
            side_effect=[mock_total, mock_avg, mock_trend, mock_tags, mock_para],
        )

        response = await client.get("/api/episodes/stats", params={"days": 30})

        assert response.status_code == 200
        data = response.json()
        # camelCase aliases from the EpisodeStats model
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


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


class TestAuthenticationEnforcement:
    """Verify that endpoints require a valid API key."""

    async def test_chat_without_api_key_returns_401(self):
        """POST /api/chat without X-API-Key header is rejected."""
        from src.app.api.deps import get_db
        from src.app.main import create_app
        from tests.integration.conftest import _null_lifespan

        app = create_app()

        mock_session = AsyncMock()

        async def override_db():
            yield mock_session

        app.dependency_overrides[get_db] = override_db
        # Do NOT override verify_api_key — let the real check run
        app.router.lifespan_context = _null_lifespan

        async with (
            __import__("httpx").AsyncClient(
                transport=__import__("httpx").ASGITransport(app=app),
                base_url="http://test",
            ) as client,
        ):
            response = await client.post(
                "/api/chat",
                json={"content": "hello", "source": "api"},
            )

        assert response.status_code == 401
        app.dependency_overrides.clear()


class TestEntryPointContracts:
    """Integration checks for attach/testing readiness entrypoints."""

    async def test_openapi_exposes_high_value_routes(self, integration_client):
        """The runtime OpenAPI document includes the key public routes."""
        client, _mock_session, _mock_anthropic = integration_client

        response = await client.get("/openapi.json")

        assert response.status_code == 200
        data = response.json()
        paths = data["paths"]

        for path in (
            "/api/chat",
            "/api/chat/stream",
            "/api/chat/context-inspect",
            "/api/dashboard/stats",
            "/api/dashboard/briefing",
            "/api/notes",
            "/api/notes/search",
            "/api/goals",
            "/health",
            "/health/preflight",
        ):
            assert path in paths

        assert "requestBody" in paths["/api/chat"]["post"]
        assert "200" in paths["/api/chat"]["post"]["responses"]
        assert "200" in paths["/api/dashboard/stats"]["get"]["responses"]
        assert "requestBody" in paths["/api/notes"]["post"]
        assert "requestBody" in paths["/api/goals"]["post"]
        assert "200" in paths["/health/preflight"]["get"]["responses"]

    async def test_health_preflight_uses_app_state_report(self):
        """The /health/preflight contract should surface startup readiness state."""
        from datetime import UTC, datetime

        from httpx import ASGITransport, AsyncClient

        from src.app.core.preflight import PreflightCheck, PreflightReport
        from src.app.main import create_app
        from tests.integration.conftest import _null_lifespan

        app = create_app()
        app.state.preflight_report = PreflightReport(
            status="warn",
            generated_at=datetime.now(UTC),
            checks=[
                PreflightCheck(
                    name="provider_configuration",
                    status="ok",
                    message="Required provider configuration is present",
                    required=True,
                    details={
                        "required": {"anthropic": True, "database": True},
                        "optional": {"telegram": False},
                        "missing_required": [],
                        "missing_optional": ["telegram"],
                    },
                ),
                PreflightCheck(
                    name="evaluation_assets",
                    status="warn",
                    message="Evaluation assets are missing optional examples",
                    required=False,
                ),
            ],
        )
        app.router.lifespan_context = _null_lifespan

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/health/preflight")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "warn"
        assert len(data["checks"]) == 2
        assert data["checks"][0]["name"] == "provider_configuration"
        assert data["checks"][1]["name"] == "evaluation_assets"

    async def test_episodes_without_api_key_returns_401(self):
        """GET /api/episodes without X-API-Key header is rejected."""
        from src.app.api.deps import get_db
        from src.app.main import create_app
        from tests.integration.conftest import _null_lifespan

        app = create_app()

        mock_session = AsyncMock()

        async def override_db():
            yield mock_session

        app.dependency_overrides[get_db] = override_db
        app.router.lifespan_context = _null_lifespan

        async with (
            __import__("httpx").AsyncClient(
                transport=__import__("httpx").ASGITransport(app=app),
                base_url="http://test",
            ) as client,
        ):
            response = await client.get("/api/episodes")

        assert response.status_code == 401
        app.dependency_overrides.clear()
