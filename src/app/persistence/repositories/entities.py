"""Entity repository -- CRUD for the lightweight knowledge graph.

All functions require the caller to manage session.commit(). Use
``async with session.begin():`` for automatic transaction management.
"""

import uuid

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import Entity, EntityMention, EntityRelationship

logger = structlog.get_logger()


async def upsert_entity(
    session: AsyncSession,
    name: str,
    entity_type: str,
) -> uuid.UUID:
    """Create or update an entity. Returns the entity ID.

    Uses case-insensitive exact matching on name to avoid duplicates.
    """
    # Try exact match first
    stmt = (
        select(Entity.id, Entity.mention_count)
        .where(func.lower(Entity.name) == func.lower(name))
        .where(Entity.entity_type == entity_type)
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.first()

    if row:
        # Update existing entity
        entity_id = row.id
        await session.execute(
            update(Entity)
            .where(Entity.id == entity_id)
            .values(
                mention_count=Entity.mention_count + 1,
                last_seen=func.now(),
            )
        )
        logger.info("entity_updated", entity_id=str(entity_id), entity_type=entity_type)
        return entity_id

    # Create new entity
    entity = Entity(
        name=name,
        entity_type=entity_type,
        canonical_name=name,
        mention_count=1,
        first_seen=func.now(),
        last_seen=func.now(),
    )
    session.add(entity)
    await session.flush()
    logger.info(
        "entity_created",
        entity_id=str(entity.id),
        entity_type=entity_type,
    )
    return entity.id


async def add_relationship(
    session: AsyncSession,
    source_entity_id: uuid.UUID,
    target_entity_id: uuid.UUID,
    relationship_type: str,
) -> None:
    """Add a relationship between two entities.

    Silently skips if the exact relationship already exists.
    """
    # Check for existing relationship
    existing = await session.execute(
        select(EntityRelationship.id).where(
            EntityRelationship.source_entity_id == source_entity_id,
            EntityRelationship.target_entity_id == target_entity_id,
            EntityRelationship.relationship_type == relationship_type,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return

    rel = EntityRelationship(
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relationship_type=relationship_type,
        valid_from=func.now(),
    )
    session.add(rel)
    await session.flush()


async def add_mention(
    session: AsyncSession,
    entity_id: uuid.UUID,
    episode_id: uuid.UUID,
    context_snippet: str | None = None,
) -> None:
    """Link an entity mention to an episode.

    Silently skips if the mention already exists.
    """
    existing = await session.execute(
        select(EntityMention.id).where(
            EntityMention.entity_id == entity_id,
            EntityMention.episode_id == episode_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return

    mention = EntityMention(
        entity_id=entity_id,
        episode_id=episode_id,
        context_snippet=context_snippet,
        mentioned_at=func.now(),
    )
    session.add(mention)
    await session.flush()


async def find_related_entities(
    session: AsyncSession,
    entity_id: uuid.UUID,
    max_depth: int = 2,
    limit: int = 20,
) -> list[dict]:
    """Find entities related to a given entity using recursive CTE.

    Includes cycle detection via a ``visited`` path array to prevent
    infinite loops when the entity graph contains cycles.
    """
    result = await session.execute(
        text("""
            WITH RECURSIVE related AS (
                SELECT target_entity_id AS id,
                       relationship_type,
                       1 AS depth,
                       ARRAY[source_entity_id, target_entity_id] AS visited
                FROM entity_relationships
                WHERE source_entity_id = :entity_id
                  AND (valid_to IS NULL OR valid_to > NOW())
                UNION ALL
                SELECT er.target_entity_id,
                       er.relationship_type,
                       r.depth + 1,
                       r.visited || er.target_entity_id
                FROM entity_relationships er
                JOIN related r ON er.source_entity_id = r.id
                WHERE r.depth < :max_depth
                  AND (er.valid_to IS NULL OR er.valid_to > NOW())
                  AND er.target_entity_id != ALL(r.visited)
            )
            SELECT DISTINCT e.id, e.name, e.entity_type, r.relationship_type, r.depth
            FROM related r
            JOIN entities e ON e.id = r.id
            ORDER BY r.depth, e.mention_count DESC
            LIMIT :limit
        """),
        {"entity_id": entity_id, "max_depth": max_depth, "limit": limit},
    )
    return [dict(row) for row in result.mappings().all()]


async def search_entities(
    session: AsyncSession,
    query: str,
    entity_type: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search entities by name using trigram similarity.

    Uses the pg_trgm ``similarity()`` function which requires the
    pg_trgm extension. Returns dicts because the result includes the
    computed similarity column.
    """
    # The type_filter is a hardcoded SQL fragment, not user input.
    # All user-supplied values go through :param bindings.
    type_filter = "AND entity_type = :entity_type" if entity_type else ""
    sql = text(  # nosec B608
        f"""
        SELECT id, name, entity_type, mention_count,
               similarity(name, :query) AS sim
        FROM entities
        WHERE similarity(name, :query) > 0.3
        {type_filter}
        ORDER BY sim DESC, mention_count DESC
        LIMIT :limit
        """
    )
    result = await session.execute(
        sql,
        {"query": query, "entity_type": entity_type, "limit": limit},
    )
    return [dict(row) for row in result.mappings().all()]
