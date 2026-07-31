"""Zettelkasten link discoverer — auto-links notes via entity co-occurrence and embeddings."""

import uuid

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.async_utils import maybe_await

logger = structlog.get_logger()


async def _mapping_rows(result: object) -> list[dict]:
    """Read SQLAlchemy mapping rows while tolerating AsyncMock-based test doubles."""
    mappings = await maybe_await(result.mappings())
    rows = await maybe_await(mappings.all())
    return [dict(row) for row in rows]


async def discover_links_by_entities(
    session: AsyncSession,
    note_id: uuid.UUID,
    limit: int = 5,
) -> list[dict]:
    """Find related notes via shared entity mentions (Phase 1 — no embeddings)."""
    result = await session.execute(
        text("""
            WITH note_entities AS (
                SELECT DISTINCT entity_id
                FROM entity_mentions em
                JOIN episodes ep ON em.episode_id = ep.id
                WHERE ep.id = :note_id
            )
            SELECT DISTINCT ep2.id, ep2.summary, COUNT(*) AS shared_entities
            FROM entity_mentions em2
            JOIN note_entities ne ON em2.entity_id = ne.entity_id
            JOIN episodes ep2 ON em2.episode_id = ep2.id
            WHERE ep2.id != :note_id
            GROUP BY ep2.id, ep2.summary
            ORDER BY shared_entities DESC
            LIMIT :limit
        """),
        {"note_id": note_id, "limit": limit},
    )
    links = await _mapping_rows(result)
    logger.info("entity_links_discovered", note_id=str(note_id), links=len(links))
    return links


async def discover_links_by_embedding(
    session: AsyncSession,
    note_id: uuid.UUID,
    limit: int = 5,
) -> list[dict]:
    """Find related notes via embedding similarity (Phase 2)."""
    result = await session.execute(
        text("""
            SELECT n2.id, n2.title, n2.executive_summary,
                   1 - (n1.embedding <=> n2.embedding) AS similarity
            FROM notes n1
            JOIN notes n2 ON n1.id != n2.id
            WHERE n1.id = :note_id
              AND n1.embedding IS NOT NULL
              AND n2.embedding IS NOT NULL
            ORDER BY n1.embedding <=> n2.embedding
            LIMIT :limit
        """),
        {"note_id": note_id, "limit": limit},
    )
    links = await _mapping_rows(result)
    logger.info("embedding_links_discovered", note_id=str(note_id), links=len(links))
    return links
