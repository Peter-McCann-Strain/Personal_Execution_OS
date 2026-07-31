"""Tests for LangGraph orchestrator graph construction and node functions."""

from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.graphs.orchestrator import (
    build_orchestrator_graph,
    classify_node,
    communications_node,
    diary_node,
    memory_node,
    notification_node,
    plan_day_stub,
    project_node,
    research_node,
    review_node,
    route_to_specialist,
    save_stub,
    tools_node,
)
from src.app.agents.specialists.notification import (
    FatigueManager,
    Notification,
    Priority,
)
from src.app.core.exceptions import RoutingError
from src.app.domain.models import Intent, IntentType, Specialist

# ---------------------------------------------------------------------------
# Graph construction tests (existing)
# ---------------------------------------------------------------------------


def test_graph_builds_successfully():
    """Graph should build without errors."""
    graph = build_orchestrator_graph()
    assert graph is not None


def test_graph_has_all_specialist_nodes():
    """Graph should have a node for every specialist (except CONVERSATIONAL, which is
    handled by the chat service before the graph is entered)."""
    graph = build_orchestrator_graph()
    for specialist in Specialist:
        if specialist.value == "conversational":
            continue
        assert specialist.value in graph.nodes


def test_graph_has_classify_node():
    """Graph should have the classify entry node."""
    graph = build_orchestrator_graph()
    assert "classify" in graph.nodes


# ---------------------------------------------------------------------------
# classify_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.orchestrator.classify_intent", new_callable=AsyncMock)
async def test_classify_node(mock_classify_intent: AsyncMock) -> None:
    """classify_node should call classify_intent and set specialist + intent."""
    fake_intent = Intent(
        intent_type=IntentType.CAPTURE,
        confidence=0.95,
        specialist=Specialist.DIARY,
        reasoning="User wants to journal",
    )
    mock_classify_intent.return_value = fake_intent

    client = MagicMock()
    state = {"message": "I had a great day", "client": client}

    result = await classify_node(state)

    mock_classify_intent.assert_awaited_once_with("I had a great day", client)
    assert result["intent"] is fake_intent
    assert result["specialist"] == "diary"
    assert result["message"] == "I had a great day"


# ---------------------------------------------------------------------------
# diary_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.orchestrator.process_diary_entry", new_callable=AsyncMock)
async def test_diary_node(mock_process: AsyncMock) -> None:
    """diary_node should call process_diary_entry and return model_dump."""
    fake_entry = MagicMock()
    fake_entry.model_dump.return_value = {"content": "Great day", "summary": "Good"}
    mock_process.return_value = fake_entry

    client = MagicMock()
    state = {"message": "I had a great day", "client": client}

    result = await diary_node(state)

    mock_process.assert_awaited_once_with("I had a great day", client)
    assert result["result"] == {"content": "Great day", "summary": "Good"}


# ---------------------------------------------------------------------------
# memory_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.orchestrator.answer_from_memory", new_callable=AsyncMock)
async def test_memory_node(mock_answer: AsyncMock) -> None:
    """memory_node should call answer_from_memory with context chunks."""
    fake_answer = MagicMock()
    fake_answer.model_dump.return_value = {"answer": "42"}
    mock_answer.return_value = fake_answer

    client = MagicMock()
    chunks = ["chunk1", "chunk2"]
    state = {"message": "What is the answer?", "client": client, "context_chunks": chunks}

    result = await memory_node(state)

    mock_answer.assert_awaited_once_with("What is the answer?", chunks, client)
    assert result["result"] == {"answer": "42"}


@pytest.mark.asyncio
@patch("src.app.agents.graphs.orchestrator.answer_from_memory", new_callable=AsyncMock)
async def test_memory_node_no_context_chunks(mock_answer: AsyncMock) -> None:
    """memory_node should default to empty list when context_chunks missing."""
    fake_answer = MagicMock()
    fake_answer.model_dump.return_value = {"answer": "empty"}
    mock_answer.return_value = fake_answer

    client = MagicMock()
    state = {"message": "Anything?", "client": client}

    result = await memory_node(state)

    mock_answer.assert_awaited_once_with("Anything?", [], client)
    assert result["result"] == {"answer": "empty"}


# ---------------------------------------------------------------------------
# research_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.orchestrator.run_research", new_callable=AsyncMock)
async def test_research_node(mock_research: AsyncMock) -> None:
    """research_node should call run_research with search_client."""
    fake_report = MagicMock()
    fake_report.model_dump.return_value = {"findings": "interesting"}
    mock_research.return_value = fake_report

    client = MagicMock()
    search_client = MagicMock()
    state = {"message": "Investigate X", "client": client, "search_client": search_client}

    result = await research_node(state)

    mock_research.assert_awaited_once_with("Investigate X", client, search_client)
    assert result["result"] == {"findings": "interesting"}


@pytest.mark.asyncio
async def test_research_node_missing_search_client() -> None:
    """research_node should raise RuntimeError when search_client is missing."""
    state = {"message": "Investigate X", "client": MagicMock()}

    with pytest.raises(RuntimeError, match="search_client"):
        await research_node(state)


# ---------------------------------------------------------------------------
# review_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.orchestrator.generate_weekly_review", new_callable=AsyncMock)
async def test_review_node(mock_review: AsyncMock) -> None:
    """review_node should call generate_weekly_review and return model_dump."""
    fake_review = MagicMock()
    fake_review.model_dump.return_value = {"review": "Week was productive"}
    mock_review.return_value = fake_review

    client = MagicMock()
    state = {"message": "Weekly review please", "client": client}

    result = await review_node(state)

    mock_review.assert_awaited_once_with("Weekly review please", client)
    assert result["result"] == {"review": "Week was productive"}


# ---------------------------------------------------------------------------
# project_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.orchestrator.ai_breakdown_project", new_callable=AsyncMock)
async def test_project_node(mock_breakdown: AsyncMock) -> None:
    """project_node should call ai_breakdown_project and return model_dump."""
    fake_breakdown = MagicMock()
    fake_breakdown.model_dump.return_value = {"tasks": ["task1", "task2"]}
    mock_breakdown.return_value = fake_breakdown

    client = MagicMock()
    state = {"message": "Plan my project", "client": client}

    result = await project_node(state)

    mock_breakdown.assert_awaited_once_with("Plan my project", client)
    assert result["result"] == {"tasks": ["task1", "task2"]}


# ---------------------------------------------------------------------------
# communications_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.orchestrator.triage_email", new_callable=AsyncMock)
async def test_communications_node(mock_triage: AsyncMock) -> None:
    """communications_node should call triage_email and return model_dump."""
    fake_classification = MagicMock()
    fake_classification.model_dump.return_value = {"action": "reply", "urgency": "high"}
    mock_triage.return_value = fake_classification

    client = MagicMock()
    state = {"message": "Triage this email", "client": client}

    result = await communications_node(state)

    mock_triage.assert_awaited_once_with("Triage this email", client)
    assert result["result"] == {"action": "reply", "urgency": "high"}


# ---------------------------------------------------------------------------
# tools_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.orchestrator.plan_tool_calls", new_callable=AsyncMock)
async def test_tools_node(mock_plan: AsyncMock) -> None:
    """tools_node should call plan_tool_calls and return model_dump."""
    fake_plan = MagicMock()
    fake_plan.model_dump.return_value = {"calls": ["calendar.list"]}
    mock_plan.return_value = fake_plan

    client = MagicMock()
    state = {"message": "Check my calendar", "client": client}

    result = await tools_node(state)

    mock_plan.assert_awaited_once_with("Check my calendar", client)
    assert result["result"] == {"calls": ["calendar.list"]}


# ---------------------------------------------------------------------------
# notification_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notification_node_deliver_now() -> None:
    """notification_node should return deliver_now when fatigue manager says so."""
    fm = FatigueManager(dnd_start=time(23, 0), dnd_end=time(7, 0))
    notif = Notification(
        message="Server is down",
        priority=Priority.P0_CRITICAL,
        category="system",
    )

    state = {
        "message": "alert",
        "client": MagicMock(),
        "fatigue_manager": fm,
        "notification": notif,
    }

    result = await notification_node(state)

    assert result["result"]["status"] == "deliver_now"
    assert result["result"]["suppressed"] is False
    assert result["result"]["priority"] == "P0"
    assert result["result"]["message"] == "Server is down"


@pytest.mark.asyncio
async def test_notification_node_batched() -> None:
    """notification_node should return batched for low-priority notifications."""
    fm = FatigueManager(dnd_start=time(23, 0), dnd_end=time(7, 0))
    notif = Notification(
        message="New RSS article",
        priority=Priority.P3_LOW,
        category="digest",
    )

    state = {
        "message": "digest",
        "client": MagicMock(),
        "fatigue_manager": fm,
        "notification": notif,
    }

    result = await notification_node(state)

    assert result["result"]["status"] == "batched"
    assert result["result"]["priority"] == "P3"


@pytest.mark.asyncio
async def test_notification_node_missing_fatigue_manager() -> None:
    """notification_node should raise RuntimeError when fatigue_manager is missing."""
    notif = Notification(
        message="test",
        priority=Priority.P2_NORMAL,
        category="system",
    )
    state = {
        "message": "alert",
        "client": MagicMock(),
        "notification": notif,
    }

    with pytest.raises(RuntimeError, match="fatigue_manager"):
        await notification_node(state)


@pytest.mark.asyncio
async def test_notification_node_missing_notification() -> None:
    """notification_node should raise RuntimeError when notification is missing."""
    fm = FatigueManager(dnd_start=time(23, 0), dnd_end=time(7, 0))
    state = {
        "message": "alert",
        "client": MagicMock(),
        "fatigue_manager": fm,
    }

    with pytest.raises(RuntimeError, match="notification"):
        await notification_node(state)


@pytest.mark.asyncio
async def test_notification_node_missing_both() -> None:
    """notification_node should raise RuntimeError when both are missing."""
    state = {"message": "alert", "client": MagicMock()}

    with pytest.raises(RuntimeError, match="fatigue_manager"):
        await notification_node(state)


# ---------------------------------------------------------------------------
# plan_day_stub (service layer handles the real work)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_day_stub() -> None:
    """plan_day_stub should return plan_day_routed status with message."""
    state = {"message": "Plan my day", "client": MagicMock()}

    result = await plan_day_stub(state)

    assert result["result"]["status"] == "plan_day_routed"
    assert result["result"]["message"] == "Plan my day"


# ---------------------------------------------------------------------------
# save_stub (service layer handles the real work)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_stub() -> None:
    """save_stub should return save_routed status with message."""
    state = {"message": "Save https://example.com", "client": MagicMock()}

    result = await save_stub(state)

    assert result["result"]["status"] == "save_routed"
    assert result["result"]["message"] == "Save https://example.com"


# ---------------------------------------------------------------------------
# route_to_specialist
# ---------------------------------------------------------------------------


def test_route_to_specialist_valid() -> None:
    """route_to_specialist should return the specialist value for valid specialists."""
    for specialist in Specialist:
        state = {"specialist": specialist.value}
        assert route_to_specialist(state) == specialist.value


def test_route_to_specialist_missing() -> None:
    """route_to_specialist should raise RoutingError when specialist is missing."""
    with pytest.raises(RoutingError, match="No specialist assigned"):
        route_to_specialist({})


def test_route_to_specialist_empty_string() -> None:
    """route_to_specialist should raise RoutingError when specialist is empty."""
    with pytest.raises(RoutingError, match="No specialist assigned"):
        route_to_specialist({"specialist": ""})


def test_route_to_specialist_unknown() -> None:
    """route_to_specialist should raise RoutingError for unknown specialist."""
    with pytest.raises(RoutingError, match="Unknown specialist"):
        route_to_specialist({"specialist": "nonexistent_agent"})
