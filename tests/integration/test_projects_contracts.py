"""Integration tests for projects endpoints through the full FastAPI app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_project(
    *,
    project_id: uuid.UUID | None = None,
    title: str = "Second Brain",
    description: str | None = "AI personal assistant",
    status: str = "in-progress",
    appetite: str | None = "big-batch",
    deadline: datetime | None = None,
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    project = MagicMock()
    project.id = project_id or uuid.uuid4()
    project.title = title
    project.description = description
    project.status = status
    project.appetite = appetite
    project.deadline = deadline
    project.created_at = now
    project.updated_at = now
    return project


def _make_epic(
    *,
    epic_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    title: str = "Epic One",
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    epic = MagicMock()
    epic.id = epic_id or uuid.uuid4()
    epic.project_id = project_id or uuid.uuid4()
    epic.title = title
    epic.description = "First epic"
    epic.sort_order = 1
    epic.created_at = now
    return epic


def _make_milestone(
    *,
    milestone_id: uuid.UUID | None = None,
    epic_id: uuid.UUID | None = None,
    title: str = "Milestone One",
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    milestone = MagicMock()
    milestone.id = milestone_id or uuid.uuid4()
    milestone.epic_id = epic_id or uuid.uuid4()
    milestone.title = title
    milestone.success_criteria = "All tasks done"
    milestone.sort_order = 1
    milestone.created_at = now
    return milestone


def _make_task(
    *,
    task_id: uuid.UUID | None = None,
    milestone_id: uuid.UUID | None = None,
    title: str = "Implement search",
    status: str = "todo",
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    task = MagicMock()
    task.id = task_id or uuid.uuid4()
    task.milestone_id = milestone_id or uuid.uuid4()
    task.title = title
    task.description = None
    task.status = status
    task.estimate_hours = 4.0
    task.actual_hours = None
    task.wsjf_score = None
    task.complexity = None
    task.context_tags = ["search"]
    task.sort_order = 1
    task.started_at = None
    task.completed_at = None
    task.created_at = now
    task.updated_at = now
    return task


class TestProjectsContracts:
    """Verify projects response contracts through the real app router."""

    async def test_list_projects_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [_make_project()]
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

        response = await client.get("/api/projects")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "Second Brain"
        assert data["items"][0]["epics"] == []

    async def test_list_projects_contract_with_filters(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

        response = await client.get(
            "/api/projects",
            params={
                "status": "planning",
                "appetite": "small-batch",
                "sort": "title",
                "order": "asc",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_get_project_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        project_id = uuid.uuid4()
        epic_id = uuid.uuid4()
        milestone_id = uuid.uuid4()
        task_id = uuid.uuid4()

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = _make_project(project_id=project_id)
        epics_result = MagicMock()
        epics_result.scalars.return_value.all.return_value = [
            _make_epic(epic_id=epic_id, project_id=project_id),
        ]
        milestones_result = MagicMock()
        milestones_result.scalars.return_value.all.return_value = [
            _make_milestone(milestone_id=milestone_id, epic_id=epic_id),
        ]
        tasks_result = MagicMock()
        tasks_result.scalars.return_value.all.return_value = [
            _make_task(task_id=task_id, milestone_id=milestone_id),
        ]
        dependencies_result = MagicMock()
        dependencies_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(
            side_effect=[
                project_result,
                epics_result,
                milestones_result,
                tasks_result,
                dependencies_result,
            ],
        )

        response = await client.get(f"/api/projects/{project_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(project_id)
        assert len(data["epics"]) == 1
        assert data["epics"][0]["id"] == str(epic_id)
        assert data["epics"][0]["milestones"][0]["tasks"][0]["id"] == str(task_id)

    async def test_get_project_contract_with_empty_hierarchy(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        project_id = uuid.uuid4()

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = _make_project(project_id=project_id)
        epics_result = MagicMock()
        epics_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[project_result, epics_result])

        response = await client.get(f"/api/projects/{project_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(project_id)
        assert data["epics"] == []

    async def test_create_project_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        project_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.projects.create_project",
            new_callable=AsyncMock,
            return_value=_make_project(project_id=project_id, title="New Project"),
        ) as create_project:
            response = await client.post(
                "/api/projects",
                json={"title": "New Project"},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(project_id)
        assert data["title"] == "New Project"
        create_project.assert_awaited_once()
        mock_session.refresh.assert_awaited()

    async def test_create_epic_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        project_id = uuid.uuid4()
        epic_id = uuid.uuid4()
        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = _make_project(project_id=project_id)
        mock_session.execute = AsyncMock(return_value=project_result)

        with patch(
            "src.app.api.routes.projects.repo_create_epic",
            new_callable=AsyncMock,
            return_value=_make_epic(epic_id=epic_id, project_id=project_id),
        ) as create_epic:
            response = await client.post(
                f"/api/projects/{project_id}/epics",
                json={"title": "Epic One", "description": "First epic", "order": 1},
            )

        assert response.status_code == 201
        assert response.json()["id"] == str(epic_id)
        create_epic.assert_awaited_once()
        mock_session.refresh.assert_awaited()

    async def test_create_milestone_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        epic_id = uuid.uuid4()
        project_id = uuid.uuid4()
        milestone_id = uuid.uuid4()
        mock_session.get = AsyncMock(
            return_value=_make_epic(epic_id=epic_id, project_id=project_id)
        )

        with patch(
            "src.app.api.routes.projects.repo_create_milestone",
            new_callable=AsyncMock,
            return_value=_make_milestone(milestone_id=milestone_id, epic_id=epic_id),
        ) as create_milestone:
            response = await client.post(
                f"/api/epics/{epic_id}/milestones",
                json={"title": "Milestone One", "success_criteria": "All tasks done", "order": 1},
            )

        assert response.status_code == 201
        assert response.json()["id"] == str(milestone_id)
        create_milestone.assert_awaited_once()
        mock_session.refresh.assert_awaited()

    async def test_update_task_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        task_id = uuid.uuid4()
        mock_task = _make_task(task_id=task_id, status="todo")

        async def _apply_update(_stmt):
            mock_task.status = "in_progress"
            mock_task.estimate_hours = 8.0
            result = MagicMock()
            result.scalar_one_or_none.return_value = mock_task
            return result

        mock_session.get = AsyncMock(return_value=mock_task)
        mock_session.execute = AsyncMock(side_effect=_apply_update)

        response = await client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "in-progress", "estimate_hours": 8.0},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(task_id)
        assert data["status"] == "in_progress"
        assert data["estimate_hours"] == 8.0

    async def test_get_project_not_found_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        project_id = uuid.uuid4()
        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=project_result)

        response = await client.get(f"/api/projects/{project_id}")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_create_epic_not_found_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        project_id = uuid.uuid4()
        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=project_result)

        response = await client.post(
            f"/api/projects/{project_id}/epics",
            json={"title": "Epic One"},
        )

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_create_milestone_not_found_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        epic_id = uuid.uuid4()
        mock_session.get = AsyncMock(return_value=None)

        response = await client.post(
            f"/api/epics/{epic_id}/milestones",
            json={"title": "Milestone One"},
        )

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_update_task_not_found_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        task_id = uuid.uuid4()
        mock_session.get = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock()

        response = await client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "done"},
        )

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"
