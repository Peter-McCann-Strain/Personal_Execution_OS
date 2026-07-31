"""Tests for context budget management."""

from unittest.mock import patch

from src.app.core.context_budget import (
    DEFAULT_CONTEXT_WINDOW,
    MODEL_CONTEXT_WINDOWS,
    ContextBudget,
    estimate_tokens,
    get_context_window,
)


def test_budget_allocation():
    """Budget percentages should sum correctly."""
    budget = ContextBudget(max_context_tokens=200_000)
    assert budget.system_budget == 10_000  # 5%
    assert budget.rag_budget == 50_000  # 25%
    assert budget.history_budget == 30_000  # 15%
    assert budget.output_reserved == 60_000  # 30%


def test_fit_to_budget_no_truncation():
    """Content within budget should not be truncated."""
    budget = ContextBudget(max_context_tokens=200_000)
    result = budget.fit_to_budget(
        system_tokens=1000,
        rag_chunks=["chunk1", "chunk2"],
        history_messages=["msg1", "msg2"],
        user_message="hello",
    )
    assert not result["truncated"]
    assert len(result["rag_chunks"]) == 2
    assert len(result["history"]) == 2


def test_fit_to_budget_truncates_history_first():
    """When over budget, history should be truncated before RAG."""
    budget = ContextBudget(max_context_tokens=1000)  # Very small budget
    # History budget = 150 tokens ≈ 525 chars
    long_messages = ["x" * 500 for _ in range(10)]
    result = budget.fit_to_budget(
        system_tokens=100,
        rag_chunks=["short chunk"],
        history_messages=long_messages,
        user_message="hello",
    )
    assert result["truncated"]
    assert len(result["history"]) < 10


def test_fit_to_budget_truncates_rag_when_needed():
    """RAG chunks should be truncated after history is exhausted."""
    budget = ContextBudget(max_context_tokens=500)  # Tiny budget
    large_chunks = ["x" * 1000 for _ in range(20)]
    result = budget.fit_to_budget(
        system_tokens=100,
        rag_chunks=large_chunks,
        history_messages=[],
        user_message="hello",
    )
    assert result["truncated"]
    assert len(result["rag_chunks"]) < 20


def test_user_message_preserved():
    """User message should never be truncated."""
    budget = ContextBudget(max_context_tokens=500)
    result = budget.fit_to_budget(
        system_tokens=100,
        rag_chunks=[],
        history_messages=[],
        user_message="my important message",
    )
    assert result["user_message"] == "my important message"


# ---------------------------------------------------------------------------
# Model-aware context window selection
# ---------------------------------------------------------------------------


def test_get_context_window_known_model():
    """Known model names should return their exact context window."""
    for model_name, expected_size in MODEL_CONTEXT_WINDOWS.items():
        assert get_context_window(model_name) == expected_size


def test_get_context_window_unknown_model():
    """Unknown model name should fall back to DEFAULT_CONTEXT_WINDOW (200K)."""
    assert get_context_window("claude-nonexistent-9000") == DEFAULT_CONTEXT_WINDOW
    assert get_context_window("gpt-4") == DEFAULT_CONTEXT_WINDOW


def test_get_context_window_none():
    """None model should return DEFAULT_CONTEXT_WINDOW."""
    assert get_context_window(None) == DEFAULT_CONTEXT_WINDOW


def test_default_context_window_is_200k():
    """Default context window should be 200,000 tokens."""
    assert DEFAULT_CONTEXT_WINDOW == 200_000


def test_budget_from_model_name():
    """ContextBudget created with a model name should use that model's window."""
    budget = ContextBudget(model="claude-sonnet-4-20250514")
    assert budget.max_context_tokens == 200_000


def test_budget_from_unknown_model():
    """ContextBudget with an unknown model should use the default window."""
    budget = ContextBudget(model="unknown-model-xyz")
    assert budget.max_context_tokens == DEFAULT_CONTEXT_WINDOW


def test_explicit_tokens_override_model():
    """Explicit max_context_tokens should override the model-derived window."""
    budget = ContextBudget(max_context_tokens=100_000, model="claude-sonnet-4-20250514")
    assert budget.max_context_tokens == 100_000


# ---------------------------------------------------------------------------
# Safety margin enforcement
# ---------------------------------------------------------------------------


def test_safety_margin_percentage():
    """Safety margin should be 20% of the context window."""
    budget = ContextBudget(max_context_tokens=200_000)
    assert budget.safety_margin == 40_000


def test_safety_margin_prevents_overflow():
    """Even if individual budgets are fine, the safety margin should enforce a hard cap."""
    budget = ContextBudget(max_context_tokens=200_000)
    # max_input = 200_000 - 60_000 (output) - 40_000 (safety) = 100_000
    history = ["y" * 3500 for _ in range(100)]  # ~100 * 1000 = 100_000 tokens
    result = budget.fit_to_budget(
        system_tokens=1000,
        rag_chunks=["x" * 350 for _ in range(50)],
        history_messages=history,
        user_message="hello",
    )
    assert result["truncated"]


def test_fit_to_budget_with_model_override():
    """fit_to_budget should respect a per-call model override."""
    budget = ContextBudget(max_context_tokens=500_000)  # Large default

    result = budget.fit_to_budget(
        system_tokens=100,
        rag_chunks=["x" * 3500 for _ in range(100)],
        history_messages=[],
        user_message="hello",
        model="claude-3-haiku-20240307",  # 200K window
    )
    assert len(result["rag_chunks"]) < 100


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def test_estimate_tokens_empty_string():
    """Empty string should estimate to 0 tokens."""
    assert estimate_tokens("") == 0


def test_estimate_tokens_short_text():
    """Short text should give a reasonable estimate."""
    result = estimate_tokens("hello world")
    assert result == 3  # int(11 / 3.5) = 3


def test_estimate_tokens_longer_text():
    """Longer text should scale linearly."""
    text = "a" * 350
    result = estimate_tokens(text)
    assert result == 100  # 350 / 3.5 = 100


def test_estimate_tokens_consistency():
    """Double the text should give approximately double the tokens."""
    short = estimate_tokens("hello world!")
    doubled = estimate_tokens("hello world!" * 2)
    assert doubled == short * 2


def test_estimate_tokens_falls_back_without_settings():
    """Token estimation should use the default ratio if settings are unavailable."""
    with patch("src.app.config.get_settings", side_effect=RuntimeError("config unavailable")):
        assert estimate_tokens("a" * 35) == 10


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_rag_and_history():
    """Budget with no RAG chunks and no history should not truncate."""
    budget = ContextBudget(max_context_tokens=200_000)
    result = budget.fit_to_budget(
        system_tokens=100,
        rag_chunks=[],
        history_messages=[],
        user_message="test",
    )
    assert not result["truncated"]
    assert result["rag_chunks"] == []
    assert result["history"] == []


def test_very_small_budget():
    """Very small context window should still work without crashing."""
    budget = ContextBudget(max_context_tokens=100)
    result = budget.fit_to_budget(
        system_tokens=10,
        rag_chunks=["some context"],
        history_messages=["old message"],
        user_message="hi",
    )
    assert result["user_message"] == "hi"


def test_budget_uses_default_percentages_when_settings_fail():
    """Budget allocation should fall back to built-in defaults if config lookup fails."""
    with patch("src.app.config.get_settings", side_effect=RuntimeError("config unavailable")):
        budget = ContextBudget(max_context_tokens=1000)

    assert budget.system_budget == 50
    assert budget.rag_budget == 250
    assert budget.history_budget == 150
    assert budget.user_budget == 50
    assert budget.output_reserved == 300
    assert budget.safety_margin == 200


def test_fit_to_budget_enforces_safety_margin_by_trimming_history_then_rag():
    """Safety-margin enforcement should keep trimming after per-section budgets are satisfied."""
    budget = ContextBudget(max_context_tokens=1000)
    result = budget.fit_to_budget(
        system_tokens=200,
        rag_chunks=["r" * 280, "s" * 280, "t" * 280],
        history_messages=["h" * 280, "i" * 280],
        user_message="u" * 350,
    )

    assert result["truncated"] is True
    assert result["history"] == []
    assert len(result["rag_chunks"]) < 3
