"""Hybrid search — BM25 + vector search with Reciprocal Rank Fusion (RRF).

Includes relevance gating to filter low-quality results that would introduce
context rot (low-relevance content actively degrades LLM output quality).
"""

import json

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import get_settings

logger = structlog.get_logger()


async def hybrid_search(
    session: AsyncSession,
    query: str,
    query_embedding: list[float],
    limit: int | None = None,
    *,
    min_score: float = 0.0,
    decay_rate: float | None = None,
) -> list[dict]:
    """Hybrid search combining BM25 full-text and vector similarity.

    Uses Reciprocal Rank Fusion: score = 1/(rank_bm25 + k) + 1/(rank_vector + k)
    with recency decay and access boosting.

    Parameters
    ----------
    min_score:
        Minimum RRF score to include in results.  Chunks below this threshold
        are filtered to prevent context rot.  Default 0.0 (no filtering —
        use :func:`~context_manager.gate_by_relevance` for application-level
        gating).
    decay_rate:
        Controls how fast old items fade.  0.01 = very slow (personal assistant
        default), 0.1 = fast.  ``None`` reads from ``settings.memory_decay_rate``.
    """
    if not query_embedding or not isinstance(query_embedding, list):
        msg = "query_embedding must be a non-empty list of floats"
        raise ValueError(msg)
    if not all(isinstance(v, (int, float)) for v in query_embedding):
        msg = "query_embedding must contain only numeric values"
        raise ValueError(msg)

    settings = get_settings()
    if limit is None:
        limit = settings.default_search_limit
    if decay_rate is None:
        decay_rate = settings.memory_decay_rate
    rrf_k = settings.rrf_k

    sub_limit = limit * 2
    result = await session.execute(
        text("""
            WITH bm25 AS (
                SELECT id, content, summary, episode_type, para_category,
                       tags, created_at, access_count,
                       ROW_NUMBER() OVER (
                           ORDER BY ts_rank(search_vector,
                                           plainto_tsquery('english', :query)) DESC
                       ) AS rank
                FROM episodes
                WHERE deleted_at IS NULL
                  AND search_vector @@ plainto_tsquery('english', :query)
                LIMIT :sub_limit
            ),
            vector AS (
                SELECT id, content, summary, episode_type, para_category,
                       tags, created_at, access_count,
                       ROW_NUMBER() OVER (
                           ORDER BY embedding <=> CAST(:embedding AS vector)
                       ) AS rank
                FROM episodes
                WHERE deleted_at IS NULL
                  AND embedding IS NOT NULL
                LIMIT :sub_limit
            ),
            fused AS (
                SELECT
                    COALESCE(b.id, v.id) AS id,
                    COALESCE(b.content, v.content) AS content,
                    COALESCE(b.summary, v.summary) AS summary,
                    COALESCE(b.episode_type, v.episode_type) AS episode_type,
                    COALESCE(b.para_category, v.para_category) AS para_category,
                    COALESCE(b.tags, v.tags) AS tags,
                    COALESCE(b.created_at, v.created_at) AS created_at,
                    COALESCE(b.access_count, v.access_count) AS access_count,
                    COALESCE(1.0 / (b.rank + :k), 0) +
                    COALESCE(1.0 / (v.rank + :k), 0) AS rrf_score
                FROM bm25 b
                FULL OUTER JOIN vector v ON b.id = v.id
            )
            SELECT
                id, content, summary, episode_type, para_category,
                tags, created_at, access_count,
                rrf_score
                    * (1.0 / (1.0 + EXTRACT(EPOCH FROM (NOW() - created_at))
                        / 86400.0 * :decay_rate))
                    * (1.0 + LN(1 + access_count) * 0.1)
                AS rrf_score
            FROM fused
            ORDER BY rrf_score DESC
            LIMIT :limit
        """),
        {
            "query": query,
            "embedding": json.dumps(query_embedding, separators=(",", ":")),
            "k": rrf_k,
            "sub_limit": sub_limit,
            "limit": limit,
            "decay_rate": decay_rate,
        },
    )

    rows = [dict(r) for r in result.mappings().all()]

    # Apply minimum score filter if specified
    if min_score > 0:
        before = len(rows)
        rows = [r for r in rows if r.get("rrf_score", 0) >= min_score]
        if len(rows) < before:
            logger.info(
                "hybrid_search_relevance_filtered",
                before=before,
                after=len(rows),
                min_score=min_score,
            )

    logger.info("hybrid_search", query_length=len(query), results=len(rows))
    return rows
