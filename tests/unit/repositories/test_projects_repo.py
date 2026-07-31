"""Tests for the projects repository — projects, epics, milestones, tasks."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.domain.constants import ProjectStatus, TaskStatus
from src.app.persistence.models import Epic, Milestone, Project, Task
from src.app.persistence.repositories.projects import (
    create_epic,
    create_milestone,
    create_project,
    create_task,
    get_project_tasks,
    get_wip_count,
    update_task_status,
)

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


def _make_project(**overrides) -> Project:
    """Create a test Project ORM object."""
    p = Project()
    p.id = overrides.get("id", uuid.uuid4())
    p.title = overrides.get("title", "Personal Assistant")
    p.description = overrides.get("description", "AI second brain system")
    p.status = overrides.get("status", ProjectStatus.PLANNING)
    p.appetite = overrides.get("appetite", "6 weeks")
    p.deadline = overrides.get("deadline")
    p.created_at = overrides.get("created_at", datetime.now(UTC))
    p.updated_at = overrides.get("updated_at", datetime.now(UTC))
    return p


def _make_task(**overrides) -> Task:
    """Create a test Task ORM object."""
    t = Task()
    t.id = overrides.get("id", uuid.uuid4())
    t.milestone_id = overrides.get("milestone_id", uuid.uuid4())
    t.title = overrides.get("title", "Implement search")
    t.description = overrides.get("description")
    t.status = overrides.get("status", TaskStatus.BACKLOG)
    t.estimate_hours = overrides.get("estimate_hours")
    t.actual_hours = overrides.get("actual_hours")
    t.wsjf_score = overrides.get("wsjf_score")
    t.complexity = overrides.get("complexity")
    t.context_tags = overrides.get("context_tags")
    t.sort_order = overrides.get("sort_order", 0)
    t.started_at = overrides.get("started_at")
    t.completed_at = overrides.get("completed_at")
    t.created_at = overrides.get("created_at", datetime.now(UTC))
    t.updated_at = overrides.get("updated_at", datetime.now(UTC))
    return t


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_project_adds_and_flushes():
    """create_project should call session.add() and session.flush()."""
    session = _make_session()

    result = await create_project(session, title="New Project")

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert isinstance(result, Project)


@pytest.mark.asyncio
async def test_create_project_sets_fields():
    """create_project should set all provided fields."""
    session = _make_session()
    deadline = datetime(2026, 12, 31, tzinfo=UTC)

    result = await create_project(
        session,
        title="Deployment Pipeline",
        description="CI/CD for the assistant",
        deadline=deadline,
        appetite="2 weeks",
    )

    assert result.title == "Deployment Pipeline"
    assert result.description == "CI/CD for the assistant"
    assert result.status == ProjectStatus.PLANNING
    assert result.appetite == "2 weeks"
    assert result.deadline == deadline


@pytest.mark.asyncio
async def test_create_project_defaults():
    """create_project should use defaults for optional fields."""
    session = _make_session()

    result = await create_project(session, title="Minimal Project")

    assert result.description is None
    assert result.deadline is None
    assert result.appetite is None
    assert result.status == ProjectStatus.PLANNING


@pytest.mark.asyncio
async def test_create_project_invalid_deadline_raises():
    """create_project should raise TypeError for non-datetime deadline."""
    session = _make_session()

    with pytest.raises(TypeError, match="deadline must be a datetime"):
        await create_project(session, title="Bad", deadline="2026-12-31")


# ---------------------------------------------------------------------------
# create_epic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_epic_adds_and_flushes():
    """create_epic should call session.add() and session.flush()."""
    session = _make_session()
    project_id = uuid.uuid4()

    await create_epic(session, project_id=project_id, title="Core Infrastructure")

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, Epic)
    assert added.project_id == project_id
    assert added.title == "Core Infrastructure"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_epic_with_order():
    """create_epic should set sort_order."""
    session = _make_session()

    result = await create_epic(
        session,
        project_id=uuid.uuid4(),
        title="Phase 2",
        description="Multi-agent",
        order=2,
    )

    assert result.sort_order == 2
    assert result.description == "Multi-agent"


# ---------------------------------------------------------------------------
# create_milestone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_milestone_adds_and_flushes():
    """create_milestone should call session.add() and session.flush()."""
    session = _make_session()
    epic_id = uuid.uuid4()

    await create_milestone(
        session,
        epic_id=epic_id,
        title="BM25 Search Working",
        success_criteria="All search tests passing",
    )

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, Milestone)
    assert added.epic_id == epic_id
    assert added.title == "BM25 Search Working"
    assert added.success_criteria == "All search tests passing"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_milestone_defaults():
    """create_milestone should use defaults for optional fields."""
    session = _make_session()

    result = await create_milestone(session, epic_id=uuid.uuid4(), title="Minimal")

    assert result.success_criteria is None
    assert result.sort_order == 0


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_task_adds_and_flushes():
    """create_task should call session.add() and session.flush()."""
    session = _make_session()
    milestone_id = uuid.uuid4()

    await create_task(session, milestone_id=milestone_id, title="Write tests")

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, Task)
    assert added.milestone_id == milestone_id
    assert added.title == "Write tests"
    assert added.status == TaskStatus.BACKLOG
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_task_sets_all_fields():
    """create_task should set all provided fields."""
    session = _make_session()

    result = await create_task(
        session,
        milestone_id=uuid.uuid4(),
        title="Implement hybrid search",
        description="BM25 + vector with RRF",
        estimate_hours=4.0,
        complexity="medium",
        context_tags=["search", "backend"],
    )

    assert result.title == "Implement hybrid search"
    assert result.description == "BM25 + vector with RRF"
    assert result.estimate_hours == 4.0
    assert result.complexity == "medium"
    assert result.context_tags == ["search", "backend"]
    assert result.status == TaskStatus.BACKLOG


@pytest.mark.asyncio
async def test_create_task_defaults():
    """create_task should use defaults for optional fields."""
    session = _make_session()

    result = await create_task(session, milestone_id=uuid.uuid4(), title="Minimal task")

    assert result.description is None
    assert result.estimate_hours is None
    assert result.complexity is None
    assert result.context_tags is None


# ---------------------------------------------------------------------------
# update_task_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_task_status_valid():
    """update_task_status should update to a valid status."""
    session = _make_session()
    task = _make_task(status=TaskStatus.IN_PROGRESS)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = task
    session.execute.return_value = mock_result

    result = await update_task_status(session, task.id, TaskStatus.IN_PROGRESS)

    session.execute.assert_awaited_once()
    assert result is task


@pytest.mark.asyncio
async def test_update_task_status_to_done():
    """update_task_status should set completed_at when status is done."""
    session = _make_session()
    task = _make_task(status=TaskStatus.DONE)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = task
    session.execute.return_value = mock_result

    result = await update_task_status(session, task.id, TaskStatus.DONE)

    assert result is task


@pytest.mark.asyncio
async def test_update_task_status_invalid_raises():
    """update_task_status should raise ValueError for invalid status."""
    session = _make_session()

    with pytest.raises(ValueError, match="Invalid task status"):
        await update_task_status(session, uuid.uuid4(), "invalid_status")


@pytest.mark.asyncio
async def test_update_task_status_not_found_raises():
    """update_task_status should raise ValueError if task not found."""
    session = _make_session()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    with pytest.raises(ValueError, match="Task not found"):
        await update_task_status(session, uuid.uuid4(), TaskStatus.READY)


@pytest.mark.asyncio
async def test_update_task_status_all_valid_statuses():
    """update_task_status should accept all TaskStatus values."""
    session = _make_session()
    task = _make_task()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = task
    session.execute.return_value = mock_result

    for status in TaskStatus:
        await update_task_status(session, task.id, status)


# ---------------------------------------------------------------------------
# get_wip_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_wip_count_returns_count():
    """get_wip_count should return the count of in-progress tasks."""
    session = _make_session()

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 3
    session.execute.return_value = mock_result

    count = await get_wip_count(session)

    assert count == 3
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_wip_count_returns_zero():
    """get_wip_count should return 0 when no tasks are in progress."""
    session = _make_session()

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 0
    session.execute.return_value = mock_result

    count = await get_wip_count(session)

    assert count == 0


# ---------------------------------------------------------------------------
# get_project_tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_project_tasks_returns_dicts():
    """get_project_tasks should return a list of dicts with task + milestone info."""
    session = _make_session()
    task_id = uuid.uuid4()
    project_id = uuid.uuid4()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = [
        {
            "id": task_id,
            "title": "Write tests",
            "status": "backlog",
            "estimate_hours": 2.0,
            "actual_hours": None,
            "wsjf_score": 15.0,
            "context_tags": ["testing"],
            "complexity": "low",
            "milestone_title": "Core Infrastructure",
        }
    ]
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    results = await get_project_tasks(session, project_id)

    assert len(results) == 1
    assert results[0]["title"] == "Write tests"
    assert results[0]["milestone_title"] == "Core Infrastructure"
    assert results[0]["wsjf_score"] == 15.0


@pytest.mark.asyncio
async def test_get_project_tasks_empty():
    """get_project_tasks should return empty list when project has no tasks."""
    session = _make_session()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    results = await get_project_tasks(session, uuid.uuid4())

    assert results == []


@pytest.mark.asyncio
async def test_get_project_tasks_passes_project_id():
    """get_project_tasks should pass project_id to the SQL query."""
    session = _make_session()
    project_id = uuid.uuid4()

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    session.execute.return_value = mock_result

    await get_project_tasks(session, project_id)

    call_args = session.execute.call_args
    params = call_args[0][1]
    assert params["project_id"] == project_id
