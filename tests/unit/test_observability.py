"""Tests for observability — LLM call cost calculation and tracking."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.core.observability import calculate_cost, track_llm_call

# ---------------------------------------------------------------------------
# calculate_cost — known models
# ---------------------------------------------------------------------------


def test_calculate_cost_haiku():
    cost = calculate_cost("claude-haiku-4-5-20251001", input_tokens=1000, output_tokens=500)
    assert cost is not None
    # input: 1000 * 1.0 / 1_000_000 = 0.001
    # output: 500 * 5.0 / 1_000_000 = 0.0025
    expected = 0.001 + 0.0025
    assert abs(cost - expected) < 1e-9


def test_calculate_cost_sonnet():
    cost = calculate_cost("claude-sonnet-4-6", input_tokens=2000, output_tokens=1000)
    assert cost is not None
    # input: 2000 * 3.0 / 1_000_000 = 0.006
    # output: 1000 * 15.0 / 1_000_000 = 0.015
    expected = 0.006 + 0.015
    assert abs(cost - expected) < 1e-9


def test_calculate_cost_opus():
    cost = calculate_cost("claude-opus-4-6", input_tokens=500, output_tokens=200)
    assert cost is not None
    # input: 500 * 5.0 / 1_000_000 = 0.0025
    # output: 200 * 25.0 / 1_000_000 = 0.005
    expected = 0.0025 + 0.005
    assert abs(cost - expected) < 1e-9


# ---------------------------------------------------------------------------
# calculate_cost — unknown model
# ---------------------------------------------------------------------------


def test_calculate_cost_unknown_model():
    cost = calculate_cost("gpt-4-turbo", input_tokens=100, output_tokens=50)
    assert cost is None


# ---------------------------------------------------------------------------
# calculate_cost — zero tokens
# ---------------------------------------------------------------------------


def test_calculate_cost_zero_tokens():
    cost = calculate_cost("claude-haiku-4-5-20251001", input_tokens=0, output_tokens=0)
    assert cost == 0.0


# ---------------------------------------------------------------------------
# track_llm_call — successful call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_track_llm_call_success():
    mock_session = MagicMock()

    async with track_llm_call(mock_session, "diary", "process_entry") as tracker:
        tracker["model"] = "claude-haiku-4-5-20251001"
        tracker["input_tokens"] = 100
        tracker["output_tokens"] = 50

    # Should add an AgentAction to the session
    mock_session.add.assert_called_once()
    action = mock_session.add.call_args.args[0]
    assert action.agent_name == "diary"
    assert action.action_type == "process_entry"
    assert action.model_used == "claude-haiku-4-5-20251001"
    assert action.tokens_in == 100
    assert action.tokens_out == 50
    assert action.cost_usd is not None
    assert action.duration_ms >= 0


# ---------------------------------------------------------------------------
# track_llm_call — includes optional fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_track_llm_call_optional_fields():
    mock_session = MagicMock()

    async with track_llm_call(mock_session, "research", "search") as tracker:
        tracker["model"] = "claude-opus-4-6"
        tracker["input_tokens"] = 200
        tracker["output_tokens"] = 100
        tracker["input_summary"] = "query about AI"
        tracker["output_summary"] = "found 5 results"
        tracker["trace_id"] = "trace-123"

    action = mock_session.add.call_args.args[0]
    assert action.input_summary == "query about AI"
    assert action.output_summary == "found 5 results"
    assert action.trace_id == "trace-123"


# ---------------------------------------------------------------------------
# track_llm_call — failed call (exception)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_track_llm_call_failure():
    mock_session = AsyncMock()

    with pytest.raises(RuntimeError, match="LLM exploded"):
        async with track_llm_call(mock_session, "diary", "process_entry"):
            raise RuntimeError("LLM exploded")

    # Should NOT add to session on failure
    mock_session.add.assert_not_called()


# ---------------------------------------------------------------------------
# track_llm_call — missing required field raises ValueError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_track_llm_call_missing_model():
    mock_session = AsyncMock()

    with pytest.raises(ValueError, match="tracker missing required field: 'model'"):
        async with track_llm_call(mock_session, "diary", "test") as tracker:
            tracker["input_tokens"] = 100
            tracker["output_tokens"] = 50


@pytest.mark.asyncio
async def test_track_llm_call_missing_input_tokens():
    mock_session = AsyncMock()

    with pytest.raises(ValueError, match="tracker missing required field: 'input_tokens'"):
        async with track_llm_call(mock_session, "diary", "test") as tracker:
            tracker["model"] = "claude-haiku-4-5-20251001"
            tracker["output_tokens"] = 50


@pytest.mark.asyncio
async def test_track_llm_call_missing_output_tokens():
    mock_session = AsyncMock()

    with pytest.raises(ValueError, match="tracker missing required field: 'output_tokens'"):
        async with track_llm_call(mock_session, "diary", "test") as tracker:
            tracker["model"] = "claude-haiku-4-5-20251001"
            tracker["input_tokens"] = 100
