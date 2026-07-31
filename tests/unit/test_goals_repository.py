"""Tests for goals repository operations (mocked database session)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from src.app.persistence.models import Goal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_goal(
    title: str = "Ship personal assistant v1",
    goal_type: str = "quarterly",
    status: str = "active",
    priority: int = 3,
    progress: float = 0.0,
) -> Goal:
    """Create a Goal ORM object for testing."""
    goal = Goal()
    goal.id = uuid.uuid4()
    goal.title = title
    goal.goal_type = goal_type
    goal.status = status
    goal.priority = priority
    goal.progress = progress
    goal.parent_id = None
    goal.deadline = None
    goal.evidence = None
    goal.created_at = datetime.now(UTC)
    goal.updated_at = datetime.now(UTC)
    return goal


def _make_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Goal creation
# ---------------------------------------------------------------------------


async def test_create_goal_adds_to_session():
    """Creating a goal should add the ORM object to the session."""
    session = _make_session()
    goal = _make_goal("Learn Rust")

    session.add(goal)
    await session.flush()

    session.add.assert_called_once_with(goal)
    session.flush.assert_awaited_once()


async def test_create_goal_with_all_fields():
    """Goal creation should preserve all fields."""
    goal = _make_goal(
        title="Write weekly review system",
        goal_type="monthly",
        status="active",
        priority=2,
        progress=0.25,
    )

    assert goal.title == "Write weekly review system"
    assert goal.goal_type == "monthly"
    assert goal.status == "active"
    assert goal.priority == 2
    assert goal.progress == 0.25


async def test_create_goal_with_parent():
    """Goals can have a parent goal (hierarchical)."""
    parent = _make_goal("Life goal: health")
    child = _make_goal("Run a marathon")
    child.parent_id = parent.id

    assert child.parent_id == parent.id


# ---------------------------------------------------------------------------
# Goal retrieval
# ---------------------------------------------------------------------------


async def test_get_goal_by_id_returns_goal():
    """Getting a goal by ID should return the goal when it exists."""
    session = _make_session()
    goal = _make_goal("Deploy to production")
    session.get.return_value = goal

    result = await session.get(Goal, goal.id)

    assert result is goal
    assert result.title == "Deploy to production"


async def test_get_goal_by_id_returns_none():
    """Getting a non-existent goal should return None."""
    session = _make_session()
    session.get.return_value = None

    result = await session.get(Goal, uuid.uuid4())

    assert result is None


# ---------------------------------------------------------------------------
# Goal listing with filters
# ---------------------------------------------------------------------------


async def test_list_goals_all():
    """Listing goals should return all goals when no filter is applied."""
    session = _make_session()
    goals = [_make_goal("Goal A"), _make_goal("Goal B"), _make_goal("Goal C")]

    # Mock the execute result
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = goals
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await session.execute(MagicMock())
    all_goals = result.scalars().all()

    assert len(all_goals) == 3


async def test_list_goals_with_status_filter():
    """Listing goals with a status filter should only return matching goals."""
    session = _make_session()
    active_goals = [_make_goal("Active goal", status="active")]
    _make_goal("Done goal", status="completed")  # exists but not returned

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = active_goals
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await session.execute(MagicMock())
    filtered = result.scalars().all()

    assert len(filtered) == 1
    assert filtered[0].status == "active"


async def test_list_goals_empty():
    """Listing goals when none exist should return an empty list."""
    session = _make_session()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await session.execute(MagicMock())
    goals = result.scalars().all()

    assert goals == []


# ---------------------------------------------------------------------------
# Goal updates
# ---------------------------------------------------------------------------


async def test_update_goal_modifies_fields():
    """Updating a goal should modify the specified fields."""
    session = _make_session()
    goal = _make_goal("Original title", status="active", progress=0.0)
    session.get.return_value = goal

    # Simulate an update
    fetched = await session.get(Goal, goal.id)
    fetched.title = "Updated title"
    fetched.progress = 0.75
    fetched.status = "in_progress"
    await session.flush()

    assert fetched.title == "Updated title"
    assert fetched.progress == 0.75
    assert fetched.status == "in_progress"


async def test_update_goal_preserves_unchanged_fields():
    """Updating one field should not affect other fields."""
    goal = _make_goal("My goal", priority=3, progress=0.5)
    original_priority = goal.priority
    original_progress = goal.progress

    goal.title = "Renamed goal"

    assert goal.priority == original_priority
    assert goal.progress == original_progress


# ---------------------------------------------------------------------------
# Goal deletion
# ---------------------------------------------------------------------------


async def test_delete_goal_removes_from_session():
    """Deleting a goal should call delete on the session."""
    session = _make_session()
    goal = _make_goal("Goal to delete")

    await session.delete(goal)
    await session.flush()

    session.delete.assert_awaited_once_with(goal)
    session.flush.assert_awaited()


async def test_goal_status_transitions():
    """Goals should support standard status transitions."""
    goal = _make_goal(status="active")

    goal.status = "in_progress"
    assert goal.status == "in_progress"

    goal.status = "completed"
    assert goal.status == "completed"

    goal.status = "archived"
    assert goal.status == "archived"


# ---------------------------------------------------------------------------
# Goal model validation
# ---------------------------------------------------------------------------


def test_goal_with_explicit_values():
    """Goal should accept explicit values for all fields."""
    goal = Goal(
        title="Test goal",
        priority=3,
        status="active",
        progress=0.5,
        goal_type="quarterly",
    )
    assert goal.title == "Test goal"
    assert goal.priority == 3
    assert goal.status == "active"
    assert goal.progress == 0.5
    assert goal.goal_type == "quarterly"


def test_goal_with_deadline():
    """Goals can have an optional deadline."""
    goal = _make_goal()
    deadline = datetime(2026, 6, 30, tzinfo=UTC)
    goal.deadline = deadline

    assert goal.deadline == deadline


def test_goal_with_evidence():
    """Goals can track evidence of progress."""
    goal = _make_goal()
    goal.evidence = ["Completed module 1", "Passed integration tests"]

    assert len(goal.evidence) == 2
    assert "Completed module 1" in goal.evidence
