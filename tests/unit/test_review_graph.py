"""Tests for review LangGraph subgraph."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph import StateGraph

from src.app.agents.graphs.review import (
    ReviewState,
    _format_review_data,
    build_review_graph,
    extract_actions_node,
    gather_data_node,
    generate_review_node,
)

# ---------------------------------------------------------------------------
# build_review_graph — returns a valid StateGraph
# ---------------------------------------------------------------------------


def test_build_review_graph_returns_state_graph():
    graph = build_review_graph()
    assert isinstance(graph, StateGraph)


def test_build_review_graph_has_expected_nodes():
    graph = build_review_graph()
    nodes = graph.nodes
    assert "gather_data" in nodes
    assert "generate_review" in nodes
    assert "extract_actions" in nodes


def test_build_review_graph_compiles():
    """The graph can be compiled without error."""
    graph = build_review_graph()
    compiled = graph.compile()
    assert compiled is not None


@pytest.mark.asyncio
@patch("src.app.agents.graphs.review.generate_weekly_review", new_callable=AsyncMock)
async def test_compiled_graph_preserves_state_across_partial_updates(mock_weekly):
    """Later Pydantic updates must not erase review inputs or generated output."""
    review = MagicMock()
    review.model_dump.return_value = {
        "period": "2026-W11",
        "recommendations": ["Keep shipping"],
    }
    mock_weekly.return_value = review
    client = AsyncMock()

    final = (
        await build_review_graph()
        .compile()
        .ainvoke(ReviewState(review_type="weekly", data="Week data here", client=client))
    )

    assert final["review_type"] == "weekly"
    assert final["data"] == "Week data here"
    assert final["client"] is client
    assert final["result"]["period"] == "2026-W11"
    assert final["actions"] == ["Keep shipping"]


# ---------------------------------------------------------------------------
# gather_data_node — passes through state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gather_data_node_passthrough():
    state: ReviewState = {
        "review_type": "weekly",
        "data": "Week data here",
        "client": AsyncMock(),
    }
    result = await gather_data_node(state)
    assert result["data"] == "Week data here"
    assert result["review_type"] == "weekly"
    assert result.model_fields_set == {"data", "review_type"}


@pytest.mark.asyncio
@patch("src.app.agents.graphs.review.list_goals", new_callable=AsyncMock)
@patch("src.app.agents.graphs.review.get_episodes_by_date_range", new_callable=AsyncMock)
async def test_gather_data_node_with_database_session(mock_get_episodes, mock_list_goals):
    """Gathered review data includes diary summaries, averages, and active goals."""
    episode = MagicMock()
    episode.created_at = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
    episode.summary = "Shipped the feature"
    episode.mood_score = 8.0
    episode.energy_rating = 6.0
    goal = MagicMock()
    goal.title = "Ship v2"
    goal.progress = 0.75
    goal.status = "active"

    mock_get_episodes.return_value = [episode]
    mock_list_goals.return_value = [goal]

    state: ReviewState = {
        "review_type": "weekly",
        "db_session": AsyncMock(),
        "client": AsyncMock(),
    }

    result = await gather_data_node(state)

    assert "Weekly review period" in result["data"]
    assert "Average mood: 8.0" in result["data"]
    assert "Average energy: 6.0" in result["data"]
    assert "Shipped the feature" in result["data"]
    assert "Ship v2: 75% (active)" in result["data"]


def test_format_review_data_with_empty_inputs():
    """Formatting still returns a useful stub when no episodes or goals are present."""
    output = _format_review_data(
        review_type="monthly",
        period_start=datetime(2026, 4, 1, tzinfo=UTC),
        period_end=datetime(2026, 4, 30, tzinfo=UTC),
        episodes=[],
        goals=[],
    )

    assert "Monthly review period: 2026-04-01 to 2026-04-30" in output
    assert "Total entries: 0" in output
    assert "Diary entries:" not in output
    assert "Active goals:" not in output


def test_format_review_data_handles_missing_mood_and_energy():
    """Formatting tolerates entries that lack mood and energy values."""
    episode = MagicMock()
    episode.created_at = datetime(2026, 4, 2, 14, 30, tzinfo=UTC)
    episode.summary = None
    episode.mood_score = None
    episode.energy_rating = None
    goal = MagicMock()
    goal.title = "Practice piano"
    goal.progress = None
    goal.status = "active"

    output = _format_review_data(
        review_type="weekly",
        period_start=datetime(2026, 4, 1, tzinfo=UTC),
        period_end=datetime(2026, 4, 7, tzinfo=UTC),
        episodes=[episode],
        goals=[goal],
    )

    assert "(no summary)" in output
    assert "Average mood" not in output
    assert "Average energy" not in output
    assert "Practice piano: 0% (active)" in output


# ---------------------------------------------------------------------------
# generate_review_node — weekly review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.review.generate_weekly_review", new_callable=AsyncMock)
async def test_generate_review_node_weekly(mock_weekly):
    mock_review = MagicMock()
    mock_review.model_dump.return_value = {
        "period": "2026-W11",
        "accomplishments": ["Shipped feature X"],
        "recommendations": ["Take more breaks"],
    }
    mock_weekly.return_value = mock_review

    state: ReviewState = {
        "review_type": "weekly",
        "data": "This week I shipped feature X...",
        "client": AsyncMock(),
    }

    result = await generate_review_node(state)
    assert result["result"]["period"] == "2026-W11"
    assert "Shipped feature X" in result["result"]["accomplishments"]
    assert result.model_fields_set == {"result"}
    mock_weekly.assert_called_once()


# ---------------------------------------------------------------------------
# generate_review_node — quarterly review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.review.generate_quarterly_review", new_callable=AsyncMock)
async def test_generate_review_node_quarterly(mock_quarterly):
    mock_review = MagicMock()
    mock_review.model_dump.return_value = {
        "period": "2026-Q1",
        "next_quarter_priorities": ["Focus on health"],
    }
    mock_quarterly.return_value = mock_review

    state: ReviewState = {
        "review_type": "quarterly",
        "data": "Q1 data...",
        "client": AsyncMock(),
    }

    result = await generate_review_node(state)
    assert result["result"]["period"] == "2026-Q1"
    mock_quarterly.assert_called_once()


# ---------------------------------------------------------------------------
# generate_review_node — defaults to weekly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.review.generate_weekly_review", new_callable=AsyncMock)
async def test_generate_review_node_default_weekly(mock_weekly):
    mock_review = MagicMock()
    mock_review.model_dump.return_value = {"period": "default"}
    mock_weekly.return_value = mock_review

    state: ReviewState = {
        "data": "Some data",
        "client": AsyncMock(),
    }

    await generate_review_node(state)
    mock_weekly.assert_called_once()


# ---------------------------------------------------------------------------
# extract_actions_node — weekly (recommendations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_actions_weekly():
    state: ReviewState = {
        "result": {
            "period": "2026-W11",
            "recommendations": ["Exercise more", "Read daily"],
        },
    }

    result = await extract_actions_node(state)
    assert result["actions"] == ["Exercise more", "Read daily"]


# ---------------------------------------------------------------------------
# extract_actions_node — quarterly (next_quarter_priorities)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_actions_quarterly():
    state: ReviewState = {
        "result": {
            "period": "2026-Q1",
            "next_quarter_priorities": ["Ship v2", "Hire designer"],
        },
    }

    result = await extract_actions_node(state)
    assert result["actions"] == ["Ship v2", "Hire designer"]


# ---------------------------------------------------------------------------
# extract_actions_node — empty result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_actions_empty_result():
    state: ReviewState = {}
    result = await extract_actions_node(state)
    assert result["actions"] == []


# ---------------------------------------------------------------------------
# extract_actions_node — result with neither field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_actions_no_action_fields():
    state: ReviewState = {
        "result": {"period": "2026-W11", "accomplishments": ["Something"]},
    }
    result = await extract_actions_node(state)
    assert result["actions"] == []
