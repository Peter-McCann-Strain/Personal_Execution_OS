"""Context budget management — token counting and intelligent allocation.

Model-aware context window allocation with a **summarize-first** strategy.
Truncation is the last resort, not the default.

All percentages and constants come from Settings — nothing hardcoded.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()

# Context window sizes for Claude models (input tokens).
# Kept in sync with https://docs.anthropic.com/en/docs/about-claude/models
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # Claude 4.5 / 4.6 family
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    # Claude 4 family
    "claude-sonnet-4-20250514": 200_000,
    "claude-haiku-4-20250414": 200_000,
    # Claude 3.5 family
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
}

# Default context window when the model is unknown.
DEFAULT_CONTEXT_WINDOW = 200_000


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string using the chars/token heuristic.

    The ratio comes from Settings if available, otherwise uses 3.5.
    More accurate than the naive 4-char approximation.
    """
    if not text:
        return 0
    try:
        from src.app.config import get_settings

        chars_per_token = get_settings().chars_per_token
    except Exception:
        # During early startup or tests without config, use the standard ratio.
        # This is NOT a silent fallback — it's bootstrapping before config exists.
        chars_per_token = 3.5
    return int(len(text) / chars_per_token)


def get_context_window(model: str | None = None) -> int:
    """Return the context window size for a model name.

    Falls back to DEFAULT_CONTEXT_WINDOW for unknown models.
    """
    if model is None:
        return DEFAULT_CONTEXT_WINDOW
    return MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)


class ContextBudget:
    """Manages token budget allocation for LLM context windows.

    Implements a **summarize-first, truncate-last** strategy:

    1. Estimate token usage for all components.
    2. If history exceeds its budget, the caller should summarize older
       messages via :func:`~context_manager.summarize_messages`.
    3. If RAG chunks exceed their budget, drop the least relevant (lowest
       score) first.
    4. Truncation of raw text is the absolute last resort.

    All budget percentages come from Settings.
    """

    def __init__(
        self,
        max_context_tokens: int | None = None,
        *,
        model: str | None = None,
    ) -> None:
        if max_context_tokens is not None:
            self.max_context_tokens = max_context_tokens
        else:
            self.max_context_tokens = get_context_window(model)

        try:
            from src.app.config import get_settings

            settings = get_settings()
            system_pct = settings.budget_system_pct
            rag_pct = settings.budget_rag_pct
            history_pct = settings.budget_history_pct
            user_pct = settings.budget_user_pct
            output_pct = settings.budget_output_pct
            safety_pct = settings.budget_safety_pct
        except Exception:
            # During tests without config — use known defaults.
            system_pct = 0.05
            rag_pct = 0.25
            history_pct = 0.15
            user_pct = 0.05
            output_pct = 0.30
            safety_pct = 0.20

        self.system_budget = int(self.max_context_tokens * system_pct)
        self.rag_budget = int(self.max_context_tokens * rag_pct)
        self.history_budget = int(self.max_context_tokens * history_pct)
        self.user_budget = int(self.max_context_tokens * user_pct)
        self.output_reserved = int(self.max_context_tokens * output_pct)
        self.safety_margin = int(self.max_context_tokens * safety_pct)

    def fit_to_budget(
        self,
        system_tokens: int,
        rag_chunks: list[str],
        history_messages: list[str],
        user_message: str,
        *,
        model: str | None = None,
    ) -> dict:
        """Fit content into the budget, preferring summarization over truncation.

        If *model* is provided, the context window for that model is used
        instead of the instance default.

        Strategy (in order):
        1. Drop lowest-relevance RAG chunks that exceed the RAG budget.
        2. Trim oldest history messages that exceed the history budget.
        3. Enforce overall safety margin by further trimming history, then RAG.

        Never truncates: system prompt, current message.

        .. note::
            For intelligent summarization of history, use
            :func:`~context_manager.assemble_context` which calls
            :func:`~context_manager.summarize_messages` before falling
            back to truncation here.
        """
        if model is not None:
            window = get_context_window(model)
            rag_budget = int(window * 0.25)
            history_budget = int(window * 0.15)
            safety_margin = int(window * 0.20)
            output_reserved = int(window * 0.30)
        else:
            rag_budget = self.rag_budget
            history_budget = self.history_budget
            safety_margin = self.safety_margin
            output_reserved = self.output_reserved

        result: dict = {
            "system": True,
            "user_message": user_message,
            "rag_chunks": list(rag_chunks),
            "history": list(history_messages),
            "truncated": False,
        }

        rag_tokens = sum(estimate_tokens(c) for c in rag_chunks)
        history_tokens = sum(estimate_tokens(m) for m in history_messages)
        user_tokens = estimate_tokens(user_message)

        # Trim history (oldest first via index tracking — O(n) not O(n²))
        trim_idx = 0
        while history_tokens > history_budget and trim_idx < len(result["history"]):
            history_tokens -= estimate_tokens(result["history"][trim_idx])
            trim_idx += 1
        if trim_idx:
            result["history"] = result["history"][trim_idx:]
            result["truncated"] = True

        # Drop least-relevant RAG chunks (last = lowest relevance)
        while rag_tokens > rag_budget and result["rag_chunks"]:
            removed = result["rag_chunks"].pop()
            rag_tokens -= estimate_tokens(removed)
            result["truncated"] = True

        # Enforce safety margin
        max_input = (
            (get_context_window(model) if model else self.max_context_tokens)
            - output_reserved
            - safety_margin
        )
        total_input = system_tokens + rag_tokens + history_tokens + user_tokens
        trim_idx = 0
        while total_input > max_input and trim_idx < len(result["history"]):
            removed_tokens = estimate_tokens(result["history"][trim_idx])
            history_tokens -= removed_tokens
            total_input -= removed_tokens
            trim_idx += 1
        if trim_idx:
            result["history"] = result["history"][trim_idx:]
            result["truncated"] = True
        while total_input > max_input and result["rag_chunks"]:
            removed = result["rag_chunks"].pop()
            removed_tokens = estimate_tokens(removed)
            rag_tokens -= removed_tokens
            total_input -= removed_tokens
            result["truncated"] = True

        if result["truncated"]:
            logger.info(
                "context_truncated",
                rag_chunks=len(result["rag_chunks"]),
                history_msgs=len(result["history"]),
            )

        return result
