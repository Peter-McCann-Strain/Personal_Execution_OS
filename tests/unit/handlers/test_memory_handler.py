"""Tests for memory handler — unified cross-store search with LLM synthesis."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.embeddings import EmbeddingError
from src.app.core.exceptions import DatabaseError
from src.app.domain.models import (
    ChatResponse,
    Intent,
    IntentType,
    MessageInput,
    Specialist,
)
from src.app.persistence.repositories.unified_search import UnifiedResult


def _make_message(content: str = "What did I say about Python?") -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _make_intent() -> Intent:
    return Intent(
        intent_type=IntentType.QUERY,
        confidence=0.9,
        specialist=Specialist.MEMORY,
        reasoning="memory query",
    )


def _make_context_chunks() -> list[dict]:
    return [
        {
            "content": "Python is great for AI",
            "score": 0.85,
            "source_type": "episode",
            "source_id": str(uuid.uuid4()),
            "search_method": "unified",
        },
        {
            "content": "I love Python's simplicity",
            "score": 0.72,
            "source_type": "note",
            "source_id": str(uuid.uuid4()),
            "search_method": "unified",
        },
    ]


def _make_episode_chunk() -> dict:
    return {
        "content": "Python is great for AI",
        "score": 0.85,
        "source_type": "episode",
        "source_id": str(uuid.uuid4()),
        "search_method": "unified",
    }


def _make_note_chunk() -> dict:
    return {
        "content": "I love Python's simplicity",
        "score": 0.72,
        "source_type": "note",
        "source_id": str(uuid.uuid4()),
        "search_method": "unified",
    }


def _make_memory_answer():
    """Create a mock MemoryAnswer."""
    answer = MagicMock()
    answer.answer = "You've mentioned Python is great for AI and simple to use."
    answer.confidence = 0.85
    answer.sources = [MagicMock(), MagicMock()]
    answer.follow_up_suggestions = ["What projects use Python?"]
    return answer


@pytest.mark.asyncio
async def test_handle_memory_happy_path_unified():
    """handle_memory returns synthesized answer from unified search results."""
    message = _make_message()
    intent = _make_intent()
    context_chunks = _make_context_chunks()
    memory_answer = _make_memory_answer()

    with (
        patch(
            "src.app.domain.services.handlers.memory._retrieve_context",
            new_callable=AsyncMock,
            return_value=context_chunks,
        ),
        patch(
            "src.app.domain.services.handlers.memory._retrieve_interaction_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._build_session_context_chunks",
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory.answer_from_memory",
            new_callable=AsyncMock,
            return_value=memory_answer,
        ) as mock_answer,
        patch(
            "src.app.domain.services.handlers.memory.gate_by_relevance",
            return_value=(context_chunks, 0),
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_episode_access",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_note_access",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.memory.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ),
    ):
        from src.app.domain.services.handlers.memory import handle_memory

        result = await handle_memory(message, AsyncMock(), AsyncMock(), intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "memory"
    assert "Python is great for AI" in result.content
    assert result.metadata["confidence"] == 0.85
    assert result.metadata["source_count"] == 2
    assert result.metadata["search_method"] == "unified"
    assert "episode" in result.metadata["source_types"]
    assert "note" in result.metadata["source_types"]
    mock_answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_memory_no_results():
    """handle_memory returns a 'not found' response when no context is retrieved."""
    message = _make_message("Something totally obscure")
    intent = _make_intent()

    with (
        patch(
            "src.app.domain.services.handlers.memory._retrieve_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._retrieve_interaction_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._build_session_context_chunks",
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory.gate_by_relevance",
            return_value=([], 0),
        ),
    ):
        from src.app.domain.services.handlers.memory import handle_memory

        result = await handle_memory(message, AsyncMock(), AsyncMock(), intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "memory"
    assert "don't have a durable record for that yet" in result.content
    assert result.metadata["result_count"] == 0
    assert result.metadata["search_method"] == "none"


@pytest.mark.asyncio
async def test_handle_memory_replaces_empty_canned_reply_when_context_exists():
    """If retrieval exists, collapse empty canned memory replies into deterministic recap."""
    message = _make_message("What was I working on yesterday?")
    intent = _make_intent()
    context_chunks = [
        {
            "content": "Interaction on 2026-04-10 10:00 BST. You asked: Deployment update. Assistant replied: You shipped the frontend deployment and fixed webhook retries.",
            "score": 0.86,
            "source_type": "interaction",
            "source_id": str(uuid.uuid4()),
            "search_method": "interaction_history",
        }
    ]
    memory_answer = MagicMock()
    memory_answer.answer = "Nothing stored about that yet."
    memory_answer.confidence = 0.2
    memory_answer.sources = []
    memory_answer.follow_up_suggestions = []

    with (
        patch(
            "src.app.domain.services.handlers.memory._retrieve_context",
            new_callable=AsyncMock,
            return_value=context_chunks,
        ),
        patch(
            "src.app.domain.services.handlers.memory._retrieve_interaction_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._build_session_context_chunks",
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory.answer_from_memory",
            new_callable=AsyncMock,
            return_value=memory_answer,
        ),
        patch(
            "src.app.domain.services.handlers.memory.gate_by_relevance",
            return_value=(context_chunks, 0),
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_episode_access",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_note_access",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.memory.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ),
    ):
        from src.app.domain.services.handlers.memory import handle_memory

        result = await handle_memory(message, AsyncMock(), AsyncMock(), intent)

    assert "Nothing stored about that yet." not in result.content
    assert "I do have related history." in result.content
    assert "frontend deployment" in result.content
    assert result.metadata["confidence"] == 0.45


@pytest.mark.asyncio
async def test_handle_memory_relevance_gating_filters_chunks():
    """handle_memory filters low-relevance chunks via gate_by_relevance."""
    message = _make_message()
    intent = _make_intent()
    raw_chunks = _make_context_chunks()
    # Simulate gating: only one chunk passes
    gated_chunks = [raw_chunks[0]]
    memory_answer = _make_memory_answer()

    with (
        patch(
            "src.app.domain.services.handlers.memory._retrieve_context",
            new_callable=AsyncMock,
            return_value=raw_chunks,
        ),
        patch(
            "src.app.domain.services.handlers.memory._retrieve_interaction_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._build_session_context_chunks",
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory.gate_by_relevance",
            return_value=(gated_chunks, 1),
        ),
        patch(
            "src.app.domain.services.handlers.memory.answer_from_memory",
            new_callable=AsyncMock,
            return_value=memory_answer,
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_episode_access",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_note_access",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.memory.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ),
    ):
        from src.app.domain.services.handlers.memory import handle_memory

        result = await handle_memory(message, AsyncMock(), AsyncMock(), intent)

    assert result.metadata["chunks_filtered"] == 1


@pytest.mark.asyncio
async def test_handle_memory_episode_only_records_episode_access():
    """handle_memory records episode access when only episodes are retrieved."""
    message = _make_message()
    intent = _make_intent()
    episode_chunk = _make_episode_chunk()
    memory_answer = _make_memory_answer()

    with (
        patch(
            "src.app.domain.services.handlers.memory._retrieve_context",
            new_callable=AsyncMock,
            return_value=[episode_chunk],
        ),
        patch(
            "src.app.domain.services.handlers.memory._retrieve_interaction_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._build_session_context_chunks",
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory.gate_by_relevance",
            return_value=([episode_chunk], 0),
        ),
        patch(
            "src.app.domain.services.handlers.memory.answer_from_memory",
            new_callable=AsyncMock,
            return_value=memory_answer,
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_episode_access",
            new_callable=AsyncMock,
        ) as mock_episode_access,
        patch(
            "src.app.domain.services.handlers.memory.record_note_access",
            new_callable=AsyncMock,
        ) as mock_note_access,
        patch(
            "src.app.domain.services.handlers.memory.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ),
    ):
        from src.app.domain.services.handlers.memory import handle_memory

        result = await handle_memory(message, AsyncMock(), AsyncMock(), intent)

    assert result.agent == "memory"
    mock_episode_access.assert_awaited_once()
    mock_note_access.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_memory_note_only_records_note_access():
    """handle_memory records note access when only notes are retrieved."""
    message = _make_message()
    intent = _make_intent()
    note_chunk = _make_note_chunk()
    memory_answer = _make_memory_answer()

    with (
        patch(
            "src.app.domain.services.handlers.memory._retrieve_context",
            new_callable=AsyncMock,
            return_value=[note_chunk],
        ),
        patch(
            "src.app.domain.services.handlers.memory._retrieve_interaction_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._build_session_context_chunks",
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory.gate_by_relevance",
            return_value=([note_chunk], 0),
        ),
        patch(
            "src.app.domain.services.handlers.memory.answer_from_memory",
            new_callable=AsyncMock,
            return_value=memory_answer,
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_episode_access",
            new_callable=AsyncMock,
        ) as mock_episode_access,
        patch(
            "src.app.domain.services.handlers.memory.record_note_access",
            new_callable=AsyncMock,
        ) as mock_note_access,
        patch(
            "src.app.domain.services.handlers.memory.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ),
    ):
        from src.app.domain.services.handlers.memory import handle_memory

        result = await handle_memory(message, AsyncMock(), AsyncMock(), intent)

    assert result.agent == "memory"
    mock_episode_access.assert_not_awaited()
    mock_note_access.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_memory_access_recording_failure_propagates():
    """handle_memory should fail when access recording fails."""
    message = _make_message()
    intent = _make_intent()
    context_chunks = _make_context_chunks()
    memory_answer = _make_memory_answer()

    with (
        patch(
            "src.app.domain.services.handlers.memory._retrieve_context",
            new_callable=AsyncMock,
            return_value=context_chunks,
        ),
        patch(
            "src.app.domain.services.handlers.memory._retrieve_interaction_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._build_session_context_chunks",
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory.gate_by_relevance",
            return_value=(context_chunks, 0),
        ),
        patch(
            "src.app.domain.services.handlers.memory.answer_from_memory",
            new_callable=AsyncMock,
            return_value=memory_answer,
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_episode_access",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_note_access",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.memory.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ),
        pytest.raises(
            DatabaseError,
            match="Memory access recording failed with RuntimeError: boom",
        ),
    ):
        from src.app.domain.services.handlers.memory import handle_memory

        await handle_memory(message, AsyncMock(), AsyncMock(), intent)


@pytest.mark.asyncio
async def test_handle_memory_entity_extraction_failure_is_swallowed():
    """handle_memory should still return the answer when entity extraction fails."""
    message = _make_message()
    intent = _make_intent()
    context_chunks = _make_context_chunks()
    memory_answer = _make_memory_answer()

    with (
        patch(
            "src.app.domain.services.handlers.memory._retrieve_context",
            new_callable=AsyncMock,
            return_value=context_chunks,
        ),
        patch(
            "src.app.domain.services.handlers.memory._retrieve_interaction_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._build_session_context_chunks",
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory.gate_by_relevance",
            return_value=(context_chunks, 0),
        ),
        patch(
            "src.app.domain.services.handlers.memory.answer_from_memory",
            new_callable=AsyncMock,
            return_value=memory_answer,
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_episode_access",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_note_access",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.memory.enqueue_entity_extraction",
            new_callable=AsyncMock,
            side_effect=RuntimeError("enqueue failed"),
        ),
    ):
        from src.app.domain.services.handlers.memory import handle_memory

        result = await handle_memory(message, AsyncMock(), AsyncMock(), intent)

    assert result.agent == "memory"
    assert result.content == memory_answer.answer


@pytest.mark.asyncio
async def test_handle_memory_uses_interaction_fallback():
    """Memory queries can answer from persisted interaction history when RAG is empty."""
    message = _make_message("What was I working on yesterday?")
    intent = _make_intent()
    interaction_chunk = {
        "content": (
            "Interaction on 2026-04-09 18:00 UTC. You asked: Fix the Telegram webhook and "
            "deploy the worker healthcheck fix."
        ),
        "score": 0.82,
        "source_type": "interaction",
        "source_id": str(uuid.uuid4()),
        "search_method": "interaction_history",
    }
    memory_answer = _make_memory_answer()
    memory_answer.answer = "Yesterday you were fixing Telegram delivery and the worker healthcheck."

    with (
        patch(
            "src.app.domain.services.handlers.memory._retrieve_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._retrieve_interaction_context",
            new_callable=AsyncMock,
            return_value=[interaction_chunk],
        ),
        patch(
            "src.app.domain.services.handlers.memory._build_session_context_chunks",
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory.gate_by_relevance",
            return_value=([interaction_chunk], 0),
        ),
        patch(
            "src.app.domain.services.handlers.memory.answer_from_memory",
            new_callable=AsyncMock,
            return_value=memory_answer,
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_episode_access",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_note_access",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.memory.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ),
    ):
        from src.app.domain.services.handlers.memory import handle_memory

        result = await handle_memory(message, AsyncMock(), AsyncMock(), intent)

    assert "Telegram delivery" in result.content
    assert "interaction" in result.metadata["source_types"]


@pytest.mark.asyncio
async def test_handle_memory_meta_query_returns_capability_reply():
    """Assistant meta-questions should not dead-end with a fake memory miss."""
    message = _make_message("Explain how you work")
    intent = _make_intent()

    with (
        patch(
            "src.app.domain.services.handlers.memory._retrieve_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._retrieve_interaction_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._build_session_context_chunks",
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory.gate_by_relevance",
            return_value=([], 0),
        ),
    ):
        from src.app.domain.services.handlers.memory import handle_memory

        result = await handle_memory(message, AsyncMock(), AsyncMock(), intent)

    assert "three layers" in result.content
    assert result.metadata["search_method"] == "capabilities"


@pytest.mark.asyncio
async def test_handle_memory_meta_query_short_circuits_before_retrieval():
    """Meta-questions should bypass retrieval even when history exists."""
    message = _make_message("Explain how you work?")
    intent = _make_intent()

    with (
        patch(
            "src.app.domain.services.handlers.memory._retrieve_context",
            new_callable=AsyncMock,
        ) as mock_retrieve_context,
        patch(
            "src.app.domain.services.handlers.memory._retrieve_interaction_context",
            new_callable=AsyncMock,
        ) as mock_retrieve_interactions,
        patch(
            "src.app.domain.services.handlers.memory._build_session_context_chunks",
        ) as mock_session_chunks,
    ):
        from src.app.domain.services.handlers.memory import handle_memory

        result = await handle_memory(message, AsyncMock(), AsyncMock(), intent)

    assert "three layers" in result.content
    assert result.metadata["search_method"] == "capabilities"
    mock_retrieve_context.assert_not_awaited()
    mock_retrieve_interactions.assert_not_awaited()
    mock_session_chunks.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_context_unified_success():
    """_retrieve_context returns unified results across all stores."""
    mock_embedder = AsyncMock()
    mock_embedder.embed_single = AsyncMock(return_value=[0.1] * 768)
    mock_embedder.close = AsyncMock()

    ep_id = str(uuid.uuid4())
    unified_results = [
        UnifiedResult(
            content="Test content",
            source_type="episode",
            source_id=ep_id,
            score=0.0164,
            metadata={"episode_type": "diary"},
        )
    ]

    mock_session = AsyncMock()

    with (
        patch("src.app.domain.services.handlers.memory.get_settings") as mock_settings,
        patch(
            "src.app.domain.services.handlers.memory.OllamaEmbeddings",
            return_value=mock_embedder,
        ),
        patch(
            "src.app.domain.services.handlers.memory.unified_search",
            new_callable=AsyncMock,
            return_value=unified_results,
        ),
    ):
        mock_settings.return_value = MagicMock(
            ollama_host="http://localhost:11434",
            ollama_embed_model="nomic-embed-text:v2-moe",
            default_search_limit=10,
        )

        from src.app.domain.services.handlers.memory import _retrieve_context

        result = await _retrieve_context("test query", mock_session)

    assert len(result) == 1
    assert result[0]["search_method"] == "unified"
    assert result[0]["content"] == "Test content"
    assert result[0]["source_id"] == ep_id
    assert result[0]["source_type"] == "episode"


@pytest.mark.asyncio
async def test_retrieve_context_raises_on_embedding_error():
    """_retrieve_context raises EmbeddingError — no silent fallback."""
    mock_session = AsyncMock()

    with (
        patch("src.app.domain.services.handlers.memory.get_settings") as mock_settings,
        patch(
            "src.app.domain.services.handlers.memory.OllamaEmbeddings",
            side_effect=EmbeddingError("Ollama down"),
        ),
    ):
        mock_settings.return_value = MagicMock(
            ollama_host="http://localhost:11434",
            ollama_embed_model="nomic-embed-text:v2-moe",
            default_search_limit=10,
        )

        from src.app.domain.services.handlers.memory import _retrieve_context

        with pytest.raises(EmbeddingError, match="Ollama down"):
            await _retrieve_context("test query", mock_session)


@pytest.mark.asyncio
async def test_retrieve_context_closes_embedder_on_embedding_failure():
    """_retrieve_context closes the embedder even when embedding fails."""
    mock_embedder = AsyncMock()
    mock_embedder.embed_single = AsyncMock(side_effect=EmbeddingError("Ollama down"))
    mock_embedder.close = AsyncMock()
    mock_session = AsyncMock()

    with (
        patch("src.app.domain.services.handlers.memory.get_settings") as mock_settings,
        patch(
            "src.app.domain.services.handlers.memory.OllamaEmbeddings",
            return_value=mock_embedder,
        ),
    ):
        mock_settings.return_value = MagicMock(
            ollama_host="http://localhost:11434",
            ollama_embed_model="nomic-embed-text:v2-moe",
            default_search_limit=10,
        )

        from src.app.domain.services.handlers.memory import _retrieve_context

        with pytest.raises(EmbeddingError, match="Ollama down"):
            await _retrieve_context("test query", mock_session)

    mock_embedder.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_context_returns_empty_on_no_results():
    """_retrieve_context returns empty list when unified search finds nothing."""
    mock_embedder = AsyncMock()
    mock_embedder.embed_single = AsyncMock(return_value=[0.1] * 768)
    mock_embedder.close = AsyncMock()

    mock_session = AsyncMock()

    with (
        patch("src.app.domain.services.handlers.memory.get_settings") as mock_settings,
        patch(
            "src.app.domain.services.handlers.memory.OllamaEmbeddings",
            return_value=mock_embedder,
        ),
        patch(
            "src.app.domain.services.handlers.memory.unified_search",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        mock_settings.return_value = MagicMock(
            ollama_host="http://localhost:11434",
            ollama_embed_model="nomic-embed-text:v2-moe",
            default_search_limit=10,
        )

        from src.app.domain.services.handlers.memory import _retrieve_context

        result = await _retrieve_context("test query", mock_session)

    assert result == []


def test_resolve_time_window_uses_local_timezone_for_yesterday():
    """Relative-day windows should be computed in user local time, then converted to UTC."""
    with patch("src.app.domain.services.handlers.memory.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(user_timezone="Europe/London")
        from src.app.domain.services.handlers.memory import _resolve_time_window

        start, end = _resolve_time_window(
            "What was I doing yesterday?",
            now=datetime(2026, 4, 11, 0, 30, tzinfo=UTC),
        ) or (None, None)

    assert start == datetime(2026, 4, 9, 23, 0, tzinfo=UTC)
    assert end == datetime(2026, 4, 10, 23, 0, tzinfo=UTC)


def test_build_empty_memory_reply_includes_absolute_date_for_time_queries():
    window = (
        datetime(2026, 4, 10, 0, 0, tzinfo=UTC),
        datetime(2026, 4, 11, 0, 0, tzinfo=UTC),
    )
    with (
        patch(
            "src.app.domain.services.handlers.memory._resolve_time_window",
            return_value=window,
        ),
        patch("src.app.domain.services.handlers.memory.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(user_timezone="Europe/London")
        from src.app.domain.services.handlers.memory import _build_empty_memory_reply

        reply = _build_empty_memory_reply("What was I doing yesterday?")

    assert "Friday April 10, 2026" in reply


@pytest.mark.asyncio
async def test_retrieve_interaction_context_sanitizes_internal_parse_prefix():
    """Interaction fallback chunks should not include leaked parse-failure wrappers."""
    interaction = MagicMock()
    interaction.id = uuid.uuid4()
    interaction.user_message = "What did I work on?"
    interaction.response_content = (
        "Failed to parse diary agent response: You shipped deployment and fixed webhook retries."
    )
    interaction.response_agent = "memory"
    interaction.specialist = "memory"
    interaction.source = "telegram"
    interaction.created_at = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)

    with (
        patch(
            "src.app.domain.services.handlers.memory.get_recent_interactions_for_user",
            new_callable=AsyncMock,
            return_value=[interaction],
        ),
        patch("src.app.domain.services.handlers.memory.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(
            relevance_threshold=0.0,
            user_timezone="Europe/London",
        )
        from src.app.domain.services.handlers.memory import _retrieve_interaction_context

        chunks = await _retrieve_interaction_context(
            "What was I working on yesterday?",
            AsyncMock(),
            user_id="user-1",
        )

    assert len(chunks) == 1
    content = chunks[0]["content"]
    assert "Failed to parse" not in content
    assert "You shipped deployment and fixed webhook retries." in content


@pytest.mark.asyncio
async def test_retrieve_interaction_context_sanitizes_embedded_parse_wrapper():
    """Parse wrappers embedded after source preambles should still be stripped."""
    interaction = MagicMock()
    interaction.id = uuid.uuid4()
    interaction.user_message = "What did I work on?"
    interaction.response_content = (
        "Sources (2): item A item B Failed to parse diary agent response: "
        "You shipped deployment and fixed webhook retries."
    )
    interaction.response_agent = "memory"
    interaction.specialist = "memory"
    interaction.source = "telegram"
    interaction.created_at = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)

    with (
        patch(
            "src.app.domain.services.handlers.memory.get_recent_interactions_for_user",
            new_callable=AsyncMock,
            return_value=[interaction],
        ),
        patch("src.app.domain.services.handlers.memory.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(
            relevance_threshold=0.0,
            user_timezone="Europe/London",
        )
        from src.app.domain.services.handlers.memory import _retrieve_interaction_context

        chunks = await _retrieve_interaction_context(
            "What was I working on yesterday?",
            AsyncMock(),
            user_id="user-1",
        )

    assert len(chunks) == 1
    content = chunks[0]["content"]
    assert "Failed to parse" not in content
    assert "Sources (" not in content
    assert "You shipped deployment and fixed webhook retries." in content


@pytest.mark.asyncio
async def test_retrieve_interaction_context_falls_back_to_owner_history_in_private_mode():
    """Telegram recall should include owner/API history for private single-user deployments."""
    owner_interaction = MagicMock()
    owner_interaction.id = uuid.uuid4()
    owner_interaction.user_message = "What was I working on?"
    owner_interaction.response_content = (
        "You shipped the frontend deployment and fixed webhook retries."
    )
    owner_interaction.response_agent = "memory"
    owner_interaction.specialist = "memory"
    owner_interaction.source = "api"
    owner_interaction.created_at = datetime(2026, 4, 10, 16, 0, tzinfo=UTC)

    with (
        patch(
            "src.app.domain.services.handlers.memory.get_recent_interactions_for_user",
            new_callable=AsyncMock,
            side_effect=[[], [owner_interaction]],
        ) as mock_recent,
        patch("src.app.domain.services.handlers.memory.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(
            relevance_threshold=0.0,
            user_timezone="Europe/London",
            private_single_user_mode=True,
        )
        from src.app.domain.services.handlers.memory import _retrieve_interaction_context

        chunks = await _retrieve_interaction_context(
            "What was I working on yesterday?",
            AsyncMock(),
            user_id="12345",
        )

    assert len(chunks) == 1
    assert "frontend deployment" in chunks[0]["content"]
    assert mock_recent.await_count == 2
    assert mock_recent.await_args_list[0].kwargs["user_id"] == "12345"
    assert mock_recent.await_args_list[1].kwargs["user_id"] == "owner"
