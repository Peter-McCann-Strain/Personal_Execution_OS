"""Tests for research LangGraph subgraph."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph import StateGraph

from src.app.agents.graphs.research import (
    ResearchState,
    build_research_graph,
    plan_queries_node,
    search_node,
    synthesise_node,
)

# ---------------------------------------------------------------------------
# build_research_graph — returns a valid StateGraph
# ---------------------------------------------------------------------------


def test_build_research_graph_returns_state_graph():
    graph = build_research_graph()
    assert isinstance(graph, StateGraph)


def test_build_research_graph_has_expected_nodes():
    graph = build_research_graph()
    nodes = graph.nodes
    assert "plan_queries" in nodes
    assert "search" in nodes
    assert "synthesise" in nodes


def test_build_research_graph_compiles():
    """The graph can be compiled without error."""
    graph = build_research_graph()
    compiled = graph.compile()
    assert compiled is not None


# ---------------------------------------------------------------------------
# plan_queries_node — generates search queries from question
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.research.generate_search_queries", new_callable=AsyncMock)
async def test_plan_queries_node(mock_gen_queries):
    mock_gen_queries.return_value = ["query 1", "query 2", "query 3"]
    mock_client = AsyncMock()

    state: ResearchState = {
        "question": "What is quantum computing?",
        "client": mock_client,
    }

    result = await plan_queries_node(state)
    assert result["queries"] == ["query 1", "query 2", "query 3"]
    assert result.model_fields_set == {"queries"}
    mock_gen_queries.assert_called_once_with("What is quantum computing?", mock_client)


# ---------------------------------------------------------------------------
# search_node — executes web searches for all queries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_node():
    mock_search = AsyncMock()
    mock_search.search.side_effect = [
        [{"title": "R1", "url": "https://a.com", "content": "A", "score": 0.9}],
        [{"title": "R2", "url": "https://b.com", "content": "B", "score": 0.8}],
    ]

    state: ResearchState = {
        "queries": ["q1", "q2"],
        "search": mock_search,
    }

    result = await search_node(state)
    assert len(result["raw_results"]) == 2
    assert result["raw_results"][0]["title"] == "R1"
    assert mock_search.search.call_count == 2


@pytest.mark.asyncio
async def test_search_node_empty_queries():
    mock_search = AsyncMock()

    state: ResearchState = {
        "queries": [],
        "search": mock_search,
    }

    result = await search_node(state)
    assert result["raw_results"] == []
    mock_search.search.assert_not_called()


@pytest.mark.asyncio
async def test_search_node_runs_queries_in_parallel():
    """Five 200ms queries should finish in well under 1s if gathered."""
    per_query_delay = 0.2
    num_queries = 5

    async def slow_search(query: str) -> list[dict]:
        await asyncio.sleep(per_query_delay)
        return [{"title": f"R:{query}", "url": f"https://x/{query}", "content": "c", "score": 0.5}]

    mock_search = MagicMock()
    mock_search.search = AsyncMock(side_effect=slow_search)

    queries = [f"q{i}" for i in range(num_queries)]
    state: ResearchState = {"queries": queries, "search": mock_search}

    start = time.perf_counter()
    result = await search_node(state)
    elapsed = time.perf_counter() - start

    # Sequential would be ~1.0s (5 * 0.2). Parallel should be ~0.2s.
    assert elapsed < 1.0, f"search_node not parallel: took {elapsed:.3f}s for {num_queries} queries"
    assert len(result["raw_results"]) == num_queries
    # Ordering preserved: first result corresponds to q0, last to q{n-1}
    assert result["raw_results"][0]["title"] == "R:q0"
    assert result["raw_results"][-1]["title"] == f"R:q{num_queries - 1}"
    assert mock_search.search.call_count == num_queries


@pytest.mark.asyncio
async def test_search_node_continues_on_per_query_exception():
    """If one query raises, the other successful results are still returned."""

    async def flaky_search(query: str) -> list[dict]:
        if query == "bad":
            raise RuntimeError("search API exploded")
        return [{"title": f"R:{query}", "url": f"https://x/{query}", "content": "c", "score": 0.5}]

    mock_search = MagicMock()
    mock_search.search = AsyncMock(side_effect=flaky_search)

    state: ResearchState = {
        "queries": ["good1", "bad", "good2"],
        "search": mock_search,
    }

    result = await search_node(state)
    titles = [r["title"] for r in result["raw_results"]]
    assert titles == ["R:good1", "R:good2"]


# ---------------------------------------------------------------------------
# synthesise_node — synthesises findings into a report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.app.agents.graphs.research.synthesise_findings", new_callable=AsyncMock)
async def test_synthesise_node(mock_synthesise):
    mock_report = MagicMock()
    mock_report.model_dump.return_value = {
        "title": "Quantum Computing Report",
        "synthesis": "Summary of findings",
        "search_queries": ["q1"],
    }
    mock_synthesise.return_value = mock_report
    mock_client = AsyncMock()

    state: ResearchState = {
        "question": "What is quantum computing?",
        "queries": ["q1", "q2"],
        "raw_results": [
            {"title": "R1", "url": "https://a.com", "content": "Content A"},
        ],
        "client": mock_client,
    }

    result = await synthesise_node(state)
    assert "result" in result
    assert result["result"]["title"] == "Quantum Computing Report"
    mock_synthesise.assert_called_once()
    # Verify search_queries were set on the report
    mock_report.search_queries = ["q1", "q2"]


@pytest.mark.asyncio
@patch("src.app.agents.graphs.research.synthesise_findings", new_callable=AsyncMock)
async def test_synthesise_node_preserves_question(mock_synthesise):
    mock_report = MagicMock()
    mock_report.model_dump.return_value = {"title": "Report"}
    mock_synthesise.return_value = mock_report

    state: ResearchState = {
        "question": "My question",
        "queries": ["q1"],
        "raw_results": [{"title": "T", "url": "u", "content": "c"}],
        "client": AsyncMock(),
    }

    await synthesise_node(state)
    # The question should be passed to synthesise_findings
    call_args = mock_synthesise.call_args
    assert call_args.args[0] == "My question"
