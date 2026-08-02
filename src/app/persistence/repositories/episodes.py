"""Episode repository -- CRUD + BM25 full-text search.

All functions require the caller to manage session.commit(). Use
``async with session.begin():`` for automatic transaction management.
"""

import uuid
from datetime import datetime

import structlog
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.async_utils import affected_rows
from src.app.core.exceptions import NotFoundError
from src.app.domain.constants import EpisodeType
from src.app.persistence.models import Episode

logger = structlog.get_logger()


async def create_episode(
    session: AsyncSession,
    content: str,
    episode_type: EpisodeType | str,
    source: str,
    summary: str | None = None,
    para_category: str | None = None,
    mood_score: float | None = None,
    energy_rating: float | None = None,
    tags: list[str] | None = None,
    people_mentioned: list[str] | None = None,
    metadata: dict | None = None,
) -> Episode:
    """Create a new episode."""
    episode = Episode(
        content=content,
        summary=summary,
        episode_type=episode_type,
        para_category=para_category,
        mood_score=mood_score,
        energy_rating=energy_rating,
        tags=tags,
        people_mentioned=people_mentioned,
        source=source,
        metadata_=metadata or {},
    )
    session.add(episode)
    await session.flush()
    logger.info(
        "episode_created",
        episode_id=str(episode.id),
        episode_type=episode_type,
        source=source,
    )
    return episode


async def get_episode_by_id(
    session: AsyncSession,
    episode_id: uuid.UUID,
) -> Episode | None:
    """Get a single episode by ID."""
    result = await session.execute(
        select(Episode).where(Episode.id == episode_id, Episode.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_episodes_by_date_range(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    limit: int = 50,
) -> list[Episode]:
    """Get episodes within a date range, newest first."""
    stmt = (
        select(Episode)
        .where(
            Episode.created_at >= start,
            Episode.created_at <= end,
            Episode.deleted_at.is_(None),
        )
        .order_by(Episode.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_episode(
    session: AsyncSession,
    episode_id: uuid.UUID,
    **kwargs: str | float | list[str] | dict | None,
) -> Episode:
    """Update episode fields. Only provided kwargs are updated.

    Raises ValueError if the episode is not found.
    """
    allowed = {
        "content",
        "summary",
        "episode_type",
        "para_category",
        "mood_score",
        "energy_rating",
        "tags",
        "people_mentioned",
        "source",
        "metadata",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}

    # Handle the metadata_ alias (column name differs from kwarg name)
    if "metadata" in updates:
        updates["metadata_"] = updates.pop("metadata")

    if not updates:
        episode = await get_episode_by_id(session, episode_id)
        if episode is None:
            msg = f"Episode not found: {episode_id}"
            raise NotFoundError(msg)
        return episode

    stmt = (
        update(Episode)
        .where(Episode.id == episode_id, Episode.deleted_at.is_(None))
        .values(**updates)
        .returning(Episode)
    )
    result = await session.execute(stmt)
    episode = result.scalar_one_or_none()
    if episode is None:
        msg = f"Episode not found: {episode_id}"
        raise NotFoundError(msg)

    logger.info(
        "episode_updated",
        episode_id=str(episode_id),
        fields=list(updates.keys()),
    )
    return episode


async def delete_episode(
    session: AsyncSession,
    episode_id: uuid.UUID,
) -> bool:
    """Delete an episode by ID. Returns True if deleted, False if not found."""
    stmt = delete(Episode).where(Episode.id == episode_id)
    result = await session.execute(stmt)
    deleted = affected_rows(result) > 0
    if deleted:
        logger.info("episode_deleted", episode_id=str(episode_id))
    return deleted


async def search_episodes_bm25(
    session: AsyncSession,
    query: str,
    limit: int = 20,
) -> list[dict]:
    """Full-text search using PostgreSQL tsvector + GIN index.

    Requires the search_vector generated column and GIN index on episodes.
    Returns dicts (not ORM instances) to avoid detached-object issues.
    """
    stmt = text("""
        SELECT id, content, summary, episode_type, para_category,
               mood_score, energy_rating, tags, people_mentioned,
               source, metadata, created_at,
               ts_rank(search_vector, plainto_tsquery('english', :query)) AS rank
        FROM episodes
        WHERE search_vector @@ plainto_tsquery('english', :query)
          AND deleted_at IS NULL
        ORDER BY rank DESC
        LIMIT :limit
    """)
    result = await session.execute(stmt, {"query": query, "limit": limit})
    rows = [dict(r) for r in result.mappings().all()]

    logger.info("bm25_search", query_length=len(query), results=len(rows))
    return rows


async def record_episode_access(
    session: AsyncSession,
    episode_ids: list[uuid.UUID],
) -> None:
    """Record that episodes were accessed (retrieved by search).

    Increments access_count and sets last_accessed_at, creating a
    "retrieval strengthens memory" feedback loop that boosts future
    retrieval scores.
    """
    if not episode_ids:
        return
    await session.execute(
        update(Episode)
        .where(Episode.id.in_(episode_ids), Episode.deleted_at.is_(None))
        .values(
            access_count=Episode.access_count + 1,
            last_accessed_at=func.now(),
        )
    )
    logger.info("episode_access_recorded", count=len(episode_ids))
