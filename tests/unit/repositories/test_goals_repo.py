"""Tests for the goals repository — CRUD for goal hierarchy."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.domain.constants import GoalStatus
from src.app.persistence.models import Goal
from src.app.persistence.repositories.goals import (
    create_goal,
    delete_goal,
    get_child_goals,
    get_goal_by_id,
    list_goals,
    update_goal,
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


def _make_goal(**overrides) -> Goal:
    """Create a test Goal ORM object."""
    g = Goal()
    g.id = overrides.get("id", uuid.uuid4())
    g.title = overrides.get("title", "Ship personal assistant v1")
    g.goal_type = overrides.get("goal_type", "quarterly")
    g.parent_id = overrides.get("parent_id")
    g.priority = overrides.get("priority", 5)
    g.status = overrides.get("status", GoalStatus.ACTIVE)
    g.progress = overrides.get("progress", 0.0)
    g.deadline = overrides.get("deadline")
    g.evidence = overrides.get("evidence")
    g.created_at = overrides.get("created_at", datetime.now(UTC))
    g.updated_at = overrides.get("updated_at", datetime.now(UTC))
    return g


# ---------------------------------------------------------------------------
# create_goal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_goal_adds_and_flushes():
    """create_goal should call session.add() and session.flush()."""
    session = _make_session()

    result = await create_goal(session, title="Learn Rust")

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert isinstance(result, Goal)


@pytest.mark.asyncio
async def test_create_goal_sets_all_fields():
    """create_goal should set all provided fields on the Goal."""
    session = _make_session()
    deadline = datetime(2026, 6, 30, tzinfo=UTC)

    result = await create_goal(
        session,
        title="Write weekly review system",
        goal_type="monthly",
        parent_id=None,
        priority=2,
        deadline=deadline,
        evidence=["Prototype working"],
    )

    assert result.title == "Write weekly review system"
    assert result.goal_type == "monthly"
    assert result.priority == 2
    assert result.status == GoalStatus.ACTIVE
    assert result.progress == 0.0
    assert result.deadline == deadline
    assert result.evidence == ["Prototype working"]


@pytest.mark.asyncio
async def test_create_goal_with_parent():
    """create_goal should accept a parent_id for hierarchical goals."""
    session = _make_session()
    parent_id = uuid.uuid4()

    result = await create_goal(session, title="Sub-goal", parent_id=parent_id)

    assert result.parent_id == parent_id


@pytest.mark.asyncio
async def test_create_goal_invalid_deadline_raises():
    """create_goal should raise TypeError for non-datetime deadline."""
    session = _make_session()

    with pytest.raises(TypeError, match="deadline must be a datetime"):
        await create_goal(session, title="Bad deadline", deadline="2026-06-30")


@pytest.mark.asyncio
async def test_create_goal_defaults():
    """create_goal should use sensible defaults for optional fields."""
    session = _make_session()

    result = await create_goal(session, title="Minimal goal")

    assert result.goal_type is None
    assert result.parent_id is None
    assert result.priority == 5
    assert result.status == GoalStatus.ACTIVE
    assert result.progress == 0.0
    assert result.deadline is None
    assert result.evidence is None


# ---------------------------------------------------------------------------
# get_goal_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_goal_by_id_found():
    """get_goal_by_id should return the goal when it exists."""
    session = _make_session()
    goal = _make_goal(title="Found goal")
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = goal
    session.execute.return_value = result_proxy

    result = await get_goal_by_id(session, goal.id)

    session.execute.assert_awaited_once()
    assert result is goal


@pytest.mark.asyncio
async def test_get_goal_by_id_not_found():
    """get_goal_by_id should return None when goal doesn't exist."""
    session = _make_session()
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = None
    session.execute.return_value = result_proxy

    result = await get_goal_by_id(session, uuid.uuid4())

    session.execute.assert_awaited_once()
    assert result is None


# ---------------------------------------------------------------------------
# list_goals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_goals_no_filter():
    """list_goals should return all goals when no filter is applied."""
    session = _make_session()
    goals = [_make_goal(title="Goal A"), _make_goal(title="Goal B")]

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = goals
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await list_goals(session)

    assert len(result) == 2
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_goals_with_status_filter():
    """list_goals should filter by status when provided."""
    session = _make_session()
    active = _make_goal(title="Active", status=GoalStatus.ACTIVE)

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [active]
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await list_goals(session, status="active")

    assert len(result) == 1
    assert result[0].status == GoalStatus.ACTIVE


@pytest.mark.asyncio
async def test_list_goals_with_type_filter():
    """list_goals should filter by goal_type when provided."""
    session = _make_session()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await list_goals(session, goal_type="quarterly")

    assert result == []
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_goals_with_parent_filter():
    """list_goals should filter by parent_id when provided."""
    session = _make_session()
    parent_id = uuid.uuid4()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await list_goals(session, parent_id=parent_id)

    assert result == []


@pytest.mark.asyncio
async def test_list_goals_empty():
    """list_goals should return empty list when no goals exist."""
    session = _make_session()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await list_goals(session)

    assert result == []


# ---------------------------------------------------------------------------
# get_child_goals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_child_goals_returns_children():
    """get_child_goals should return direct child goals."""
    session = _make_session()
    parent_id = uuid.uuid4()
    child = _make_goal(title="Child goal", parent_id=parent_id)

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [child]
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await get_child_goals(session, parent_id)

    assert len(result) == 1
    assert result[0].parent_id == parent_id


@pytest.mark.asyncio
async def test_get_child_goals_empty():
    """get_child_goals should return empty list when no children exist."""
    session = _make_session()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await get_child_goals(session, uuid.uuid4())

    assert result == []


# ---------------------------------------------------------------------------
# update_goal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_goal_with_valid_fields():
    """update_goal should update allowed fields."""
    session = _make_session()
    goal = _make_goal(title="Updated goal", progress=0.5)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = goal
    session.execute.return_value = mock_result

    result = await update_goal(session, goal.id, title="Updated goal", progress=0.5)

    session.execute.assert_awaited_once()
    assert result.title == "Updated goal"
    assert result.progress == 0.5


@pytest.mark.asyncio
async def test_update_goal_not_found_raises():
    """update_goal should raise ValueError if goal not found."""
    session = _make_session()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    with pytest.raises(ValueError, match="Goal not found"):
        await update_goal(session, uuid.uuid4(), title="new title")


@pytest.mark.asyncio
async def test_update_goal_no_valid_kwargs_returns_goal():
    """update_goal with no valid kwargs should return the goal unchanged."""
    session = _make_session()
    goal = _make_goal()
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = goal
    session.execute.return_value = result_proxy

    result = await update_goal(session, goal.id, invalid_field="value")

    assert result is goal


@pytest.mark.asyncio
async def test_update_goal_no_valid_kwargs_not_found_raises():
    """update_goal with no valid kwargs should raise if goal not found."""
    session = _make_session()
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = None
    session.execute.return_value = result_proxy

    with pytest.raises(ValueError, match="Goal not found"):
        await update_goal(session, uuid.uuid4(), invalid_field="value")


# ---------------------------------------------------------------------------
# delete_goal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_goal_found():
    """delete_goal should return True when the goal is deleted."""
    session = _make_session()

    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute.return_value = mock_result

    result = await delete_goal(session, uuid.uuid4())

    assert result is True
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_goal_not_found():
    """delete_goal should return False when the goal doesn't exist."""
    session = _make_session()

    mock_result = MagicMock()
    mock_result.rowcount = 0
    session.execute.return_value = mock_result

    result = await delete_goal(session, uuid.uuid4())

    assert result is False
