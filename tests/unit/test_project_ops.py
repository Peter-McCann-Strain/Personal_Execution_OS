"""Tests for project_ops — start_task and generate_standup."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.app.agents.tools.project_ops import WIP_LIMIT, generate_standup, start_task


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock()


# ---------------------------------------------------------------------------
# start_task — under WIP limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.tools.project_ops.update_task_status", new_callable=AsyncMock)
@patch("src.app.agents.tools.project_ops.get_wip_count", new_callable=AsyncMock)
async def test_start_task_success(mock_wip, mock_update, mock_session):
    mock_wip.return_value = 1  # Under limit
    task_id = uuid.uuid4()

    result = await start_task(mock_session, task_id)

    assert result["status"] == "ok"
    assert result["message"] == "Task started"
    mock_update.assert_called_once_with(mock_session, task_id, "in_progress")


# ---------------------------------------------------------------------------
# start_task — at WIP limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.tools.project_ops.update_task_status", new_callable=AsyncMock)
@patch("src.app.agents.tools.project_ops.get_wip_count", new_callable=AsyncMock)
async def test_start_task_blocked_at_wip_limit(mock_wip, mock_update, mock_session):
    mock_wip.return_value = WIP_LIMIT  # At limit

    result = await start_task(mock_session, uuid.uuid4())

    assert result["status"] == "blocked"
    assert "WIP limit reached" in result["message"]
    mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# start_task — over WIP limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.tools.project_ops.update_task_status", new_callable=AsyncMock)
@patch("src.app.agents.tools.project_ops.get_wip_count", new_callable=AsyncMock)
async def test_start_task_blocked_over_wip_limit(mock_wip, mock_update, mock_session):
    mock_wip.return_value = WIP_LIMIT + 2  # Over limit

    result = await start_task(mock_session, uuid.uuid4())

    assert result["status"] == "blocked"
    mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# generate_standup — mixed task statuses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.tools.project_ops.get_project_tasks", new_callable=AsyncMock)
async def test_generate_standup(mock_get_tasks, mock_session):
    mock_get_tasks.return_value = [
        {"title": "Auth module", "status": "in_progress"},
        {"title": "API design", "status": "in_progress"},
        {"title": "DB setup", "status": "done"},
        {"title": "Deploy", "status": "done"},
        {"title": "Fix bug", "status": "blocked"},
    ]
    project_id = uuid.uuid4()

    standup = await generate_standup(mock_session, project_id)

    assert standup["in_progress"] == ["Auth module", "API design"]
    assert standup["completed"] == ["DB setup", "Deploy"]
    assert standup["blocked"] == ["Fix bug"]
    assert standup["wip_count"] == 2
    assert standup["wip_limit"] == WIP_LIMIT


# ---------------------------------------------------------------------------
# generate_standup — empty project
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.tools.project_ops.get_project_tasks", new_callable=AsyncMock)
async def test_generate_standup_empty(mock_get_tasks, mock_session):
    mock_get_tasks.return_value = []
    project_id = uuid.uuid4()

    standup = await generate_standup(mock_session, project_id)

    assert standup["in_progress"] == []
    assert standup["completed"] == []
    assert standup["blocked"] == []
    assert standup["wip_count"] == 0


# ---------------------------------------------------------------------------
# generate_standup — limits completed to 5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.tools.project_ops.get_project_tasks", new_callable=AsyncMock)
async def test_generate_standup_completed_limit(mock_get_tasks, mock_session):
    done_tasks = [{"title": f"Task {i}", "status": "done"} for i in range(10)]
    mock_get_tasks.return_value = done_tasks

    standup = await generate_standup(mock_session, uuid.uuid4())

    assert len(standup["completed"]) == 5
