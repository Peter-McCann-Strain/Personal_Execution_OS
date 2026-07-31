"""Tests for the grounded reflection loop in the research subgraph.

All tests are fully mocked — no Anthropic calls, no Tavily calls.

Design invariants under test:
    * reflect_node increments reflection_count each pass.
    * Router loops back to synthesise when verdict == "revise" and
      reflection_count < cap.
    * Router terminates when verdict == "accept" OR when the cap is hit.
    * The research_reflection_result telemetry event fires exactly once
      at graph termination with the expected fields.
    * The compiled end-to-end graph:
        - Finishes after a single synthesis pass when the critic accepts.
        - Finishes after exactly two synthesis passes when the critic
          revises-then-accepts.
        - Respects MAX_REFLECTION_STEPS = 2 when the critic never accepts
          (i.e. runs synthesise exactly 2 times then terminates via the
          cap, not via "accept").
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph import END

from src.app.agents.graphs.research import (
    MAX_REFLECTION_STEPS,
    ResearchCritique,
    ResearchState,
    _route_after_reflect,
    build_research_graph,
    reflect_node,
)

# ---------------------------------------------------------------------------
# Module-level invariant: documented cap is 2
# ---------------------------------------------------------------------------


def test_max_reflection_steps_is_two():
    """2026 agentic-patterns guidance: cap reflection at 2 loops."""
    assert MAX_REFLECTION_STEPS == 2


# ---------------------------------------------------------------------------
# reflect_node — increments count, stores critique
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(
    "src.app.agents.graphs.research.call_and_parse_with_retry",
    new_callable=AsyncMock,
)
async def test_reflect_node_increments_count_and_stores_critique(mock_call):
    mock_call.return_value = ResearchCritique(
        claims_traced=[True, True],
        gaps=[],
        verdict="accept",
        rationale="all claims traced to findings.",
    )
    state: ResearchState = {
        "question": "q",
        "client": AsyncMock(),
        "result": {"synthesis": "Claim 1. Claim 2."},
        "raw_results": [{"title": "A", "url": "https://a", "content": "supports claim 1 and 2"}],
    }

    result = await reflect_node(state)

    assert result["reflection_count"] == 1
    assert result["critique"]["verdict"] == "accept"
    # The critic must be called exactly once — no hidden retries at this layer.
    assert mock_call.call_count == 1


@pytest.mark.asyncio
@patch(
    "src.app.agents.graphs.research.call_and_parse_with_retry",
    new_callable=AsyncMock,
)
async def test_reflect_node_increments_from_existing_count(mock_call):
    mock_call.return_value = ResearchCritique(
        claims_traced=[True],
        gaps=[],
        verdict="accept",
        rationale="ok.",
    )
    state: ResearchState = {
        "question": "q",
        "client": AsyncMock(),
        "result": {"synthesis": "x"},
        "raw_results": [],
        "reflection_count": 1,
    }

    result = await reflect_node(state)
    assert result["reflection_count"] == 2


# ---------------------------------------------------------------------------
# _route_after_reflect — conditional routing logic
# ---------------------------------------------------------------------------


def test_router_accepts_first_pass_and_logs_telemetry():
    state: ResearchState = {
        "critique": {
            "verdict": "accept",
            "gaps": [],
            "claims_traced": [True, True],
            "rationale": "ok",
        },
        "reflection_count": 1,
        "max_reflection_steps": MAX_REFLECTION_STEPS,
    }

    with patch("src.app.agents.graphs.research.logger") as mock_logger:
        route = _route_after_reflect(state)

    assert route == END
    mock_logger.info.assert_called_once_with(
        "research_reflection_result",
        accepted_first_pass=True,
        iterations=1,
        gaps_count=0,
        accepted=True,
    )


def test_router_loops_on_revise_under_cap():
    state: ResearchState = {
        "critique": {
            "verdict": "revise",
            "gaps": ["missing contrarian view"],
            "claims_traced": [True, False],
            "rationale": "one unsupported claim",
        },
        "reflection_count": 1,
        "max_reflection_steps": MAX_REFLECTION_STEPS,
    }

    with patch("src.app.agents.graphs.research.logger") as mock_logger:
        route = _route_after_reflect(state)

    # Loop back — no telemetry yet (we only emit it on termination).
    assert route == "synthesise"
    mock_logger.info.assert_not_called()


def test_router_terminates_when_cap_reached_even_if_revise():
    state: ResearchState = {
        "critique": {
            "verdict": "revise",
            "gaps": ["still more gaps"],
            "claims_traced": [False],
            "rationale": "still bad",
        },
        "reflection_count": MAX_REFLECTION_STEPS,
        "max_reflection_steps": MAX_REFLECTION_STEPS,
    }

    with patch("src.app.agents.graphs.research.logger") as mock_logger:
        route = _route_after_reflect(state)

    # Cap hit — route to END, fire telemetry, and the final verdict
    # was "revise" so ``accepted`` must be False.
    assert route == END
    mock_logger.info.assert_called_once_with(
        "research_reflection_result",
        accepted_first_pass=False,
        iterations=MAX_REFLECTION_STEPS,
        gaps_count=1,
        accepted=False,
    )


def test_router_second_pass_accept_is_not_first_pass():
    state: ResearchState = {
        "critique": {
            "verdict": "accept",
            "gaps": [],
            "claims_traced": [True, True],
            "rationale": "fixed on revision",
        },
        "reflection_count": 2,
        "max_reflection_steps": MAX_REFLECTION_STEPS,
    }

    with patch("src.app.agents.graphs.research.logger") as mock_logger:
        route = _route_after_reflect(state)

    assert route == END
    mock_logger.info.assert_called_once_with(
        "research_reflection_result",
        accepted_first_pass=False,
        iterations=2,
        gaps_count=0,
        accepted=True,
    )


# ---------------------------------------------------------------------------
# End-to-end compiled graph — stub generator and critic, count invocations
# ---------------------------------------------------------------------------


def _stub_report(synthesis: str):
    """Return a mock report object compatible with synthesise_node."""
    report = MagicMock()
    report.model_dump.return_value = {
        "title": "Report",
        "synthesis": synthesis,
        "search_queries": ["q1"],
    }
    report.safety_flags = []
    report.search_queries = []
    return report


def _base_state() -> ResearchState:
    """Minimal state the graph needs past the plan+search stages.

    We pre-populate queries and raw_results so we don't have to stub the
    query-generation / search nodes — this test is about the reflection
    loop, not the retrieval pipeline.
    """
    return {
        "question": "What is X?",
        "queries": ["q1"],
        "raw_results": [{"title": "T1", "url": "https://x", "content": "supports everything"}],
        "client": AsyncMock(),
        "search": AsyncMock(),
        "reflection_count": 0,
        "max_reflection_steps": MAX_REFLECTION_STEPS,
    }


@pytest.mark.asyncio
@patch(
    "src.app.agents.graphs.research.synthesise_findings",
    new_callable=AsyncMock,
)
@patch(
    "src.app.agents.graphs.research.generate_search_queries",
    new_callable=AsyncMock,
)
@patch(
    "src.app.agents.graphs.research.call_and_parse_with_retry",
    new_callable=AsyncMock,
)
async def test_graph_single_loop_accept_first_pass(mock_critic, mock_gen_queries, mock_synthesise):
    """Critic accepts immediately → synthesise runs once, graph terminates."""
    mock_gen_queries.return_value = ["q1"]
    mock_synthesise.return_value = _stub_report("Grounded draft.")
    mock_critic.return_value = ResearchCritique(
        claims_traced=[True],
        gaps=[],
        verdict="accept",
        rationale="ok.",
    )

    graph = build_research_graph().compile()
    search_stub = MagicMock()
    search_stub.search = AsyncMock(
        return_value=[{"title": "T", "url": "https://x", "content": "c"}]
    )

    state = _base_state()
    state["search"] = search_stub

    with patch("src.app.agents.graphs.research.logger") as mock_logger:
        final = await graph.ainvoke(state)

    assert mock_synthesise.call_count == 1
    assert mock_critic.call_count == 1
    assert final["reflection_count"] == 1
    assert final["critique"]["verdict"] == "accept"
    # Telemetry fires exactly once, on termination.
    mock_logger.info.assert_any_call(
        "research_reflection_result",
        accepted_first_pass=True,
        iterations=1,
        gaps_count=0,
        accepted=True,
    )


@pytest.mark.asyncio
@patch(
    "src.app.agents.graphs.research.synthesise_findings",
    new_callable=AsyncMock,
)
@patch(
    "src.app.agents.graphs.research.generate_search_queries",
    new_callable=AsyncMock,
)
@patch(
    "src.app.agents.graphs.research.call_and_parse_with_retry",
    new_callable=AsyncMock,
)
async def test_graph_revise_then_accept_runs_two_synth_passes(
    mock_critic, mock_gen_queries, mock_synthesise
):
    """First critique says revise, second says accept → synthesise runs twice."""
    mock_gen_queries.return_value = ["q1"]
    mock_synthesise.side_effect = [
        _stub_report("Draft v1 — has a gap."),
        _stub_report("Draft v2 — gap closed."),
    ]
    mock_critic.side_effect = [
        ResearchCritique(
            claims_traced=[True, False],
            gaps=["missing contrarian view"],
            verdict="revise",
            rationale="one claim unsupported.",
        ),
        ResearchCritique(
            claims_traced=[True, True],
            gaps=[],
            verdict="accept",
            rationale="fixed.",
        ),
    ]

    graph = build_research_graph().compile()
    search_stub = MagicMock()
    search_stub.search = AsyncMock(
        return_value=[{"title": "T", "url": "https://x", "content": "c"}]
    )

    state = _base_state()
    state["search"] = search_stub

    with patch("src.app.agents.graphs.research.logger") as mock_logger:
        final = await graph.ainvoke(state)

    assert mock_synthesise.call_count == 2
    assert mock_critic.call_count == 2
    assert final["reflection_count"] == 2
    assert final["critique"]["verdict"] == "accept"
    # accepted_first_pass must be False because it took a revision.
    mock_logger.info.assert_any_call(
        "research_reflection_result",
        accepted_first_pass=False,
        iterations=2,
        gaps_count=0,
        accepted=True,
    )


@pytest.mark.asyncio
@patch(
    "src.app.agents.graphs.research.synthesise_findings",
    new_callable=AsyncMock,
)
@patch(
    "src.app.agents.graphs.research.generate_search_queries",
    new_callable=AsyncMock,
)
@patch(
    "src.app.agents.graphs.research.call_and_parse_with_retry",
    new_callable=AsyncMock,
)
async def test_graph_caps_at_max_reflection_steps(mock_critic, mock_gen_queries, mock_synthesise):
    """Critic always revises → graph terminates at the hard cap.

    With MAX_REFLECTION_STEPS = 2, the loop runs:
        synth v1 → reflect (count 0→1, revise, 1<2) → loop → synth v2
        → reflect (count 1→2, revise, 2<2 False) → END
    So synthesise fires exactly MAX_REFLECTION_STEPS times (2).
    """
    mock_gen_queries.return_value = ["q1"]
    mock_synthesise.side_effect = [
        _stub_report("v1"),
        _stub_report("v2"),
        _stub_report("v3"),  # extra stub — test fails fast if the cap leaks
    ]
    # Critic never accepts.  Enough side-effect values to blow past the cap
    # in case the cap fails — the test will then detect the extra call.
    mock_critic.side_effect = [
        ResearchCritique(
            claims_traced=[False],
            gaps=["a"],
            verdict="revise",
            rationale="bad.",
        ),
        ResearchCritique(
            claims_traced=[False],
            gaps=["b"],
            verdict="revise",
            rationale="still bad.",
        ),
        ResearchCritique(
            claims_traced=[False],
            gaps=["c"],
            verdict="revise",
            rationale="still bad 3.",
        ),
        ResearchCritique(
            claims_traced=[False],
            gaps=["d"],
            verdict="revise",
            rationale="still bad 4.",
        ),
    ]

    graph = build_research_graph().compile()
    search_stub = MagicMock()
    search_stub.search = AsyncMock(
        return_value=[{"title": "T", "url": "https://x", "content": "c"}]
    )

    state = _base_state()
    state["search"] = search_stub

    with patch("src.app.agents.graphs.research.logger") as mock_logger:
        final = await graph.ainvoke(state)

    # Exactly MAX_REFLECTION_STEPS syntheses — one per reflection pass.
    assert mock_synthesise.call_count == MAX_REFLECTION_STEPS
    # Critic runs once per synthesis pass.
    assert mock_critic.call_count == MAX_REFLECTION_STEPS
    assert final["reflection_count"] == MAX_REFLECTION_STEPS
    assert final["critique"]["verdict"] == "revise"
    # Final accepted flag is False — cap hit while still wanting a revise.
    mock_logger.info.assert_any_call(
        "research_reflection_result",
        accepted_first_pass=False,
        iterations=MAX_REFLECTION_STEPS,
        gaps_count=1,
        accepted=False,
    )
