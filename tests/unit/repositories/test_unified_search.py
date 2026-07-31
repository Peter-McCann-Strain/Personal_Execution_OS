"""Tests for unified cross-store retrieval — RRF merge across episodes, notes, entities."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.persistence.repositories.unified_search import (
    UnifiedResult,
    _reciprocal_rank_fusion,
    _search_connector_documents,
    _search_entities,
    _search_episodes,
    _search_notes,
    _search_saved_memories,
    unified_search,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


def _make_result(
    content: str = "test content",
    source_type: str = "episode",
    source_id: str | None = None,
    score: float = 0.5,
    metadata: dict | None = None,
) -> UnifiedResult:
    """Create a UnifiedResult for testing."""
    return UnifiedResult(
        content=content,
        source_type=source_type,
        source_id=source_id or str(uuid.uuid4()),
        score=score,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# UnifiedResult dataclass
# ---------------------------------------------------------------------------


class TestUnifiedResult:
    def test_creation(self):
        """UnifiedResult should store all fields correctly."""
        r = UnifiedResult(
            content="Hello world",
            source_type="note",
            source_id="abc-123",
            score=0.75,
            metadata={"title": "My Note"},
        )
        assert r.content == "Hello world"
        assert r.source_type == "note"
        assert r.source_id == "abc-123"
        assert r.score == 0.75
        assert r.metadata == {"title": "My Note"}

    def test_frozen(self):
        """UnifiedResult should be immutable (frozen dataclass)."""
        r = _make_result()
        with pytest.raises(AttributeError):
            r.score = 1.0  # type: ignore[misc]

    def test_default_metadata(self):
        """UnifiedResult should default metadata to empty dict."""
        r = UnifiedResult(
            content="x",
            source_type="episode",
            source_id="1",
            score=0.0,
        )
        assert r.metadata == {}

    def test_equality(self):
        """Two UnifiedResults with same fields should be equal."""
        kwargs = {
            "content": "same",
            "source_type": "note",
            "source_id": "id-1",
            "score": 0.5,
            "metadata": {},
        }
        assert UnifiedResult(**kwargs) == UnifiedResult(**kwargs)


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


class TestReciprocalRankFusion:
    def test_single_list(self):
        """RRF with a single list should preserve order and assign scores."""
        items = [
            _make_result(content="first", source_type="episode", source_id="1"),
            _make_result(content="second", source_type="episode", source_id="2"),
            _make_result(content="third", source_type="episode", source_id="3"),
        ]
        merged = _reciprocal_rank_fusion([items], k=60)

        assert len(merged) == 3
        assert merged[0].content == "first"
        assert merged[1].content == "second"
        assert merged[2].content == "third"
        # Scores should be decreasing
        assert merged[0].score > merged[1].score > merged[2].score

    def test_single_list_scores(self):
        """RRF scores are normalized into a stable 0..1 range."""
        items = [
            _make_result(source_type="note", source_id="a"),
            _make_result(source_type="note", source_id="b"),
        ]
        merged = _reciprocal_rank_fusion([items], k=60)

        assert merged[0].score == pytest.approx(1.0)
        assert merged[1].score == pytest.approx(0.0)
        assert merged[0].metadata["raw_rrf_score"] == pytest.approx(1.0 / 61)
        assert merged[1].metadata["raw_rrf_score"] == pytest.approx(1.0 / 62)

    def test_multiple_lists_no_overlap(self):
        """RRF with non-overlapping lists should interleave by score."""
        list_a = [_make_result(source_type="episode", source_id="ep-1")]
        list_b = [_make_result(source_type="note", source_id="note-1")]
        list_c = [_make_result(source_type="entity", source_id="ent-1")]

        merged = _reciprocal_rank_fusion([list_a, list_b, list_c], k=60)

        assert len(merged) == 3
        # All rank-0 items from different lists get the same normalized score
        assert merged[0].score == pytest.approx(1.0)
        assert merged[1].score == pytest.approx(1.0)
        assert merged[2].score == pytest.approx(1.0)

    def test_overlapping_results_get_boosted(self):
        """Items appearing in multiple lists should have higher fused scores."""
        shared_id = "shared-123"
        # Same item in two lists
        list_a = [
            _make_result(source_type="episode", source_id=shared_id, content="shared"),
            _make_result(source_type="episode", source_id="only-a"),
        ]
        list_b = [
            _make_result(source_type="episode", source_id=shared_id, content="shared"),
            _make_result(source_type="episode", source_id="only-b"),
        ]

        merged = _reciprocal_rank_fusion([list_a, list_b], k=60)

        # The shared item should be ranked first (boosted by appearing in both lists)
        assert merged[0].source_id == shared_id
        assert merged[0].score == pytest.approx(1.0)
        assert merged[0].metadata["raw_rrf_score"] == pytest.approx(2.0 / 61)

        # Non-shared items should have lower scores
        non_shared = [r for r in merged if r.source_id != shared_id]
        for r in non_shared:
            assert r.score < merged[0].score

    def test_empty_lists(self):
        """RRF with all empty lists should return empty list."""
        merged = _reciprocal_rank_fusion([[], [], []])
        assert merged == []

    def test_some_empty_lists(self):
        """RRF should handle a mix of empty and non-empty lists."""
        items = [_make_result(source_type="note", source_id="n-1")]
        merged = _reciprocal_rank_fusion([[], items, []])

        assert len(merged) == 1
        assert merged[0].source_id == "n-1"

    def test_no_lists(self):
        """RRF with no lists at all should return empty list."""
        merged = _reciprocal_rank_fusion([])
        assert merged == []

    def test_k_parameter_affects_raw_scores(self):
        """Lower k should produce higher raw RRF scores for top-ranked items."""
        items = [_make_result(source_type="episode", source_id="x")]

        merged_low_k = _reciprocal_rank_fusion([items], k=10)
        merged_high_k = _reciprocal_rank_fusion([items], k=100)

        assert (
            merged_low_k[0].metadata["raw_rrf_score"] > merged_high_k[0].metadata["raw_rrf_score"]
        )

    def test_preserves_metadata(self):
        """RRF should preserve metadata from the original results."""
        items = [
            _make_result(
                source_type="note",
                source_id="n-1",
                metadata={"title": "Important"},
            ),
        ]
        merged = _reciprocal_rank_fusion([items])

        assert merged[0].metadata["title"] == "Important"
        assert "raw_rrf_score" in merged[0].metadata

    def test_overlap_keeps_highest_scoring_metadata(self):
        """When an item appears in multiple lists, keep the version with higher score."""
        shared_id = "dup-1"
        list_a = [
            _make_result(
                source_type="episode",
                source_id=shared_id,
                score=0.3,
                metadata={"from": "a"},
            ),
        ]
        list_b = [
            _make_result(
                source_type="episode",
                source_id=shared_id,
                score=0.8,
                metadata={"from": "b"},
            ),
        ]

        merged = _reciprocal_rank_fusion([list_a, list_b])

        # Should keep metadata from the higher-scoring version
        assert merged[0].metadata["from"] == "b"
        assert "raw_rrf_score" in merged[0].metadata


# ---------------------------------------------------------------------------
# Sub-search helpers (with mocked repos)
# ---------------------------------------------------------------------------


class TestSearchEpisodes:
    @pytest.mark.asyncio
    async def test_no_embedding_returns_empty(self):
        """_search_episodes should return empty list when no embedding is provided."""
        session = _make_session()
        results = await _search_episodes(session, "test query", embedding=None)
        assert results == []

    @pytest.mark.asyncio
    async def test_wraps_hybrid_search_results(self):
        """_search_episodes should wrap hybrid_search results as UnifiedResult."""
        session = _make_session()
        ep_id = uuid.uuid4()
        mock_rows = [
            {
                "id": ep_id,
                "content": "Morning routine",
                "summary": "AM routine",
                "episode_type": "diary",
                "para_category": None,
                "tags": ["morning"],
                "created_at": "2026-01-01T08:00:00",
                "rrf_score": 0.035,
            }
        ]

        with patch(
            "src.app.persistence.repositories.unified_search.hybrid_search",
            new_callable=AsyncMock,
            return_value=mock_rows,
        ):
            results = await _search_episodes(
                session,
                "morning",
                embedding=[0.1] * 768,
                limit=10,
            )

        assert len(results) == 1
        assert results[0].source_type == "episode"
        assert results[0].source_id == str(ep_id)
        assert results[0].content == "Morning routine"
        assert results[0].score == 0.035
        assert results[0].metadata["episode_type"] == "diary"

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """_search_episodes should return empty list when hybrid_search returns nothing."""
        session = _make_session()

        with patch(
            "src.app.persistence.repositories.unified_search.hybrid_search",
            new_callable=AsyncMock,
            return_value=[],
        ):
            results = await _search_episodes(
                session,
                "nothing",
                embedding=[0.1] * 3,
                limit=5,
            )

        assert results == []


class TestSearchNotes:
    @pytest.mark.asyncio
    async def test_wraps_note_results(self):
        """_search_notes should wrap search_notes results as UnifiedResult."""
        session = _make_session()
        note_id = uuid.uuid4()
        mock_rows = [
            {
                "id": note_id,
                "title": "Python Tips",
                "content": "Use dataclasses for value objects.",
                "note_type": "permanent",
                "para_category": "resource",
                "tags": ["python"],
                "created_at": "2026-02-15T10:00:00",
            }
        ]

        with patch(
            "src.app.persistence.repositories.unified_search.search_notes",
            new_callable=AsyncMock,
            return_value=mock_rows,
        ):
            results = await _search_notes(session, "python", limit=10)

        assert len(results) == 1
        assert results[0].source_type == "note"
        assert results[0].source_id == str(note_id)
        assert "[Python Tips]" in results[0].content
        assert "Use dataclasses" in results[0].content
        assert results[0].metadata["title"] == "Python Tips"

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """_search_notes should return empty list when no notes match."""
        session = _make_session()

        with patch(
            "src.app.persistence.repositories.unified_search.search_notes",
            new_callable=AsyncMock,
            return_value=[],
        ):
            results = await _search_notes(session, "nothing")

        assert results == []


class TestSearchEntities:
    @pytest.mark.asyncio
    async def test_wraps_entity_results(self):
        """_search_entities should wrap search_entities results as UnifiedResult."""
        session = _make_session()
        ent_id = uuid.uuid4()
        mock_rows = [
            {
                "id": ent_id,
                "name": "Alice Smith",
                "entity_type": "person",
                "mention_count": 5,
                "sim": 0.85,
            }
        ]

        with patch(
            "src.app.persistence.repositories.unified_search.search_entities",
            new_callable=AsyncMock,
            return_value=mock_rows,
        ):
            results = await _search_entities(session, "alice", limit=10)

        assert len(results) == 1
        assert results[0].source_type == "entity"
        assert results[0].source_id == str(ent_id)
        assert "Alice Smith" in results[0].content
        assert results[0].score == 0.85
        assert results[0].metadata["entity_type"] == "person"
        assert results[0].metadata["mention_count"] == 5

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """_search_entities should return empty list when no entities match."""
        session = _make_session()

        with patch(
            "src.app.persistence.repositories.unified_search.search_entities",
            new_callable=AsyncMock,
            return_value=[],
        ):
            results = await _search_entities(session, "nothing")

        assert results == []


class TestSearchSavedMemories:
    @pytest.mark.asyncio
    async def test_wraps_saved_memory_results(self):
        session = _make_session()
        memory = MagicMock()
        memory.id = uuid.uuid4()
        memory.title = "Working style"
        memory.content = "Prefers concise answers."
        memory.scope = "global"
        memory.scope_key = None
        memory.pinned = True
        memory.provenance = {"created_via": "manual"}
        memory.source_type = "note"
        memory.source_id = "note-1"
        memory.updated_at.isoformat.return_value = "2026-04-13T08:30:00+00:00"

        with patch(
            "src.app.persistence.repositories.unified_search.search_saved_memories",
            new_callable=AsyncMock,
            return_value=[memory],
        ):
            results = await _search_saved_memories(
                session,
                "working style",
                user_id="owner",
                limit=10,
            )

        assert len(results) == 1
        assert results[0].source_type == "saved_memory"
        assert results[0].metadata["title"] == "Working style"
        assert results[0].metadata["pinned"] is True


class TestSearchConnectorDocuments:
    @pytest.mark.asyncio
    async def test_wraps_connector_document_results(self):
        session = _make_session()
        document = MagicMock()
        document.id = uuid.uuid4()
        document.title = "Launch brief"
        document.content = "Go-to-market plan"
        document.source_url = "https://example.com/brief"
        document.source_type = "google_doc"
        document.metadata_ = {"owner": "Alex"}
        document.synced_at.isoformat.return_value = "2026-04-13T08:35:00+00:00"
        document.updated_at.isoformat.return_value = "2026-04-13T08:35:00+00:00"

        with patch(
            "src.app.persistence.repositories.unified_search.search_connector_documents",
            new_callable=AsyncMock,
            return_value=[document],
        ):
            results = await _search_connector_documents(
                session,
                "launch",
                user_id="owner",
                limit=10,
            )

        assert len(results) == 1
        assert results[0].source_type == "connector_document"
        assert results[0].metadata["title"] == "Launch brief"
        assert results[0].metadata["source_url"] == "https://example.com/brief"


# ---------------------------------------------------------------------------
# unified_search (full pipeline, mocked sub-searches)
# ---------------------------------------------------------------------------


class TestUnifiedSearch:
    @pytest.mark.asyncio
    async def test_merges_all_three_stores(self):
        """unified_search should search all three stores and merge results."""
        session = _make_session()

        ep = _make_result(content="episode hit", source_type="episode", source_id="ep-1")
        note = _make_result(content="note hit", source_type="note", source_id="note-1")
        entity = _make_result(content="entity hit", source_type="entity", source_id="ent-1")

        with (
            patch(
                "src.app.persistence.repositories.unified_search._search_episodes",
                new_callable=AsyncMock,
                return_value=[ep],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_notes",
                new_callable=AsyncMock,
                return_value=[note],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_entities",
                new_callable=AsyncMock,
                return_value=[entity],
            ),
        ):
            results = await unified_search(
                session,
                "test query",
                embedding=[0.1] * 3,
                limit=10,
            )

        assert len(results) == 3
        source_types = {r.source_type for r in results}
        assert source_types == {"episode", "note", "entity"}

    @pytest.mark.asyncio
    async def test_includes_user_scoped_saved_memories_and_connector_documents(self):
        """user_id enables saved-memory and connector-document retrieval."""
        session = _make_session()

        saved_memory = _make_result(
            content="saved memory hit",
            source_type="saved_memory",
            source_id="memory-1",
        )
        connector_document = _make_result(
            content="connector hit",
            source_type="connector_document",
            source_id="doc-1",
        )

        with (
            patch(
                "src.app.persistence.repositories.unified_search._search_episodes",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_entities",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_saved_memories",
                new_callable=AsyncMock,
                return_value=[saved_memory],
            ) as mock_memories,
            patch(
                "src.app.persistence.repositories.unified_search._search_connector_documents",
                new_callable=AsyncMock,
                return_value=[connector_document],
            ) as mock_documents,
        ):
            results = await unified_search(
                session,
                "test query",
                user_id="owner",
                embedding=[0.1] * 3,
                limit=10,
            )

        assert {result.source_type for result in results} == {
            "saved_memory",
            "connector_document",
        }
        mock_memories.assert_awaited_once()
        mock_documents.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_suppressed_sources_skip_user_scoped_stores(self):
        """suppressed_sources should skip saved memories and connector docs."""
        session = _make_session()

        with (
            patch(
                "src.app.persistence.repositories.unified_search._search_episodes",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_entities",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_saved_memories",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_memories,
            patch(
                "src.app.persistence.repositories.unified_search._search_connector_documents",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_documents,
        ):
            await unified_search(
                session,
                "test query",
                user_id="owner",
                embedding=[0.1] * 3,
                limit=10,
                suppressed_sources={"saved_memory", "connector_document"},
            )

        mock_memories.assert_not_awaited()
        mock_documents.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        """unified_search should respect the limit parameter."""
        session = _make_session()

        many_results = [_make_result(source_type="episode", source_id=f"ep-{i}") for i in range(20)]

        with (
            patch(
                "src.app.persistence.repositories.unified_search._search_episodes",
                new_callable=AsyncMock,
                return_value=many_results,
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_entities",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            results = await unified_search(
                session,
                "query",
                embedding=[0.1],
                limit=5,
            )

        assert len(results) <= 5

    @pytest.mark.asyncio
    async def test_min_score_filtering(self):
        """unified_search should filter results below normalized min_score."""
        session = _make_session()

        ep = _make_result(source_type="episode", source_id="ep-1")
        ep_low = _make_result(source_type="episode", source_id="ep-2")

        with (
            patch(
                "src.app.persistence.repositories.unified_search._search_episodes",
                new_callable=AsyncMock,
                return_value=[ep, ep_low],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_entities",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            results = await unified_search(
                session,
                "query",
                embedding=[0.1],
                limit=10,
                min_score=0.5,
            )

        assert len(results) == 1
        assert results[0].source_id == "ep-1"

    @pytest.mark.asyncio
    async def test_all_stores_empty(self):
        """unified_search should return empty list when all stores return nothing."""
        session = _make_session()

        with (
            patch(
                "src.app.persistence.repositories.unified_search._search_episodes",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_entities",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            results = await unified_search(
                session,
                "nonexistent",
                embedding=[0.1],
                limit=10,
            )

        assert results == []

    @pytest.mark.asyncio
    async def test_no_embedding_skips_episodes(self):
        """unified_search without embedding should still search notes and entities."""
        session = _make_session()

        note = _make_result(content="found note", source_type="note", source_id="n-1")
        entity = _make_result(content="found entity", source_type="entity", source_id="e-1")

        with (
            patch(
                "src.app.persistence.repositories.unified_search._search_episodes",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_ep,
            patch(
                "src.app.persistence.repositories.unified_search._search_notes",
                new_callable=AsyncMock,
                return_value=[note],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_entities",
                new_callable=AsyncMock,
                return_value=[entity],
            ),
        ):
            results = await unified_search(
                session,
                "test",
                embedding=None,
                limit=10,
            )

        # Episodes should have been called with embedding=None
        mock_ep.assert_awaited_once()
        call_kwargs = mock_ep.call_args
        assert (
            call_kwargs.kwargs.get("embedding") is None or call_kwargs[1].get("embedding") is None
        )

        # Should still have note and entity results
        assert len(results) == 2
        source_types = {r.source_type for r in results}
        assert source_types == {"note", "entity"}

    @pytest.mark.asyncio
    async def test_overlap_boosts_ranking(self):
        """Items in multiple stores should rank higher than single-store items."""
        session = _make_session()

        shared_id = "shared-item"
        # Same item appears as both an episode and via entity search
        ep_shared = _make_result(
            content="shared content",
            source_type="episode",
            source_id=shared_id,
        )
        ep_only = _make_result(
            content="episode only",
            source_type="episode",
            source_id="ep-only",
        )
        # Entity with same source_type:source_id key will merge
        entity_shared = _make_result(
            content="shared content entity",
            source_type="episode",
            source_id=shared_id,
        )

        with (
            patch(
                "src.app.persistence.repositories.unified_search._search_episodes",
                new_callable=AsyncMock,
                return_value=[ep_shared, ep_only],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.persistence.repositories.unified_search._search_entities",
                new_callable=AsyncMock,
                return_value=[entity_shared],
            ),
        ):
            results = await unified_search(
                session,
                "shared",
                embedding=[0.1],
                limit=10,
            )

        # Shared item should be ranked first
        assert results[0].source_id == shared_id

    @pytest.mark.asyncio
    async def test_sub_limit_over_fetches(self):
        """unified_search should pass sub_limit = limit * 2 to sub-searches."""
        session = _make_session()

        with (
            patch(
                "src.app.persistence.repositories.unified_search._search_episodes",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_ep,
            patch(
                "src.app.persistence.repositories.unified_search._search_notes",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_notes,
            patch(
                "src.app.persistence.repositories.unified_search._search_entities",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_ent,
        ):
            await unified_search(session, "q", embedding=[0.1], limit=5)

        # Sub-searches should receive limit=10 (5 * 2)
        assert mock_ep.call_args.kwargs.get("limit") == 10
        assert mock_notes.call_args.kwargs.get("limit") == 10
        assert mock_ent.call_args.kwargs.get("limit") == 10
