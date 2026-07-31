"""Integration tests for goals endpoints through the full FastAPI app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_goal(
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
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    goal = MagicMock()
    goal.id = goal_id or uuid.uuid4()
    goal.title = title
    goal.goal_type = goal_type
    goal.parent_id = parent_id
    goal.priority = priority
    goal.status = status
    goal.progress = progress
    goal.deadline = deadline
    goal.evidence = evidence or []
    goal.created_at = now
    goal.updated_at = now
    return goal


class TestGoalsContracts:
    """Verify goals response contracts through the real app router."""

    async def test_list_goals_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [_make_goal()]
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

        response = await client.get("/api/goals")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "Learn Rust"
        assert data["items"][0]["progress"] == 0.35

    async def test_get_goal_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        goal_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.goals.repo_get_goal_by_id",
            new_callable=AsyncMock,
            return_value=_make_goal(goal_id=goal_id),
        ):
            response = await client.get(f"/api/goals/{goal_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(goal_id)
        assert data["title"] == "Learn Rust"

    async def test_create_goal_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        parent_id = uuid.uuid4()
        goal_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.goals.repo_create_goal",
            new_callable=AsyncMock,
            return_value=_make_goal(goal_id=goal_id, parent_id=parent_id),
        ) as create_goal:
            response = await client.post(
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

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(goal_id)
        assert data["parent_id"] == str(parent_id)
        create_goal.assert_awaited_once()
        mock_session.refresh.assert_awaited()

    async def test_get_child_goals_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        parent_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.goals.repo_get_child_goals",
            new_callable=AsyncMock,
            return_value=[_make_goal(parent_id=parent_id, title="Finish chapter 1")],
        ) as get_children:
            response = await client.get(f"/api/goals/{parent_id}/children")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Finish chapter 1"
        get_children.assert_awaited_once_with(mock_session, parent_id=parent_id)

    async def test_update_goal_progress_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        goal_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.goals.update_goal",
            new_callable=AsyncMock,
            return_value=_make_goal(goal_id=goal_id, progress=0.75),
        ):
            response = await client.patch(
                f"/api/goals/{goal_id}",
                json={"progress": 0.75},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(goal_id)
        assert data["progress"] == 0.75
        mock_session.refresh.assert_awaited()

    async def test_delete_goal_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        goal_id = uuid.uuid4()
        goal = _make_goal(goal_id=goal_id)
        goal.soft_delete = MagicMock()

        with patch(
            "src.app.api.routes.goals.repo_get_goal_by_id",
            new_callable=AsyncMock,
            return_value=goal,
        ):
            response = await client.delete(f"/api/goals/{goal_id}")

        assert response.status_code == 204
        goal.soft_delete.assert_called_once_with()

    async def test_get_goal_not_found_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        goal_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.goals.repo_get_goal_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"/api/goals/{goal_id}")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"
