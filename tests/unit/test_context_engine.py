"""Tests for the pluggable context engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.app.core.context_manager import AssembledContext
from src.app.domain.models import SessionStatePacket, StatePacketItem


def test_prune_messages_trims_oversized_old_tool_output():
    """Old oversized tool messages should be trimmed, but recent assistant messages stay intact."""
    from src.app.core.context_engine import HierarchicalContextEngine

    engine = HierarchicalContextEngine()
    old_large_tool_output = {
        "role": "assistant",
        "agent": "tools",
        "content": "x" * 5005,
    }
    recent_large_tool_output = {
        "role": "assistant",
        "agent": "tools",
        "content": "y" * 5005,
    }
    messages = [
        {"role": "user", "content": "Remember I prefer concise answers."},
        old_large_tool_output,
        {"role": "assistant", "content": "normal assistant response"},
        {"role": "assistant", "content": "another response"},
        recent_large_tool_output,
    ]

    pruned, count, characters = engine._prune_messages(messages)

    assert count == 1
    assert characters > 0
    assert "[Older tool result trimmed" in pruned[1]["content"]
    assert pruned[-1]["content"] == recent_large_tool_output["content"]


def test_prune_messages_handles_empty_history():
    """Pruning an empty history should return an empty result without counters."""
    from src.app.core.context_engine import HierarchicalContextEngine

    engine = HierarchicalContextEngine()

    pruned, count, characters = engine._prune_messages([])

    assert pruned == []
    assert count == 0
    assert characters == 0


def test_extract_durable_memory_candidates_deduplicates_and_caps():
    """Durable-memory extraction should deduplicate excerpts and stop at six candidates."""
    from src.app.core.context_engine import HierarchicalContextEngine

    engine = HierarchicalContextEngine()
    messages = [
        {"role": "user", "content": "I prefer concise answers."},
        {"role": "user", "content": "I prefer concise answers."},
        {"role": "assistant", "content": "We decided to ship on Friday."},
        {"role": "user", "content": "I will send the report tomorrow."},
        {"role": "assistant", "content": "The project milestone moved."},
        {"role": "user", "content": "I met with my manager today."},
        {"role": "assistant", "content": "Important: note that retries are required."},
        {"role": "user", "content": "I like morning reviews."},
    ]

    candidates = engine._extract_durable_memory_candidates(messages)

    assert len(candidates) == 6
    assert [candidate.category for candidate in candidates] == [
        "preference",
        "decision",
        "commitment",
        "project_state",
        "relationship",
        "knowledge",
    ]


def test_extract_durable_memory_candidates_skips_blank_content():
    """Blank or missing content should be ignored while valid candidates are still extracted."""
    from src.app.core.context_engine import HierarchicalContextEngine

    engine = HierarchicalContextEngine()
    messages = [
        {"role": "user", "content": "   "},
        {"role": "assistant"},
        {"role": "user", "content": "I prefer concise answers."},
    ]

    candidates = engine._extract_durable_memory_candidates(messages)

    assert len(candidates) == 1
    assert candidates[0].category == "preference"
    assert candidates[0].source_role == "user"


async def test_assemble_emits_inspection_metadata():
    """The engine should wrap assembled context with structured inspection metadata."""
    from src.app.core.context_engine import HierarchicalContextEngine

    engine = HierarchicalContextEngine()
    assembled = AssembledContext(
        conversation_context="User: Hello\nAssistant: Hi",
        rag_context="Chunk A\nChunk B",
        total_tokens_estimate=123,
        history_summarized=True,
        rag_chunks_included=2,
        rag_chunks_filtered=1,
    )
    messages = [
        {"role": "user", "content": "I prefer concise answers."},
        {"role": "assistant", "agent": "tools", "content": "x" * 5005},
        {"role": "assistant", "content": "A recent assistant turn"},
        {"role": "assistant", "content": "Another recent assistant turn"},
        {"role": "assistant", "content": "The newest assistant turn"},
    ]

    with patch(
        "src.app.core.context_engine.assemble_context",
        new_callable=AsyncMock,
        return_value=assembled,
    ) as mock_assemble:
        result = await engine.assemble(
            conversation_messages=messages,
            conversation_summary="Earlier session summary",
            state_packet=SessionStatePacket(
                preferences=[StatePacketItem(value="I prefer concise answers.")]
            ),
            rag_chunks=[{"score": 0.8}],
            user_message="Current message",
            client=AsyncMock(),
            model="claude-sonnet-4-6",
        )

    assert result.assembled is assembled
    assert result.inspection.history_summarized is True
    assert result.inspection.rag_chunks_included == 2
    assert result.inspection.rag_chunks_filtered == 1
    assert result.inspection.state_packet_present is True
    assert result.inspection.total_tokens_estimate == 123
    assert len(result.inspection.sections) == 5
    assert result.inspection.durable_memory_candidates[0].category == "preference"
    assert result.inspection.pruned_messages == 1
    mock_assemble.assert_awaited_once()


def test_get_default_context_engine_returns_singleton():
    """The default context engine should be stable across calls."""
    from src.app.core.context_engine import get_default_context_engine

    first = get_default_context_engine()
    second = get_default_context_engine()

    assert first is second
