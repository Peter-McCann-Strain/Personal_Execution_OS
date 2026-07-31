"""Tests for the dashboard API routes — stats, briefing, trends, recent items."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.dashboard import router
from src.app.core.exceptions import (
    EXCEPTION_STATUS_MAP,
    AppError,
    ConnectorBackendError,
    ConnectorRateLimitedError,
    ConnectorTokenExpiredError,
    ConnectorUnknownError,
    ErrorResponse,
)
from tests.unit.api.auth_helpers import override_current_principal

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _mock_get_db():
    yield AsyncMock()


def _build_app(*, override_auth: bool = True) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_db] = _mock_get_db

    if override_auth:
        override_current_principal(app)

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.include_router(router, prefix="/api")
    return app


def _make_mock_episode(*, content: str = "Test entry") -> MagicMock:
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = uuid.uuid4()
    m.content = content
    m.summary = "Summary"
    m.episode_type = "diary"
    m.para_category = None
    m.mood_score = 7.0
    m.energy_rating = 6.5
    m.tags = []
    m.people_mentioned = []
    m.source = "api"
    m.created_at = now
    return m


def _make_mock_action() -> MagicMock:
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = uuid.uuid4()
    m.agent_name = "diary"
    m.action_type = "process"
    m.model_used = "claude-haiku"
    m.tokens_in = 100
    m.tokens_out = 200
    m.cost_usd = 0.001
    m.duration_ms = 500
    m.input_summary = "Input"
    m.output_summary = "Output"
    m.trace_id = "trace-123"
    m.created_at = now
    return m


def _make_mock_goal() -> MagicMock:
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = uuid.uuid4()
    m.title = "Learn Rust"
    m.goal_type = "quarterly"
    m.parent_id = None
    m.priority = 1
    m.status = "active"
    m.progress = 0.5
    m.deadline = None
    m.evidence = []
    m.created_at = now
    m.updated_at = now
    return m


# ---------------------------------------------------------------------------
# dashboard_stats
# ---------------------------------------------------------------------------


async def test_dashboard_stats():
    """GET /dashboard/stats returns stat cards."""
    mock_session = AsyncMock()

    # avg mood query
    mood_result = MagicMock()
    mood_result.scalar.return_value = 7.3

    # active project count
    project_result = MagicMock()
    project_result.scalar.return_value = 3

    mock_session.execute = AsyncMock(side_effect=[mood_result, project_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch("src.app.api.routes.dashboard.get_settings", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/stats")

    assert resp.status_code == 200
    data = resp.json()
    assert "mood" in data
    assert "projects" in data
    assert "emails" in data
    assert "events" in data
    assert data["mood"]["value"] == 7.3
    assert data["projects"]["value"] == 3.0
    assert data["emails"]["status"] == "not_configured"
    assert data["events"]["status"] == "not_configured"
    assert data["events"]["value"] is None


async def test_dashboard_stats_null_mood():
    """GET /dashboard/stats handles null mood gracefully."""
    mock_session = AsyncMock()

    mood_result = MagicMock()
    mood_result.scalar.return_value = None

    project_result = MagicMock()
    project_result.scalar.return_value = 0

    mock_session.execute = AsyncMock(side_effect=[mood_result, project_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch("src.app.api.routes.dashboard.get_settings", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/stats")

    assert resp.status_code == 200
    data = resp.json()
    assert data["mood"]["value"] is None


async def test_dashboard_stats_google_and_content_configured():
    """GET /dashboard/stats uses the configured messaging branch when integrations exist."""
    mock_session = AsyncMock()

    mood_result = MagicMock()
    mood_result.scalar.return_value = 6.2

    project_result = MagicMock()
    project_result.scalar.return_value = 2

    mock_session.execute = AsyncMock(side_effect=[mood_result, project_result])

    mock_settings = MagicMock()
    mock_settings.google_configured = True
    mock_settings.tavily_configured = True
    mock_settings.user_timezone = "Europe/London"

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with (
        patch("src.app.api.routes.dashboard.get_settings", return_value=mock_settings),
        patch(
            "src.app.api.routes.dashboard._get_unread_email_count",
            new_callable=AsyncMock,
            side_effect=ConnectorTokenExpiredError("gmail token expired", connector="gmail"),
        ),
        patch(
            "src.app.api.routes.dashboard._get_todays_calendar_events",
            new_callable=AsyncMock,
            side_effect=ConnectorBackendError("calendar 503", connector="calendar"),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/stats")

    assert resp.status_code == 200
    data = resp.json()
    # Gmail tile reports a token-expired, actionable failure.
    assert data["emails"]["status"] == "unavailable"
    assert data["emails"]["errorCategory"] == "token_expired"
    assert data["emails"]["actionable"] is True
    assert data["emails"]["actionUrl"] == "/connectors/google"
    assert "Reconnect" in data["emails"]["message"] or "expired" in data["emails"]["message"]
    # Calendar tile reports a backend (5xx) failure — not actionable.
    assert data["events"]["status"] == "unavailable"
    assert data["events"]["errorCategory"] == "backend_error"
    assert data["events"]["actionable"] is False
    assert data["events"]["actionUrl"] is None


async def test_dashboard_stats_rate_limited_and_unknown_categories():
    """GET /dashboard/stats reports rate_limited / unknown when raised."""
    mock_session = AsyncMock()

    mood_result = MagicMock()
    mood_result.scalar.return_value = 6.0
    project_result = MagicMock()
    project_result.scalar.return_value = 1
    mock_session.execute = AsyncMock(side_effect=[mood_result, project_result])

    mock_settings = MagicMock()
    mock_settings.google_configured = True
    mock_settings.tavily_configured = False
    mock_settings.user_timezone = "Europe/London"

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with (
        patch("src.app.api.routes.dashboard.get_settings", return_value=mock_settings),
        patch(
            "src.app.api.routes.dashboard._get_unread_email_count",
            new_callable=AsyncMock,
            side_effect=ConnectorRateLimitedError("429", connector="gmail"),
        ),
        patch(
            "src.app.api.routes.dashboard._get_todays_calendar_events",
            new_callable=AsyncMock,
            side_effect=ConnectorUnknownError("boom", connector="calendar"),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/stats")

    assert resp.status_code == 200
    data = resp.json()
    assert data["emails"]["errorCategory"] == "rate_limited"
    assert data["emails"]["actionable"] is False
    assert data["events"]["errorCategory"] == "unknown"
    assert data["events"]["actionable"] is False


async def test_dashboard_stats_get_settings_failure():
    """GET /dashboard/stats falls back cleanly when settings lookup fails."""
    mock_session = AsyncMock()

    mood_result = MagicMock()
    mood_result.scalar.return_value = 5.0

    project_result = MagicMock()
    project_result.scalar.return_value = 1

    mock_session.execute = AsyncMock(side_effect=[mood_result, project_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.dashboard.get_settings",
        side_effect=RuntimeError("boom"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/stats")

    assert resp.status_code == 200
    data = resp.json()
    assert data["emails"]["status"] == "not_configured"


# ---------------------------------------------------------------------------
# morning_briefing
# ---------------------------------------------------------------------------


async def test_morning_briefing():
    """GET /dashboard/briefing returns greeting and empty schedule."""
    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.dashboard._get_priority_notifications",
        new_callable=AsyncMock,
        return_value=[],
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/briefing")

    assert resp.status_code == 200
    data = resp.json()
    assert "greeting" in data
    assert "schedule" in data
    assert "notifications" in data
    assert "content" in data
    assert "status" in data
    assert "notices" in data
    assert data["greeting"]["summary"] == "Your briefing is ready."


async def test_morning_briefing_configured_afternoon():
    """GET /dashboard/briefing takes the configured branch and afternoon greeting."""
    mock_session = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.google_configured = True
    mock_settings.tavily_configured = True
    mock_settings.user_timezone = "Europe/London"

    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 16, 18, 30, 0, tzinfo=tz)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with (
        patch("src.app.api.routes.dashboard.get_settings", return_value=mock_settings),
        patch("src.app.api.routes.dashboard.datetime", _FakeDateTime),
        patch(
            "src.app.api.routes.dashboard._get_todays_calendar_events",
            new_callable=AsyncMock,
            side_effect=ConnectorTokenExpiredError("calendar token expired", connector="calendar"),
        ),
        patch(
            "src.app.api.routes.dashboard._get_priority_notifications",
            new_callable=AsyncMock,
            side_effect=RuntimeError("notifications unavailable"),
        ),
        patch(
            "src.app.api.routes.dashboard._get_curated_content",
            new_callable=AsyncMock,
            side_effect=RuntimeError("content unavailable"),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/briefing")

    assert resp.status_code == 200
    data = resp.json()
    assert data["greeting"]["greeting"] == "Good evening"
    assert data["status"] == "partial"
    assert {notice["status"] for notice in data["notices"]} == {"unavailable"}
    # The calendar notice should now carry a categorised, actionable payload.
    calendar_notice = next(n for n in data["notices"] if n["source"] == "calendar")
    assert calendar_notice["errorCategory"] == "token_expired"
    assert calendar_notice["actionable"] is True
    assert calendar_notice["actionUrl"] == "/connectors/google"


async def test_morning_briefing_morning_branch():
    """GET /dashboard/briefing takes the morning greeting branch."""
    mock_session = AsyncMock()

    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 16, 9, 15, 0, tzinfo=tz)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with (
        patch("src.app.api.routes.dashboard.get_settings", side_effect=RuntimeError("boom")),
        patch("src.app.api.routes.dashboard.datetime", _FakeDateTime),
        patch(
            "src.app.api.routes.dashboard._get_priority_notifications",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/briefing")

    assert resp.status_code == 200
    data = resp.json()
    assert data["greeting"]["greeting"] == "Good morning"
    assert data["status"] == "not_configured"


# ---------------------------------------------------------------------------
# mood_energy_trends
# ---------------------------------------------------------------------------


async def test_mood_energy_trends():
    """GET /dashboard/trends/mood-energy returns time series points."""
    mock_session = AsyncMock()

    mock_row = MagicMock()
    mock_row.date = "2026-03-15"
    mock_row.mood = 7.5
    mock_row.energy = 6.8

    result = MagicMock()
    result.all.return_value = [mock_row]
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/dashboard/trends/mood-energy", params={"days": 7})

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["date"] == "2026-03-15"
    assert data[0]["mood"] == 7.5


# ---------------------------------------------------------------------------
# recent_diary_entries
# ---------------------------------------------------------------------------


async def test_recent_diary_entries():
    """GET /dashboard/diary/recent returns episodes."""
    mock_ep = _make_mock_episode(content="Morning walk")

    mock_session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [mock_ep]
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/dashboard/diary/recent")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["content"] == "Morning walk"


# ---------------------------------------------------------------------------
# active_goals
# ---------------------------------------------------------------------------


async def test_active_goals():
    """GET /dashboard/goals returns active goals via repository."""
    mock_goal = _make_mock_goal()

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.dashboard.list_goals",
        new_callable=AsyncMock,
        return_value=[mock_goal],
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/dashboard/goals")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["title"] == "Learn Rust"


# ---------------------------------------------------------------------------
# recent_agent_activity
# ---------------------------------------------------------------------------


async def test_recent_activity():
    """GET /dashboard/activity/recent returns agent actions."""
    mock_action = _make_mock_action()

    mock_session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [mock_action]
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/dashboard/activity/recent")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["agent_name"] == "diary"
