"""Memory routes — search, entities, relationships."""

from __future__ import annotations

import uuid
from contextlib import suppress

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import Principal, get_current_principal, get_db
from src.app.core.exceptions import NotFoundError
from src.app.persistence.models import Entity, EntityRelationship
from src.app.persistence.repositories.connectors import search_connector_documents
from src.app.persistence.repositories.entities import (
    find_related_entities as repo_find_related_entities,
)
from src.app.persistence.repositories.entities import search_entities
from src.app.persistence.repositories.episodes import search_episodes_bm25
from src.app.persistence.repositories.notes import search_notes
from src.app.persistence.repositories.saved_memories import (
    mark_saved_memories_used as repo_mark_saved_memories_used,
)
from src.app.persistence.repositories.saved_memories import search_saved_memories

logger = structlog.get_logger()
router = APIRouter()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class MemorySearchResult(BaseModel):
    title: str | None = None
    content: str
    relevance_score: float
    source_type: str
    source_label: str
    source_id: str
    source_url: str | None = None
    provenance_label: str | None = None


class MemoryAnswer(BaseModel):
    answer: str
    confidence: float
    sources: list[MemorySearchResult]
    follow_up_suggestions: list[str]


class SearchRequest(BaseModel):
    query: str
    sensitive_mode: bool = False
    suppressed_sources: list[str] = []


class EntityDTO(BaseModel):
    id: str
    name: str
    entity_type: str
    canonical_name: str | None
    mention_count: int
    first_seen: str | None
    last_seen: str | None
    metadata: dict
    created_at: str


class EntityRelationshipDTO(BaseModel):
    id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    valid_from: str | None
    valid_to: str | None


class RelatedEntityDTO(BaseModel):
    id: str
    name: str
    entity_type: str
    relationship_type: str
    depth: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity_to_dto(e: Entity) -> EntityDTO:
    return EntityDTO(
        id=str(e.id),
        name=e.name,
        entity_type=e.entity_type,
        canonical_name=e.canonical_name,
        mention_count=e.mention_count,
        first_seen=e.first_seen.isoformat() if e.first_seen else None,
        last_seen=e.last_seen.isoformat() if e.last_seen else None,
        metadata=e.metadata_ or {},
        created_at=e.created_at.isoformat() if e.created_at else "",
    )


def _relationship_to_dto(r: EntityRelationship) -> EntityRelationshipDTO:
    return EntityRelationshipDTO(
        id=str(r.id),
        source_entity_id=str(r.source_entity_id),
        target_entity_id=str(r.target_entity_id),
        relationship_type=r.relationship_type,
        valid_from=r.valid_from.isoformat() if r.valid_from else None,
        valid_to=r.valid_to.isoformat() if r.valid_to else None,
    )


def _rough_text_relevance(
    query: str,
    *,
    title: str = "",
    content: str = "",
    base: float,
) -> float:
    normalized_query = query.casefold().strip()
    if not normalized_query:
        return round(base, 4)
    title_lower = title.casefold()
    content_lower = content.casefold()
    score = base
    if normalized_query in title_lower:
        score += 0.18
    if normalized_query in content_lower:
        score += 0.12
    token_hits = sum(
        1
        for token in normalized_query.split()
        if len(token) > 2 and (token in title_lower or token in content_lower)
    )
    score += min(token_hits * 0.03, 0.12)
    return round(min(score, 0.99), 4)


def _source_suppressed(source_type: str, suppressed_sources: set[str]) -> bool:
    return source_type in suppressed_sources


def _principal_user_ref(principal: Principal) -> str:
    return principal.external_subject or principal.subject


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/search", response_model=MemoryAnswer)
async def search_memory(
    body: SearchRequest,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> MemoryAnswer:
    """Search durable memory sources and return a synthesised answer."""
    user_id = _principal_user_ref(principal)
    suppressed_sources = {value.strip() for value in body.suppressed_sources if value.strip()}
    if body.sensitive_mode:
        suppressed_sources |= {"saved_memory", "connector_document"}

    episode_rows = (
        []
        if _source_suppressed("episode", suppressed_sources)
        else await search_episodes_bm25(db, body.query, limit=6)
    )
    try:
        note_rows = (
            []
            if _source_suppressed("note", suppressed_sources)
            else await search_notes(db, body.query, limit=4)
        )
    except Exception:
        logger.warning("memory_note_search_unavailable", exc_info=True)
        note_rows = []
    try:
        memory_rows = (
            []
            if _source_suppressed("saved_memory", suppressed_sources)
            else await search_saved_memories(db, user_id=user_id, query=body.query, limit=4)
        )
    except Exception:
        logger.warning("memory_saved_memory_search_unavailable", exc_info=True)
        memory_rows = []
    try:
        connector_rows = (
            []
            if _source_suppressed("connector_document", suppressed_sources)
            else await search_connector_documents(
                db,
                user_id=user_id,
                query=body.query,
                limit=4,
            )
        )
    except Exception:
        logger.warning("memory_connector_search_unavailable", exc_info=True)
        connector_rows = []
    sources: list[MemorySearchResult] = []
    summaries: list[tuple[float, str]] = []

    for row in episode_rows:
        source_id = str(row["id"])
        summary = row.get("summary") or ""
        content = row.get("content", "")
        rank = float(row.get("rank", 0.0))

        sources.append(
            MemorySearchResult(
                title=summary[:120] or content[:120] or None,
                content=content[:500],
                relevance_score=round(rank, 4),
                source_type="episode",
                source_label="Recent chat",
                source_id=source_id,
                provenance_label="Conversation history",
            )
        )
        if summary:
            summaries.append((rank, summary))
        elif content:
            summaries.append((rank, content[:200]))

    for row in note_rows:
        title = str(row.get("title", "") or "")
        content = str(row.get("content", "") or "")
        relevance = _rough_text_relevance(body.query, title=title, content=content, base=0.58)
        sources.append(
            MemorySearchResult(
                title=title or None,
                content=content[:500],
                relevance_score=relevance,
                source_type="note",
                source_label="Note",
                source_id=str(row.get("id")),
                source_url=str(row.get("source_url")) if row.get("source_url") else None,
                provenance_label=str(row.get("kind") or row.get("note_type") or "note"),
            )
        )
        summaries.append((relevance, title or content[:180]))

    for row in memory_rows:
        relevance = _rough_text_relevance(
            body.query,
            title=row.title,
            content=row.content,
            base=0.72,
        )
        sources.append(
            MemorySearchResult(
                title=row.title,
                content=row.content[:500],
                relevance_score=relevance,
                source_type="saved_memory",
                source_label="Saved memory",
                source_id=str(row.id),
                provenance_label=row.scope,
            )
        )
        summaries.append((relevance, row.title))

    for row in connector_rows:
        relevance = _rough_text_relevance(
            body.query,
            title=row.title,
            content=row.content,
            base=0.62,
        )
        sources.append(
            MemorySearchResult(
                title=row.title,
                content=row.content[:500],
                relevance_score=relevance,
                source_type="connector_document",
                source_label="Synced connector data",
                source_id=str(row.id),
                source_url=row.source_url,
                provenance_label=row.source_type,
            )
        )
        summaries.append((relevance, row.title))

    sources.sort(key=lambda item: item.relevance_score, reverse=True)
    summaries.sort(key=lambda item: item[0], reverse=True)
    answer = (
        " ".join(summary for _score, summary in summaries[:4] if summary)
        if summaries
        else "No matching memories found."
    )
    confidence = min(1.0, len(sources) / 5.0) if sources else 0.0

    follow_ups: list[str] = []
    if sources:
        follow_ups = [
            f"Tell me more about {body.query}",
            "What are the key themes?",
            "Show related entries",
        ]

    saved_memory_ids: list[uuid.UUID] = []
    for source in sources:
        if source.source_type != "saved_memory" or not isinstance(source.source_id, str):
            continue
        with suppress(ValueError):
            saved_memory_ids.append(uuid.UUID(source.source_id))
    if saved_memory_ids:
        await repo_mark_saved_memories_used(
            db,
            user_id=user_id,
            memory_ids=saved_memory_ids,
        )
        await db.commit()

    logger.info(
        "memory_search",
        query_length=len(body.query),
        results=len(sources),
    )
    return MemoryAnswer(
        answer=answer,
        confidence=round(confidence, 2),
        sources=sources[:10],
        follow_up_suggestions=follow_ups,
    )


@router.get("/entities", response_model=list[EntityDTO])
async def list_entities(
    _principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
    entity_type: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[EntityDTO]:
    """List entities with optional type filter and search."""
    if search:
        # Use trigram search from the entities repo
        raw_results = await search_entities(db, query=search, entity_type=entity_type, limit=limit)
        # search_entities returns dicts with id, name, entity_type, mention_count, sim
        # We need to load full Entity objects for DTO conversion
        entity_ids = [row["id"] for row in raw_results]
        if not entity_ids:
            return []

        stmt = select(Entity).where(Entity.id.in_(entity_ids))
        result = await db.execute(stmt)
        entities = list(result.scalars().all())

        # Preserve search ranking order
        id_order = {eid: idx for idx, eid in enumerate(entity_ids)}
        entities.sort(key=lambda e: id_order.get(e.id, 999))

        return [_entity_to_dto(e) for e in entities]

    # No search — direct query with filters
    stmt = select(Entity)

    if entity_type is not None:
        stmt = stmt.where(Entity.entity_type == entity_type)

    stmt = (
        stmt.order_by(Entity.mention_count.desc(), Entity.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    entities = list(result.scalars().all())

    logger.info("entities_listed", count=len(entities), entity_type=entity_type)
    return [_entity_to_dto(e) for e in entities]


@router.get("/entities/relationships", response_model=list[EntityRelationshipDTO])
async def list_relationships(
    _principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[EntityRelationshipDTO]:
    """Return all entity relationships for the knowledge graph."""
    stmt = select(EntityRelationship).order_by(EntityRelationship.created_at.desc())
    result = await db.execute(stmt)
    relationships = list(result.scalars().all())

    logger.info("relationships_listed", count=len(relationships))
    return [_relationship_to_dto(r) for r in relationships]


@router.get("/entities/{entity_id}", response_model=EntityDTO)
async def get_entity(
    entity_id: uuid.UUID,
    _principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> EntityDTO:
    """Get a single entity by ID."""
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError(f"Entity not found: {entity_id}")
    return _entity_to_dto(entity)


@router.get("/entities/{entity_id}/related", response_model=list[RelatedEntityDTO])
async def find_related_entities(
    entity_id: uuid.UUID,
    _principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
    max_depth: int = Query(2, ge=1, le=5),
    limit: int = Query(20, ge=1, le=100),
) -> list[RelatedEntityDTO]:
    """Find entities related to the given entity via recursive CTE traversal."""
    rows = await repo_find_related_entities(
        db,
        entity_id=entity_id,
        max_depth=max_depth,
        limit=limit,
    )
    return [
        RelatedEntityDTO(
            id=str(row["id"]),
            name=row["name"],
            entity_type=row["entity_type"],
            relationship_type=row["relationship_type"],
            depth=row["depth"],
        )
        for row in rows
    ]
