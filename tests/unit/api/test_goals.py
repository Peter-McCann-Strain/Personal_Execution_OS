"""Tests for the goals API routes — listing, detail, and progress updates."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.goals import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
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


def _make_mock_goal(
    *,
    goal_id: uuid.UUID | None = None,
    title: str = "Learn Rust",
    goal_type: str | None = "quarterly",
    parent_id: uuid.UUID | None = None,
    priority: int = 1,
    status: str = "active",
    progress: float = 0.35,
    deadline: datetime | None = None,
    evidence: list[str] | None = None,
) -> MagicMock:
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = goal_id or uuid.uuid4()
    m.title = title
    m.goal_type = goal_type
    m.parent_id = parent_id
    m.priority = priority
    m.status = status
    m.progress = progress
    m.deadline = deadline
    m.evidence = evidence or []
    m.created_at = now
    m.updated_at = now
    return m


# ---------------------------------------------------------------------------
# list_goals
# ---------------------------------------------------------------------------


async def test_list_goals_success():
    """GET /goals returns paginated goals."""
    mock_goal = _make_mock_goal()

    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = [mock_goal]

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/goals")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Learn Rust"
    assert data["items"][0]["progress"] == 0.35


async def test_list_goals_empty():
    """GET /goals returns empty page when no goals exist."""
    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/goals")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["has_more"] is False


async def test_list_goals_with_filters_and_desc_sort():
    """GET /goals exercises the filtered descending sort branch."""
    mock_goal = _make_mock_goal(priority=8, status="active", goal_type="quarterly")

    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = [mock_goal]

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/goals",
            params={
                "status": "active",
                "goal_type": "quarterly",
                "sort": "deadline",
                "order": "desc",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["priority"] == 8


def test_create_goal_body_accepts_valid_deadline():
    """CreateGoalBody accepts ISO 8601 datetimes."""
    from src.app.api.routes.goals import CreateGoalBody

    body = CreateGoalBody(title="Ship it", deadline="2026-04-07T09:00:00+00:00")

    assert body.deadline == "2026-04-07T09:00:00+00:00"


def test_create_goal_body_rejects_invalid_deadline():
    """CreateGoalBody rejects invalid ISO 8601 datetimes."""
    from pydantic import ValidationError

    from src.app.api.routes.goals import CreateGoalBody

    with pytest.raises(ValidationError, match="Invalid ISO 8601 datetime"):
        CreateGoalBody(title="Ship it", deadline="tomorrow-ish")


def test_create_goal_body_accepts_none_deadline():
    """CreateGoalBody keeps the no-deadline branch intact."""
    from src.app.api.routes.goals import CreateGoalBody

    body = CreateGoalBody(title="Ship it", deadline=None)

    assert body.deadline is None


# ---------------------------------------------------------------------------
# get_goal
# ---------------------------------------------------------------------------


async def test_get_goal_success():
    """GET /goals/{id} returns the goal."""
    goal_id = uuid.uuid4()
    mock_goal = _make_mock_goal(goal_id=goal_id)

    mock_session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_goal
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/goals/{goal_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(goal_id)
    assert data["title"] == "Learn Rust"


async def test_get_goal_not_found():
    """GET /goals/{id} returns 404 when goal doesn't exist."""
    goal_id = uuid.uuid4()

    mock_session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/goals/{goal_id}")

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


# ---------------------------------------------------------------------------
# update_goal_progress
# ---------------------------------------------------------------------------


async def test_update_goal_progress():
    """PATCH /goals/{id} updates progress and returns updated goal."""
    goal_id = uuid.uuid4()
    mock_goal = _make_mock_goal(goal_id=goal_id, progress=0.75)

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.goals.update_goal",
        new_callable=AsyncMock,
        return_value=mock_goal,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/api/goals/{goal_id}",
                json={"progress": 0.75},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(goal_id)
    assert data["progress"] == 0.75


async def test_update_goal_not_found():
    """PATCH /goals/{id} returns 404 when goal doesn't exist."""
    goal_id = uuid.uuid4()

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.goals.update_goal",
        new_callable=AsyncMock,
        side_effect=ValueError(f"Goal not found: {goal_id}"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/api/goals/{goal_id}",
                json={"progress": 0.5},
            )

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


async def test_create_goal_success():
    """POST /goals creates a new goal and returns it."""
    parent_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    mock_goal = _make_mock_goal(goal_id=goal_id, parent_id=parent_id)

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.goals.repo_create_goal",
        new_callable=AsyncMock,
        return_value=mock_goal,
    ) as mock_create:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/goals",
                json={
                    "title": "Learn Rust",
                    "goal_type": "quarterly",
                    "parent_id": str(parent_id),
                    "priority": 3,
                    "deadline": "2026-04-07T10:00:00+00:00",
                    "evidence": ["Read The Book"],
                },
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == str(goal_id)
    assert data["parent_id"] == str(parent_id)
    mock_create.assert_awaited_once()


async def test_create_goal_minimal_payload():
    """POST /goals exercises the no-deadline, no-parent branch."""
    goal_id = uuid.uuid4()
    mock_goal = _make_mock_goal(goal_id=goal_id, goal_type=None, parent_id=None, deadline=None)

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.goals.repo_create_goal",
        new_callable=AsyncMock,
        return_value=mock_goal,
    ) as mock_create:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/goals",
                json={
                    "title": "Minimal goal",
                },
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == str(goal_id)
    assert data["deadline"] is None
    assert data["parent_id"] is None
    mock_create.assert_awaited_once()


async def test_get_child_goals_success():
    """GET /goals/{id}/children returns child goals."""
    parent_id = uuid.uuid4()
    child_goal = _make_mock_goal(parent_id=parent_id, title="Finish chapter 1")

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.goals.repo_get_child_goals",
        new_callable=AsyncMock,
        return_value=[child_goal],
    ) as mock_children:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/goals/{parent_id}/children")

    assert resp.status_code == 200
    assert resp.json()[0]["title"] == "Finish chapter 1"
    mock_children.assert_awaited_once_with(mock_session, parent_id=parent_id)


async def test_delete_goal_success():
    """DELETE /goals/{id} soft-deletes an existing goal."""
    goal_id = uuid.uuid4()
    mock_goal = _make_mock_goal(goal_id=goal_id)
    mock_goal.soft_delete = MagicMock()

    mock_session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_goal
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/api/goals/{goal_id}")

    assert resp.status_code == 204
    mock_goal.soft_delete.assert_called_once_with()


async def test_delete_goal_not_found():
    """DELETE /goals/{id} returns 404 when goal doesn't exist."""
    goal_id = uuid.uuid4()
    mock_session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/api/goals/{goal_id}")

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"
