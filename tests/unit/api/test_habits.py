"""Tests for the habit tracking endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.habits import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from tests.unit.api.auth_helpers import override_current_principal

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _mock_get_db():
    """Yield a mock session so routes don't need a real DB."""
    yield AsyncMock()


def _build_app(*, override_auth: bool = True) -> FastAPI:
    """Create a minimal FastAPI app with the habits router for testing."""
    app = FastAPI()
    app.dependency_overrides[get_db] = _mock_get_db

    if override_auth:
        override_current_principal(app)

    # Register the AppError handler so NotFoundError -> 404 works.
    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.include_router(router, prefix="/api")
    return app


def _make_mock_habit(
    *,
    habit_id: uuid.UUID | None = None,
    name: str = "Meditate",
    description: str | None = "10 minutes daily",
    frequency: str = "daily",
    frequency_days: int = 1,
    current_streak: int = 5,
    longest_streak: int = 12,
    total_completions: int = 30,
    active: bool = True,
    tags: list[str] | None = None,
) -> MagicMock:
    """Build a MagicMock that behaves like a Habit ORM instance."""
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = habit_id or uuid.uuid4()
    m.name = name
    m.description = description
    m.frequency = frequency
    m.frequency_days = frequency_days
    m.current_streak = current_streak
    m.longest_streak = longest_streak
    m.total_completions = total_completions
    m.last_completed_at = now
    m.active = active
    m.tags = tags or ["wellness"]
    m.created_at = now
    m.updated_at = now
    return m


def _make_mock_habit_log(
    *,
    habit_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build a MagicMock that behaves like a HabitLog ORM instance."""
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = uuid.uuid4()
    m.habit_id = habit_id or uuid.uuid4()
    m.completed_at = now
    m.note = "Felt great today"
    m.source = "manual"
    return m


# ---------------------------------------------------------------------------
# list_habits
# ---------------------------------------------------------------------------


async def test_list_habits_success():
    """GET /habits returns a list of HabitDTOs."""
    mock_habit = _make_mock_habit()

    app = _build_app()

    with patch(
        "src.app.api.routes.habits.repo_get_active_habits",
        new_callable=AsyncMock,
        return_value=[mock_habit],
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/habits")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "Meditate"
    assert data[0]["current_streak"] == 5
    assert data[0]["longest_streak"] == 12


async def test_list_habits_empty():
    """GET /habits returns empty list when no active habits exist."""
    app = _build_app()

    with patch(
        "src.app.api.routes.habits.repo_get_active_habits",
        new_callable=AsyncMock,
        return_value=[],
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/habits")

    assert resp.status_code == 200
    data = resp.json()
    assert data == []


# ---------------------------------------------------------------------------
# create_habit
# ---------------------------------------------------------------------------


async def test_create_habit():
    """POST /habits creates a habit and returns 201 with HabitDTO."""
    habit_id = uuid.uuid4()
    mock_habit = _make_mock_habit(habit_id=habit_id, name="Exercise")

    mock_session = AsyncMock()
    mock_session.begin = MagicMock(return_value=AsyncMock())
    mock_session.refresh = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.habits.repo_create_habit",
        new_callable=AsyncMock,
        return_value=mock_habit,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/habits",
                json={"name": "Exercise", "frequency": "daily", "frequency_days": 1},
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == str(habit_id)
    assert data["name"] == "Exercise"


# ---------------------------------------------------------------------------
# get_habit
# ---------------------------------------------------------------------------


async def test_get_habit_success():
    """GET /habits/{id} returns a HabitDTO for an existing habit."""
    habit_id = uuid.uuid4()
    mock_habit = _make_mock_habit(habit_id=habit_id)

    app = _build_app()

    with patch(
        "src.app.api.routes.habits.repo_get_habit_by_id",
        new_callable=AsyncMock,
        return_value=mock_habit,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/habits/{habit_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(habit_id)
    assert data["name"] == "Meditate"
    assert data["current_streak"] == 5


async def test_get_habit_not_found():
    """GET /habits/{id} returns 404 when the habit does not exist."""
    habit_id = uuid.uuid4()

    app = _build_app()

    with patch(
        "src.app.api.routes.habits.repo_get_habit_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/habits/{habit_id}")

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "not_found"


# ---------------------------------------------------------------------------
# complete_habit
# ---------------------------------------------------------------------------


async def test_complete_habit():
    """POST /habits/{id}/complete logs a completion and returns 201."""
    habit_id = uuid.uuid4()
    mock_habit = _make_mock_habit(habit_id=habit_id)
    mock_log = _make_mock_habit_log(habit_id=habit_id)

    mock_session = AsyncMock()
    mock_session.begin = MagicMock(return_value=AsyncMock())
    mock_session.refresh = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with (
        patch(
            "src.app.api.routes.habits.repo_get_habit_by_id",
            new_callable=AsyncMock,
            return_value=mock_habit,
        ),
        patch(
            "src.app.api.routes.habits.repo_log_habit_completion",
            new_callable=AsyncMock,
            return_value=mock_log,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/habits/{habit_id}/complete",
                json={"note": "Felt great today"},
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["habit_id"] == str(habit_id)
    assert data["source"] == "manual"
    assert data["note"] == "Felt great today"


async def test_complete_habit_not_found():
    """POST /habits/{id}/complete returns 404 when habit does not exist."""
    habit_id = uuid.uuid4()

    app = _build_app()

    with patch(
        "src.app.api.routes.habits.repo_get_habit_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/habits/{habit_id}/complete")

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "not_found"


# ---------------------------------------------------------------------------
# list_habit_logs
# ---------------------------------------------------------------------------


async def test_list_habit_logs():
    """GET /habits/{id}/logs returns a list of HabitLogDTOs."""
    habit_id = uuid.uuid4()
    mock_habit = _make_mock_habit(habit_id=habit_id)
    mock_log = _make_mock_habit_log(habit_id=habit_id)

    app = _build_app()

    with (
        patch(
            "src.app.api.routes.habits.repo_get_habit_by_id",
            new_callable=AsyncMock,
            return_value=mock_habit,
        ),
        patch(
            "src.app.api.routes.habits.repo_get_habit_logs",
            new_callable=AsyncMock,
            return_value=[mock_log],
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/habits/{habit_id}/logs")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["habit_id"] == str(habit_id)
    assert data[0]["note"] == "Felt great today"


async def test_list_habit_logs_not_found():
    """GET /habits/{id}/logs returns 404 when the habit does not exist."""
    habit_id = uuid.uuid4()

    app = _build_app()

    with patch(
        "src.app.api.routes.habits.repo_get_habit_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/habits/{habit_id}/logs")

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "not_found"
