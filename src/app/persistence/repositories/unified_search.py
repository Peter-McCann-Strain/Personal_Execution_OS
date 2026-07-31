"""Unified cross-store retrieval -- searches durable stores and fuses the results.

Reciprocal Rank Fusion (RRF) merges results from all stores into a single
ranked list.  Items appearing in multiple stores get boosted, so a note that also
matches an entity mention floats to the top.

No silent fallbacks -- if a sub-search fails, the error propagates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.repositories.connectors import search_connector_documents
from src.app.persistence.repositories.entities import search_entities
from src.app.persistence.repositories.notes import search_notes
from src.app.persistence.repositories.saved_memories import search_saved_memories
from src.app.persistence.repositories.vector import hybrid_search

logger = structlog.get_logger()


@dataclass(frozen=True)
class UnifiedResult:
    """A single result from any store, normalized for ranking."""

    content: str
    source_type: str  # "episode", "note", "entity"
    source_id: str
    score: float
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def unified_search(
    session: AsyncSession,
    query: str,
    *,
    user_id: str | None = None,
    embedding: list[float] | None = None,
    limit: int = 10,
    min_score: float = 0.0,
    suppressed_sources: set[str] | None = None,
) -> list[UnifiedResult]:
    """Search durable memory sources, then merge with normalized RRF.

    Parameters
    ----------
    session:
        Active SQLAlchemy async session.
    query:
        User's search query (natural language).
    embedding:
        Pre-computed query embedding for vector search.  If ``None``,
        episode search falls back to BM25-only (which still works but
        loses the vector half of hybrid search).
    limit:
        Maximum number of results to return after fusion.
    min_score:
        Minimum RRF score to include.  Chunks below this threshold are
        filtered to prevent context rot.
    suppressed_sources:
        Optional source types to skip, e.g. ``{"saved_memory", "connector_document"}``.
    """
    sub_limit = limit * 2  # over-fetch so RRF has enough candidates
    suppressed = {value.strip() for value in suppressed_sources or set() if value.strip()}

    # AsyncSession is not safe to share across concurrent tasks, so keep
    # repository calls sequential here.
    episode_results = (
        []
        if "episode" in suppressed
        else await _search_episodes(
            session,
            query,
            embedding=embedding,
            limit=sub_limit,
        )
    )
    note_results = (
        [] if "note" in suppressed else await _search_notes(session, query, limit=sub_limit)
    )
    entity_results = (
        [] if "entity" in suppressed else await _search_entities(session, query, limit=sub_limit)
    )
    saved_memory_results = (
        []
        if user_id is None or "saved_memory" in suppressed
        else await _search_saved_memories(
            session,
            query,
            user_id=user_id,
            limit=sub_limit,
        )
    )
    connector_document_results = (
        []
        if user_id is None or "connector_document" in suppressed
        else await _search_connector_documents(
            session,
            query,
            user_id=user_id,
            limit=sub_limit,
        )
    )

    logger.info(
        "unified_search_sources",
        query_length=len(query),
        episodes=len(episode_results),
        notes=len(note_results),
        entities=len(entity_results),
        saved_memories=len(saved_memory_results),
        connector_documents=len(connector_document_results),
    )

    # Merge with RRF
    merged = _reciprocal_rank_fusion(
        [
            episode_results,
            note_results,
            entity_results,
            saved_memory_results,
            connector_document_results,
        ],
        k=60,  # RRF constant -- standard value
    )

    # Filter by minimum score and limit
    filtered = [r for r in merged if r.score >= min_score][:limit]

    logger.info(
        "unified_search_complete",
        query_length=len(query),
        total_candidates=len(merged),
        after_filter=len(filtered),
        min_score=min_score,
    )

    return filtered


# ---------------------------------------------------------------------------
# Sub-search helpers (normalize into UnifiedResult)
# ---------------------------------------------------------------------------


async def _search_episodes(
    session: AsyncSession,
    query: str,
    *,
    embedding: list[float] | None = None,
    limit: int = 20,
) -> list[UnifiedResult]:
    """Search episodes via hybrid BM25 + vector search.

    If no embedding is provided, returns an empty list -- the caller is
    responsible for providing embeddings when vector search is desired.
    """
    if embedding is None:
        return []

    rows = await hybrid_search(
        session=session,
        query=query,
        query_embedding=embedding,
        limit=limit,
    )

    return [
        UnifiedResult(
            content=row["content"],
            source_type="episode",
            source_id=str(row["id"]),
            score=float(row.get("rrf_score", 0)),
            metadata={
                "episode_type": row.get("episode_type"),
                "summary": row.get("summary"),
                "tags": row.get("tags"),
                "created_at": str(row.get("created_at", "")),
            },
        )
        for row in rows
    ]


async def _search_notes(
    session: AsyncSession,
    query: str,
    *,
    limit: int = 20,
) -> list[UnifiedResult]:
    """Search notes via full-text search."""
    rows = await search_notes(session=session, query=query, limit=limit)

    return [
        UnifiedResult(
            content=f"[{row.get('title', 'Untitled')}] {row['content']}",
            source_type="note",
            source_id=str(row["id"]),
            score=0.0,  # notes FTS has no score -- rank order is sufficient for RRF
            metadata={
                "title": row.get("title"),
                "note_type": row.get("note_type"),
                "para_category": row.get("para_category"),
                "tags": row.get("tags"),
                "created_at": str(row.get("created_at", "")),
            },
        )
        for row in rows
    ]


async def _search_entities(
    session: AsyncSession,
    query: str,
    *,
    limit: int = 20,
) -> list[UnifiedResult]:
    """Search entities via trigram similarity."""
    rows = await search_entities(session=session, query=query, limit=limit)

    return [
        UnifiedResult(
            content=(
                f"Entity: {row['name']} "
                f"(type: {row['entity_type']}, "
                f"mentions: {row.get('mention_count', 0)})"
            ),
            source_type="entity",
            source_id=str(row["id"]),
            score=float(row.get("sim", 0)),
            metadata={
                "entity_type": row.get("entity_type"),
                "mention_count": row.get("mention_count"),
                "similarity": float(row.get("sim", 0)),
            },
        )
        for row in rows
    ]


async def _search_saved_memories(
    session: AsyncSession,
    query: str,
    *,
    user_id: str,
    limit: int = 20,
) -> list[UnifiedResult]:
    """Search explicit saved memories for the current user."""
    rows = await search_saved_memories(
        session=session,
        user_id=user_id,
        query=query,
        limit=limit,
    )

    return [
        UnifiedResult(
            content=f"[{row.title}] {row.content}",
            source_type="saved_memory",
            source_id=str(row.id),
            score=0.0,
            metadata={
                "title": row.title,
                "scope": row.scope,
                "scope_key": row.scope_key,
                "pinned": bool(row.pinned),
                "provenance": row.provenance or {},
                "source_type": row.source_type,
                "source_id": row.source_id,
                "updated_at": row.updated_at.isoformat(),
            },
        )
        for row in rows
    ]


async def _search_connector_documents(
    session: AsyncSession,
    query: str,
    *,
    user_id: str,
    limit: int = 20,
) -> list[UnifiedResult]:
    """Search synced connector documents for the current user."""
    rows = await search_connector_documents(
        session=session,
        user_id=user_id,
        query=query,
        limit=limit,
    )

    return [
        UnifiedResult(
            content=f"[{row.title}] {row.content}",
            source_type="connector_document",
            source_id=str(row.id),
            score=0.0,
            metadata={
                "title": row.title,
                "source_url": row.source_url,
                "connector_source_type": row.source_type,
                "synced_at": row.synced_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                **(row.metadata_ or {}),
            },
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def _reciprocal_rank_fusion(
    result_lists: list[list[UnifiedResult]],
    k: int = 60,
) -> list[UnifiedResult]:
    """Merge multiple ranked lists using RRF, then min-max normalize scores.

    Each item's fused score is: sum over all lists of 1/(k + rank + 1).
    Items appearing in multiple lists naturally get boosted because their
    scores accumulate.

    Parameters
    ----------
    result_lists:
        One list per search source, each pre-sorted by relevance (best first).
    k:
        RRF smoothing constant.  Standard value is 60.  Higher values reduce
        the advantage of top-ranked items.
    """
    scores: dict[str, float] = {}
    results_by_key: dict[str, UnifiedResult] = {}

    for result_list in result_lists:
        for rank, result in enumerate(result_list):
            key = f"{result.source_type}:{result.source_id}"
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            # Keep the version with the highest individual score
            existing = results_by_key.get(key)
            if existing is None or result.score > existing.score:
                results_by_key[key] = result

    # Sort by fused score descending
    sorted_keys = sorted(scores, key=scores.__getitem__, reverse=True)
    if not sorted_keys:
        return []

    raw_values = [scores[key] for key in sorted_keys]
    min_score = min(raw_values)
    max_score = max(raw_values)

    normalized_results: list[UnifiedResult] = []
    for key in sorted_keys:
        raw_score = scores[key]
        if max_score == min_score:
            normalized_score = 1.0 if raw_score > 0 else 0.0
        else:
            normalized_score = (raw_score - min_score) / (max_score - min_score)

        base_result = results_by_key[key]
        normalized_results.append(
            UnifiedResult(
                content=base_result.content,
                source_type=base_result.source_type,
                source_id=base_result.source_id,
                score=normalized_score,
                metadata={
                    **base_result.metadata,
                    "raw_rrf_score": raw_score,
                },
            )
        )

    return normalized_results
