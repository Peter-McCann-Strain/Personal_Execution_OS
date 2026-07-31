"""Tests for project handler — AI breakdown and WSJF prioritization."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.domain.models import (
    ChatResponse,
    Intent,
    IntentType,
    MessageInput,
    Specialist,
)


def _make_message(content: str = "Break down this project") -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _make_intent() -> Intent:
    return Intent(
        intent_type=IntentType.PROJECT,
        confidence=0.9,
        specialist=Specialist.PROJECT,
        reasoning="project management",
    )


def _make_breakdown_result():
    """Build a mock ProjectBreakdownResult."""
    task = MagicMock()
    task.title = "Set up database"
    task.description = "Configure PostgreSQL"
    task.estimate_hours = 4.0
    task.complexity = "medium"
    task.depends_on = []
    task.context_tags = ["backend"]

    milestone = MagicMock()
    milestone.title = "Infrastructure"
    milestone.success_criteria = ["Database running", "Migrations working"]
    milestone.tasks = [task]

    breakdown = MagicMock()
    breakdown.milestones = [milestone]
    breakdown.project_summary = (
        "Build the initial infrastructure and deliver a first vertical slice."
    )
    breakdown.total_estimated_hours = 4.0
    breakdown.critical_path = ["Set up database"]
    breakdown.risks = ["Schema changes could ripple into the API."]
    return breakdown


def _make_episode_mock():
    episode = MagicMock()
    episode.id = uuid.uuid4()
    return episode


def _make_draft_mock():
    draft = MagicMock()
    draft.id = uuid.uuid4()
    return draft


@pytest.mark.asyncio
async def test_handle_project_breakdown_happy_path():
    """handle_project generates a project breakdown and stores it."""
    message = _make_message("Build a todo app with React and FastAPI")
    intent = _make_intent()
    breakdown = _make_breakdown_result()
    episode = _make_episode_mock()
    draft = _make_draft_mock()

    mock_session = AsyncMock()

    with (
        patch(
            "src.app.domain.services.handlers.project.ai_breakdown_project",
            new_callable=AsyncMock,
            return_value=breakdown,
        ) as mock_breakdown,
        patch(
            "src.app.domain.services.handlers.project.create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch(
            "src.app.domain.services.handlers.project.create_project_draft",
            new_callable=AsyncMock,
            return_value=draft,
        ),
    ):
        from src.app.domain.services.handlers.project import handle_project

        result = await handle_project(message, AsyncMock(), mock_session, intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "project"
    assert "drafted a project plan" in result.content.lower()
    assert "critical path" in result.content.lower()
    assert result.metadata["milestone_count"] == 1
    assert result.metadata["total_estimated_hours"] == 4.0
    assert result.metadata["draft_created"] is True
    assert result.metadata["project_draft_id"] == str(draft.id)
    mock_breakdown.assert_awaited_once()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_project_wsjf_calculation():
    """handle_project calculates WSJF when keywords + 4 numbers are present."""
    message = _make_message(
        "Calculate WSJF: business value 8, time criticality 6, risk reduction 4, job size 3"
    )
    intent = _make_intent()

    with patch(
        "src.app.domain.services.handlers.project.calculate_wsjf",
        return_value=6.0,
    ) as mock_wsjf:
        from src.app.domain.services.handlers.project import handle_project

        result = await handle_project(message, AsyncMock(), AsyncMock(), intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "project"
    assert "WSJF score is 6.0" in result.content
    assert "high priority" in result.content
    assert result.metadata["wsjf_score"] == 6.0
    assert result.metadata["business_value"] == 8
    assert result.metadata["time_criticality"] == 6
    mock_wsjf.assert_called_once_with(8, 6, 4, 3)


@pytest.mark.asyncio
async def test_handle_project_wsjf_invalid_params():
    """handle_project handles ValueError from calculate_wsjf."""
    message = _make_message("prioritize: business value 99, time 6, risk 4, size 3")
    intent = _make_intent()

    with patch(
        "src.app.domain.services.handlers.project.calculate_wsjf",
        side_effect=ValueError("business_value must be between 1 and 10, got 99"),
    ):
        from src.app.domain.services.handlers.project import handle_project

        result = await handle_project(message, AsyncMock(), AsyncMock(), intent)

    assert result.agent == "project"
    assert "Invalid WSJF parameters" in result.content
    assert result.metadata["error"] == "invalid_wsjf_params"


@pytest.mark.asyncio
async def test_handle_project_wsjf_insufficient_numbers():
    """handle_project detects WSJF keyword but not enough numeric values."""
    # "prioritize" keyword but only 2 numbers
    message = _make_message("prioritize tasks 5 3")
    intent = _make_intent()
    breakdown = _make_breakdown_result()
    episode = _make_episode_mock()
    draft = _make_draft_mock()

    with (
        patch(
            "src.app.domain.services.handlers.project.ai_breakdown_project",
            new_callable=AsyncMock,
            return_value=breakdown,
        ),
        patch(
            "src.app.domain.services.handlers.project.create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch(
            "src.app.domain.services.handlers.project.create_project_draft",
            new_callable=AsyncMock,
            return_value=draft,
        ),
    ):
        from src.app.domain.services.handlers.project import handle_project

        result = await handle_project(message, AsyncMock(), AsyncMock(), intent)

    # Not enough numbers for WSJF, falls through to breakdown
    assert result.agent == "project"
    assert "drafted a project plan" in result.content.lower()


@pytest.mark.asyncio
async def test_handle_project_llm_failure_propagates():
    """handle_project propagates LLM errors from ai_breakdown_project."""
    message = _make_message("Plan a new project")
    intent = _make_intent()

    with (
        patch(
            "src.app.domain.services.handlers.project.ai_breakdown_project",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Claude API failed"),
        ),
        pytest.raises(RuntimeError, match="Claude API failed"),
    ):
        from src.app.domain.services.handlers.project import handle_project

        await handle_project(message, AsyncMock(), AsyncMock(), intent)


def test_is_wsjf_request_with_keywords_and_numbers():
    """_is_wsjf_request detects WSJF when keyword + 4 numbers present."""
    from src.app.domain.services.handlers.project import _is_wsjf_request

    assert _is_wsjf_request("wsjf 8 6 4 3") is True
    assert _is_wsjf_request("prioritize tasks: 8, 6, 4, 3") is True
    assert _is_wsjf_request("calculate priority score 7 5 3 2") is True
    assert _is_wsjf_request("cost of delay 9 8 7 6") is True


def test_is_wsjf_request_without_enough_numbers():
    """_is_wsjf_request returns False without enough numbers."""
    from src.app.domain.services.handlers.project import _is_wsjf_request

    assert _is_wsjf_request("wsjf 8 6") is False
    assert _is_wsjf_request("prioritize this project") is False


def test_is_wsjf_request_without_keywords():
    """_is_wsjf_request returns False without recognized keywords."""
    from src.app.domain.services.handlers.project import _is_wsjf_request

    assert _is_wsjf_request("calculate 8 6 4 3") is False


# ------------------------------------------------------------------
# Bug 2 regression: single-task capture path
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_project_single_task_creates_draft_without_breakdown():
    """Bug 2 regression: 'Add a task: ...' must persist a project_drafts row
    AND an episode without invoking the heavy ai_breakdown_project LLM call.
    """
    message = _make_message(
        "Add a task: write the deploy/rollback runbook before the next release."
    )
    intent = _make_intent()
    episode = _make_episode_mock()
    draft = _make_draft_mock()

    mock_session = AsyncMock()

    with (
        patch(
            "src.app.domain.services.handlers.project.ai_breakdown_project",
            new_callable=AsyncMock,
        ) as mock_breakdown,
        patch(
            "src.app.domain.services.handlers.project.create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch(
            "src.app.domain.services.handlers.project.create_project_draft",
            new_callable=AsyncMock,
            return_value=draft,
        ) as mock_create_draft,
    ):
        from src.app.domain.services.handlers.project import handle_project

        result = await handle_project(message, AsyncMock(), mock_session, intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "project"
    assert result.metadata["capture_mode"] == "single_task"
    assert result.metadata["draft_created"] is True
    assert result.metadata["project_draft_id"] == str(draft.id)
    assert "captured task" in result.content.lower()
    # The heavy AI breakdown must NOT be called for a single-task capture.
    mock_breakdown.assert_not_awaited()
    mock_create_draft.assert_awaited_once()
    mock_session.commit.assert_awaited_once()


def test_is_single_task_request_matches_add_a_task_prefix():
    """The single-task heuristic must catch common task-add phrasings."""
    from src.app.domain.services.handlers.project import _is_single_task_request

    assert _is_single_task_request("add a task: ship the runbook") is True
    assert _is_single_task_request("add task write the docs") is True
    assert _is_single_task_request("create a task to audit the logs") is True
    assert _is_single_task_request("new task: update onboarding copy") is True


def test_is_single_task_request_ignores_breakdown_prompts():
    """Large-project breakdown prompts must not be treated as single tasks."""
    from src.app.domain.services.handlers.project import _is_single_task_request

    assert _is_single_task_request("break down the personal assistant project") is False
    assert _is_single_task_request("prioritise my tasks for next sprint") is False


def test_extract_task_title_strips_common_prefixes():
    """_extract_task_title must drop 'Add a task:' style prefixes cleanly."""
    from src.app.domain.services.handlers.project import _extract_task_title

    assert (
        _extract_task_title("Add a task: write the deploy/rollback runbook")
        == "write the deploy/rollback runbook"
    )
    assert _extract_task_title("new task - audit the logs") == "audit the logs"
