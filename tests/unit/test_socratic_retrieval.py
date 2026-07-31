"""Tests for Socratic second-brain retrieval."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


async def test_retrieve_second_brain_context_formats_notes_and_tutorials():
    """Retrieval combines note hits and past tutorials into one context string."""
    notes = [
        {
            "title": "Caching basics",
            "content": "Caching can improve performance when invalidation is controlled.",
            "created_at": "2026-01-12",
        }
    ]
    tutorials = [
        SimpleNamespace(
            topic="Cache invalidation",
            completed_at=datetime(2026, 1, 15, tzinfo=UTC),
            analysis={"knowledge_gaps": [{"gap": "Expiry strategies"}]},
        )
    ]

    with (
        patch(
            "src.app.agents.socratic.retrieval.search_notes",
            new_callable=AsyncMock,
            return_value=notes,
        ),
        patch(
            "src.app.agents.socratic.retrieval.get_past_tutorials",
            new_callable=AsyncMock,
            return_value=tutorials,
        ),
    ):
        from src.app.agents.socratic.retrieval import retrieve_second_brain_context

        result = await retrieve_second_brain_context(
            user_id="user-1",
            propositions=[{"text": "Caching improves performance"}],
            submitted_work="Caching is useful.",
            db_session=AsyncMock(),
        )

    assert "## Relevant Notes from Second Brain" in result
    assert "Caching basics" in result
    assert "## Past Tutorial Sessions" in result
    assert "Expiry strategies" in result


async def test_retrieve_second_brain_context_uses_submitted_work_when_propositions_empty():
    """Submitted work becomes the query fallback when proposition text is missing."""
    with (
        patch(
            "src.app.agents.socratic.retrieval.search_notes",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_search_notes,
        patch(
            "src.app.agents.socratic.retrieval.get_past_tutorials",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        from src.app.agents.socratic.retrieval import retrieve_second_brain_context

        result = await retrieve_second_brain_context(
            user_id="user-1",
            propositions=[{"no_text": "ignored"}],
            submitted_work="Fallback query content",
            db_session=AsyncMock(),
        )

    assert result == ""
    assert mock_search_notes.await_args.kwargs["query"] == "Fallback query content"


async def test_retrieve_second_brain_context_handles_note_search_failure():
    """Note-search failures should propagate instead of degrading silently."""

    with (
        patch(
            "src.app.agents.socratic.retrieval.search_notes",
            new_callable=AsyncMock,
            side_effect=RuntimeError("notes unavailable"),
        ),
        patch(
            "src.app.agents.socratic.retrieval.get_past_tutorials",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        from src.app.agents.socratic.retrieval import retrieve_second_brain_context

        with pytest.raises(RuntimeError, match="notes unavailable"):
            await retrieve_second_brain_context(
                user_id="user-1",
                propositions=[{"text": "Consensus matters"}],
                submitted_work="Distributed systems work",
                db_session=AsyncMock(),
            )


async def test_retrieve_second_brain_context_handles_tutorial_lookup_failure():
    """Tutorial-history failures should propagate instead of degrading silently."""
    notes = [
        {
            "title": "Socratic note",
            "content": "Ask sharp questions and trace assumptions.",
            "created_at": "2026-03-01",
        }
    ]

    with (
        patch(
            "src.app.agents.socratic.retrieval.search_notes",
            new_callable=AsyncMock,
            return_value=notes,
        ),
        patch(
            "src.app.agents.socratic.retrieval.get_past_tutorials",
            new_callable=AsyncMock,
            side_effect=RuntimeError("history unavailable"),
        ),
    ):
        from src.app.agents.socratic.retrieval import retrieve_second_brain_context

        with pytest.raises(RuntimeError, match="history unavailable"):
            await retrieve_second_brain_context(
                user_id="user-1",
                propositions=[{"text": "Question assumptions"}],
                submitted_work="Socratic practice",
                db_session=AsyncMock(),
            )


async def test_retrieve_second_brain_context_ignores_non_dict_propositions():
    """Non-dict proposition items should be skipped when building the query."""
    with (
        patch(
            "src.app.agents.socratic.retrieval.search_notes",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_search_notes,
        patch(
            "src.app.agents.socratic.retrieval.get_past_tutorials",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        from src.app.agents.socratic.retrieval import retrieve_second_brain_context

        result = await retrieve_second_brain_context(
            user_id="user-1",
            propositions=["ignore-me", {"text": "Use this"}],
            submitted_work="Fallback query content",
            db_session=AsyncMock(),
        )

    assert result == ""
    assert mock_search_notes.await_args.kwargs["query"] == "Use this"
