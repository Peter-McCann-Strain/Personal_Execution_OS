"""Property-based tests for deterministic budgeting and smoke parsing helpers."""

from __future__ import annotations

import json
from unittest.mock import patch

from hypothesis import assume, given
from hypothesis import strategies as st

from scripts.smoke_api import _parse_sse_events
from src.app.core.context_budget import ContextBudget, estimate_tokens


@given(st.text())
def test_estimate_tokens_matches_fallback_formula(text: str):
    """Fallback token estimation should always match the documented heuristic."""
    with patch("src.app.config.get_settings", side_effect=RuntimeError("config unavailable")):
        assert estimate_tokens(text) == int(len(text) / 3.5)


@given(st.text(), st.text())
def test_estimate_tokens_is_monotonic_when_appending_text(prefix: str, suffix: str):
    """Appending text should never reduce the estimated token count."""
    with patch("src.app.config.get_settings", side_effect=RuntimeError("config unavailable")):
        assert estimate_tokens(prefix + suffix) >= estimate_tokens(prefix)


@given(
    max_context_tokens=st.integers(min_value=200, max_value=5_000),
    system_tokens=st.integers(min_value=0, max_value=200),
    rag_chunks=st.lists(st.text(min_size=0, max_size=400), max_size=6),
    history_messages=st.lists(st.text(min_size=0, max_size=400), max_size=6),
    user_message=st.text(min_size=0, max_size=80),
)
def test_fit_to_budget_preserves_trimming_order_and_respects_effective_input_cap(
    *,
    max_context_tokens: int,
    system_tokens: int,
    rag_chunks: list[str],
    history_messages: list[str],
    user_message: str,
):
    """Budget fitting should keep the newest history, highest-ranked RAG, and stay within cap."""
    budget = ContextBudget(max_context_tokens=max_context_tokens)
    max_input = budget.max_context_tokens - budget.output_reserved - budget.safety_margin
    assume(system_tokens + estimate_tokens(user_message) <= max_input)

    result = budget.fit_to_budget(
        system_tokens=system_tokens,
        rag_chunks=rag_chunks,
        history_messages=history_messages,
        user_message=user_message,
    )

    total_input = (
        system_tokens
        + estimate_tokens(result["user_message"])
        + sum(estimate_tokens(chunk) for chunk in result["rag_chunks"])
        + sum(estimate_tokens(message) for message in result["history"])
    )

    assert total_input <= max_input
    assert result["user_message"] == user_message
    assert rag_chunks[: len(result["rag_chunks"])] == result["rag_chunks"]
    expected_history = history_messages[-len(result["history"]) :] if result["history"] else []
    assert expected_history == result["history"]


_event_name_strategy = st.from_regex(r"[a-z_]{1,12}", fullmatch=True)
_payload_strategy = st.dictionaries(
    keys=st.from_regex(r"[a-z_]{1,12}", fullmatch=True),
    values=st.text(max_size=24),
    max_size=4,
)


@given(st.lists(st.tuples(_event_name_strategy, _payload_strategy), min_size=1, max_size=6))
def test_parse_sse_events_round_trips_structured_event_bodies(
    events: list[tuple[str, dict[str, str]]],
):
    """The SSE parser should preserve ordered event/data pairs and ignore keepalives."""
    body = (
        "".join(
            f": keepalive\nevent: {event_name}\ndata: {json.dumps(payload)}\n\n"
            for event_name, payload in events
        )
        + "data: [DONE]\n\n"
    )

    assert _parse_sse_events(body) == events
