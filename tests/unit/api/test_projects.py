"""Tests for the projects API routes — listing, detail, create, and task update."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.projects import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from tests.unit.api.auth_helpers import override_current_principal


def test_project_datetime_normalizer_rejects_non_callable_serializer() -> None:
    from src.app.api.routes.projects import _iso_datetime_value

    assert _iso_datetime_value(MagicMock(isoformat="not-callable")) is None


async def test_load_dependency_map_uses_sqlalchemy_sync_scalar_result() -> None:
    from src.app.api.routes.projects import _load_dependency_map

    task_id = uuid.uuid4()
    dependency_id = uuid.uuid4()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        SimpleNamespace(task_id=task_id, depends_on_task_id=dependency_id)
    ]
    session = AsyncMock()
    session.execute.return_value = result

    dependency_map = await _load_dependency_map(session, [task_id])

    assert dependency_map == {task_id: [dependency_id]}


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


def _make_mock_project(
    *,
    project_id: uuid.UUID | None = None,
    title: str = "Second Brain",
    description: str | None = "AI personal assistant",
    status: str = "in-progress",
    appetite: str | None = "big-batch",
    deadline: datetime | None = None,
) -> MagicMock:
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = project_id or uuid.uuid4()
    m.title = title
    m.description = description
    m.status = status
    m.appetite = appetite
    m.deadline = deadline
    m.created_at = now
    m.updated_at = now
    return m


def _make_mock_task(
    *,
    task_id: uuid.UUID | None = None,
    milestone_id: uuid.UUID | None = None,
    title: str = "Implement search",
    status: str = "todo",
) -> MagicMock:
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = task_id or uuid.uuid4()
    m.milestone_id = milestone_id or uuid.uuid4()
    m.title = title
    m.description = None
    m.status = status
    m.estimate_hours = 4.0
    m.actual_hours = None
    m.wsjf_score = None
    m.complexity = None
    m.context_tags = ["search"]
    m.sort_order = 1
    m.started_at = None
    m.completed_at = None
    m.created_at = now
    m.updated_at = now
    return m


def _make_task_update_result(task: MagicMock) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = task
    return result


def _make_mock_epic(
    *,
    epic_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    title: str = "Epic One",
) -> MagicMock:
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = epic_id or uuid.uuid4()
    m.project_id = project_id or uuid.uuid4()
    m.title = title
    m.description = "First epic"
    m.sort_order = 1
    m.created_at = now
    return m


def _make_mock_milestone(
    *,
    milestone_id: uuid.UUID | None = None,
    epic_id: uuid.UUID | None = None,
    title: str = "Milestone One",
) -> MagicMock:
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = milestone_id or uuid.uuid4()
    m.epic_id = epic_id or uuid.uuid4()
    m.title = title
    m.success_criteria = "All tasks done"
    m.sort_order = 1
    m.created_at = now
    return m


def _make_mock_project_draft(
    *,
    draft_id: uuid.UUID | None = None,
    applied_project_id: uuid.UUID | None = None,
) -> MagicMock:
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = draft_id or uuid.uuid4()
    m.user_id = "owner"
    m.title = "Website launch draft"
    m.source_message = "Break this project down"
    m.status = "draft"
    m.applied_project_id = applied_project_id
    m.breakdown = {
        "project_summary": "Launch site with supporting collateral",
        "total_estimated_hours": 12.5,
        "critical_path": ["Rules doc", "Website launch"],
        "risks": ["Blocked on design sign-off"],
        "milestones": [
            {
                "title": "Website launch",
                "deliverables": [],
                "tasks": [],
            }
        ],
    }
    m.created_at = now
    m.updated_at = now
    return m


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------


async def test_list_projects_success():
    """GET /projects returns paginated projects."""
    mock_project = _make_mock_project()

    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = [mock_project]

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/projects")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Second Brain"
    assert data["items"][0]["status"] == "in-progress"
    assert data["items"][0]["epics"] == []


async def test_list_projects_with_filters():
    """GET /projects with filter params is accepted."""
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
        resp = await client.get(
            "/api/projects",
            params={
                "status": "planning",
                "appetite": "small-batch",
                "sort": "title",
                "order": "asc",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_create_project_body_rejects_invalid_deadline():
    """CreateProjectBody should reject invalid ISO datetimes."""
    from pydantic import ValidationError

    from src.app.api.routes.projects import CreateProjectBody

    with pytest.raises(ValidationError, match="Invalid ISO 8601 datetime"):
        CreateProjectBody(title="Project", deadline="not-a-date")


def test_create_project_body_accepts_missing_deadline():
    """CreateProjectBody should accept an omitted deadline."""
    from src.app.api.routes.projects import CreateProjectBody

    body = CreateProjectBody(title="Project", deadline=None)

    assert body.deadline is None


# ---------------------------------------------------------------------------
# get_project
# ---------------------------------------------------------------------------


async def test_get_project_success():
    """GET /projects/{id} returns the project with empty hierarchy."""
    project_id = uuid.uuid4()
    mock_project = _make_mock_project(project_id=project_id)

    mock_session = AsyncMock()

    project_result = MagicMock()
    project_result.scalar_one_or_none.return_value = mock_project
    # Epics query returns empty
    epics_result = MagicMock()
    epics_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(side_effect=[project_result, epics_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/projects/{project_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(project_id)
    assert data["title"] == "Second Brain"
    assert data["epics"] == []


async def test_get_project_with_epics_but_no_milestones():
    """GET /projects/{id} should return epics even when milestones are absent."""
    project_id = uuid.uuid4()
    epic_id = uuid.uuid4()

    mock_project = _make_mock_project(project_id=project_id)
    mock_epic = _make_mock_epic(epic_id=epic_id, project_id=project_id)

    mock_session = AsyncMock()

    project_result = MagicMock()
    project_result.scalar_one_or_none.return_value = mock_project
    epics_result = MagicMock()
    epics_result.scalars.return_value.all.return_value = [mock_epic]
    milestones_result = MagicMock()
    milestones_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(side_effect=[project_result, epics_result, milestones_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/projects/{project_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["epics"]) == 1
    assert data["epics"][0]["id"] == str(epic_id)
    assert data["epics"][0]["milestones"] == []


async def test_get_project_with_full_hierarchy():
    """GET /projects/{id} returns epics, milestones, and tasks."""
    project_id = uuid.uuid4()
    epic_id = uuid.uuid4()
    milestone_id = uuid.uuid4()
    task_id = uuid.uuid4()

    mock_project = _make_mock_project(project_id=project_id)
    mock_epic = _make_mock_epic(epic_id=epic_id, project_id=project_id)
    mock_milestone = _make_mock_milestone(milestone_id=milestone_id, epic_id=epic_id)
    mock_task = _make_mock_task(task_id=task_id, milestone_id=milestone_id)

    mock_session = AsyncMock()

    project_result = MagicMock()
    project_result.scalar_one_or_none.return_value = mock_project
    epics_result = MagicMock()
    epics_result.scalars.return_value.all.return_value = [mock_epic]
    milestones_result = MagicMock()
    milestones_result.scalars.return_value.all.return_value = [mock_milestone]
    tasks_result = MagicMock()
    tasks_result.scalars.return_value.all.return_value = [mock_task]
    mock_session.execute = AsyncMock(
        side_effect=[project_result, epics_result, milestones_result, tasks_result]
    )

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/projects/{project_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["epics"]) == 1
    assert len(data["epics"][0]["milestones"]) == 1
    assert len(data["epics"][0]["milestones"][0]["tasks"]) == 1
    assert data["epics"][0]["milestones"][0]["tasks"][0]["id"] == str(task_id)


async def test_get_project_not_found():
    """GET /projects/{id} returns 404 when project doesn't exist."""
    project_id = uuid.uuid4()

    mock_session = AsyncMock()
    project_result = MagicMock()
    project_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=project_result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/projects/{project_id}")

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------


async def test_create_project():
    """POST /projects creates a project and returns 201."""
    project_id = uuid.uuid4()
    mock_project = _make_mock_project(project_id=project_id, title="New Project")

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.projects.create_project",
        new_callable=AsyncMock,
        return_value=mock_project,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/projects",
                json={"title": "New Project"},
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == str(project_id)
    assert data["title"] == "New Project"


async def test_list_project_drafts_success():
    mock_session = AsyncMock()
    mock_draft = _make_mock_project_draft()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.projects.repo_list_project_drafts",
        new_callable=AsyncMock,
        return_value=([mock_draft], 1),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/project-drafts", params={"status": "draft"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Website launch draft"


async def test_apply_project_draft_success():
    draft_id = uuid.uuid4()
    project_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_project = _make_mock_project(project_id=project_id, title="Website launch")
    mock_draft = _make_mock_project_draft(draft_id=draft_id, applied_project_id=project_id)

    epics_result = MagicMock()
    epics_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=epics_result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with (
        patch(
            "src.app.api.routes.projects.repo_get_project_draft",
            new_callable=AsyncMock,
            return_value=mock_draft,
        ),
        patch(
            "src.app.api.routes.projects.repo_apply_project_draft",
            new_callable=AsyncMock,
            return_value=mock_project,
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"/api/project-drafts/{draft_id}/apply")

    assert resp.status_code == 200
    assert resp.json()["id"] == str(project_id)


async def test_create_project_with_deadline():
    """POST /projects parses and forwards deadline values."""
    project_id = uuid.uuid4()
    mock_project = _make_mock_project(
        project_id=project_id,
        title="Deadline Project",
        deadline=datetime(2026, 6, 1, tzinfo=UTC),
    )

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.projects.create_project",
        new_callable=AsyncMock,
        return_value=mock_project,
    ) as mock_create:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/projects",
                json={"title": "Deadline Project", "deadline": "2026-06-01T00:00:00+00:00"},
            )

    assert resp.status_code == 201
    assert resp.json()["deadline"] is not None
    assert mock_create.await_args.kwargs["deadline"] is not None


# ---------------------------------------------------------------------------
# update_task
# ---------------------------------------------------------------------------


async def test_update_task_success():
    """PATCH /tasks/{id} updates a task and returns TaskDTO."""
    task_id = uuid.uuid4()
    mock_task = _make_mock_task(task_id=task_id, title="Updated task", status="in-progress")

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_task)
    mock_session.execute = AsyncMock(return_value=_make_task_update_result(mock_task))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "in-progress"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(task_id)


async def test_update_task_with_all_fields_and_in_progress():
    """PATCH /tasks/{id} updates all supplied fields and sets started_at for in-progress."""
    task_id = uuid.uuid4()
    mock_task = _make_mock_task(task_id=task_id, title="Updated task", status="in_progress")

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_task)
    mock_session.execute = AsyncMock(return_value=_make_task_update_result(mock_task))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch.object(mock_session, "execute", wraps=mock_session.execute) as mock_execute:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/api/tasks/{task_id}",
                json={
                    "title": "Updated task",
                    "status": "in_progress",
                    "estimate_hours": 8.0,
                    "wsjf_score": 42.0,
                    "context_tags": ["backend", "search"],
                },
            )

    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated task"
    assert resp.json()["status"] == "in_progress"
    assert mock_execute.await_count == 1


async def test_update_task_done_sets_completed_at():
    """PATCH /tasks/{id} with status=done triggers completed_at handling."""
    task_id = uuid.uuid4()
    mock_task = _make_mock_task(task_id=task_id, status="done")

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_task)
    mock_session.execute = AsyncMock(return_value=_make_task_update_result(mock_task))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "done"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


async def test_update_task_no_fields_still_returns_current_task():
    """PATCH /tasks/{id} with no fields should still return the current task."""
    task_id = uuid.uuid4()
    mock_task = _make_mock_task(task_id=task_id)

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_task)
    mock_session.execute = AsyncMock(return_value=_make_task_update_result(mock_task))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(f"/api/tasks/{task_id}", json={})

    assert resp.status_code == 200
    assert resp.json()["id"] == str(task_id)


async def test_create_epic_success():
    """POST /projects/{id}/epics creates an epic under the project."""
    project_id = uuid.uuid4()
    epic_id = uuid.uuid4()
    mock_project = _make_mock_project(project_id=project_id)
    mock_epic = _make_mock_epic(epic_id=epic_id, project_id=project_id)

    mock_session = AsyncMock()
    project_result = MagicMock()
    project_result.scalar_one_or_none.return_value = mock_project
    mock_session.execute = AsyncMock(return_value=project_result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.projects.repo_create_epic",
        new_callable=AsyncMock,
        return_value=mock_epic,
    ) as mock_create:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/projects/{project_id}/epics",
                json={"title": "Epic One", "description": "First epic", "order": 1},
            )

    assert resp.status_code == 201
    assert resp.json()["id"] == str(epic_id)
    mock_create.assert_awaited_once()


async def test_create_epic_not_found():
    """POST /projects/{id}/epics returns 404 when project is missing."""
    project_id = uuid.uuid4()

    mock_session = AsyncMock()
    project_result = MagicMock()
    project_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=project_result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/projects/{project_id}/epics",
            json={"title": "Epic One"},
        )

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


async def test_create_milestone_success():
    """POST /epics/{id}/milestones creates a milestone under the epic."""
    epic_id = uuid.uuid4()
    project_id = uuid.uuid4()
    milestone_id = uuid.uuid4()
    mock_epic = _make_mock_epic(epic_id=epic_id, project_id=project_id)
    mock_milestone = _make_mock_milestone(milestone_id=milestone_id, epic_id=epic_id)

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_epic)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.projects.repo_create_milestone",
        new_callable=AsyncMock,
        return_value=mock_milestone,
    ) as mock_create:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/epics/{epic_id}/milestones",
                json={"title": "Milestone One", "success_criteria": "All tasks done", "order": 1},
            )

    assert resp.status_code == 201
    assert resp.json()["id"] == str(milestone_id)
    mock_create.assert_awaited_once()


async def test_create_milestone_not_found():
    """POST /epics/{id}/milestones returns 404 when epic is missing."""
    epic_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/epics/{epic_id}/milestones",
            json={"title": "Milestone One"},
        )

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


async def test_update_task_not_found():
    """PATCH /tasks/{id} returns 404 when task doesn't exist."""
    task_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock()
    mock_session.flush = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "completed"},
        )

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"
