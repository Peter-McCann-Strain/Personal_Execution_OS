"""Notes repository -- second-brain CRUD, links, graph queries, daily notes, and canvases."""

from __future__ import annotations

import inspect
import re
import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

import structlog
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import Note, NoteCanvas, NoteLink

logger = structlog.get_logger()

_WIKI_LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")


async def _session_add(session: AsyncSession, instance: object) -> None:
    result = session.add(instance)
    if inspect.isawaitable(result):
        await result


async def _maybe_await[T](value: T) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


async def _scalar_one_or_none(result: Any) -> Any:
    return await _maybe_await(result.scalar_one_or_none())


async def _scalar_one(result: Any) -> Any:
    return await _maybe_await(result.scalar_one())


async def _scalars_all(result: Any) -> list[Any]:
    scalars = await _maybe_await(result.scalars())
    rows = await _maybe_await(scalars.all())
    return list(rows)


def slugify_note_title(value: str) -> str:
    """Build an Obsidian-style slug from a note title."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "note"


def extract_wiki_links(content: str) -> list[str]:
    """Return ordered unique wiki-link targets from markdown note content."""
    seen: set[str] = set()
    targets: list[str] = []
    for match in _WIKI_LINK_RE.findall(content or ""):
        raw = match.split("|", 1)[0].strip()
        if not raw:
            continue
        key = raw.casefold()
        if key in seen:
            continue
        seen.add(key)
        targets.append(raw)
    return targets


async def _generate_unique_slug(
    session: AsyncSession,
    title: str,
    *,
    note_id: uuid.UUID | None = None,
) -> str:
    base = slugify_note_title(title)
    candidate = base
    suffix = 2
    while True:
        stmt = select(Note.id).where(Note.slug == candidate, Note.deleted_at.is_(None))
        if note_id is not None:
            stmt = stmt.where(Note.id != note_id)
        result = await session.execute(stmt.limit(1))
        existing_id = await _scalar_one_or_none(result)
        if existing_id is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


async def _find_note_by_reference(
    session: AsyncSession,
    *,
    reference: str,
    exclude_note_id: uuid.UUID | None = None,
) -> Note | None:
    slug = slugify_note_title(reference)
    stmt = select(Note).where(
        Note.deleted_at.is_(None),
        or_(
            func.lower(Note.title) == reference.casefold(),
            Note.slug == slug,
            Note.aliases.any(reference),
        ),
    )
    if exclude_note_id is not None:
        stmt = stmt.where(Note.id != exclude_note_id)
    result = await session.execute(stmt.order_by(Note.updated_at.desc()).limit(1))
    return await _scalar_one_or_none(result)


def _tokenize_similarity_text(*values: str) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        tokens.update(
            token
            for token in re.findall(r"[a-z0-9]{3,}", value.casefold())
            if token not in {"note", "notes", "this", "that"}
        )
    return tokens


async def _semantic_link_candidates(
    session: AsyncSession,
    *,
    note: Note,
) -> list[tuple[Note, float, str]]:
    note_tags = set(note.tags or [])
    note_tokens = _tokenize_similarity_text(note.title, note.content[:400])

    stmt = select(Note).where(Note.deleted_at.is_(None), Note.id != note.id)
    filters = []
    if note.para_category is not None:
        filters.append(Note.para_category == note.para_category)
    if note_tags:
        filters.append(Note.tags.overlap(list(note_tags)))
    if filters:
        stmt = stmt.where(or_(*filters))
    result = await session.execute(stmt.order_by(Note.updated_at.desc()).limit(50))
    candidates: list[tuple[Note, float, str]] = []
    for other in await _scalars_all(result):
        overlap_tags = note_tags & set(other.tags or [])
        overlap_tokens = note_tokens & _tokenize_similarity_text(other.title, other.content[:220])
        score = float((len(overlap_tags) * 2) + len(overlap_tokens))
        if score < 2:
            continue
        reason_bits: list[str] = []
        if overlap_tags:
            reason_bits.append(f"shared tags: {', '.join(sorted(overlap_tags))}")
        if overlap_tokens:
            reason_bits.append(f"shared concepts: {', '.join(sorted(list(overlap_tokens))[:4])}")
        candidates.append((other, score, "; ".join(reason_bits)))
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates[:5]


async def sync_note_links(
    session: AsyncSession,
    *,
    note: Note,
) -> None:
    """Rebuild wiki and semantic outgoing links for a note."""
    await session.execute(
        delete(NoteLink).where(
            NoteLink.source_note_id == note.id,
            NoteLink.origin.in_(["wiki", "semantic"]),
        )
    )

    wiki_target_ids: set[uuid.UUID] = set()
    for reference in extract_wiki_links(note.content):
        target = await _find_note_by_reference(
            session,
            reference=reference,
            exclude_note_id=note.id,
        )
        if target is None:
            continue
        wiki_target_ids.add(target.id)
        await create_note_link(
            session,
            source_note_id=note.id,
            target_note_id=target.id,
            link_reason=f"Wiki link to [[{reference}]]",
            similarity_score=1.0,
            auto_discovered=False,
            link_type="wiki",
            origin="wiki",
        )

    for target, score, reason in await _semantic_link_candidates(session, note=note):
        if target.id in wiki_target_ids:
            continue
        await create_note_link(
            session,
            source_note_id=note.id,
            target_note_id=target.id,
            link_reason=reason,
            similarity_score=score,
            auto_discovered=True,
            link_type="semantic",
            origin="semantic",
        )


async def create_note(
    session: AsyncSession,
    title: str,
    content: str,
    note_type: str = "fleeting",
    para_category: str | None = None,
    tags: list[str] | None = None,
    source_url: str | None = None,
    *,
    slug: str | None = None,
    aliases: list[str] | None = None,
    kind: str | None = None,
    daily_date: date | None = None,
    frontmatter: dict[str, Any] | None = None,
) -> Note:
    """Create a new note and derive wiki/semantic links."""
    resolved_slug = slug or await _generate_unique_slug(session, title)
    note = Note(
        title=title,
        slug=resolved_slug,
        aliases=aliases,
        kind=kind or "note",
        daily_date=daily_date,
        frontmatter=frontmatter or {},
        content=content,
        note_type=note_type,
        para_category=para_category,
        tags=tags,
        source_url=source_url,
        progressive_summary_level=1,
    )
    await _session_add(session, note)
    await session.flush()
    await sync_note_links(session, note=note)
    logger.info("note_created", note_id=str(note.id))
    return note


async def create_note_link(
    session: AsyncSession,
    source_note_id: uuid.UUID,
    target_note_id: uuid.UUID,
    link_reason: str | None = None,
    similarity_score: float | None = None,
    auto_discovered: bool = True,
    *,
    link_type: str = "manual",
    origin: str = "manual",
) -> NoteLink:
    """Create a directed link between notes, skipping exact duplicates."""
    existing = await session.execute(
        select(NoteLink.id).where(
            NoteLink.source_note_id == source_note_id,
            NoteLink.target_note_id == target_note_id,
        )
    )
    existing_id = await _scalar_one_or_none(existing)
    if existing_id is not None:
        link = await session.get(NoteLink, existing_id)
        assert link is not None
        return link

    link = NoteLink(
        source_note_id=source_note_id,
        target_note_id=target_note_id,
        link_reason=link_reason,
        similarity_score=similarity_score,
        auto_discovered=auto_discovered,
        link_type=link_type,
        origin=origin,
    )
    await _session_add(session, link)
    await session.flush()
    return link


async def get_note_by_id(
    session: AsyncSession,
    note_id: uuid.UUID,
) -> Note | None:
    """Get a single non-deleted note by ID."""
    result = await session.execute(
        select(Note).where(Note.id == note_id, Note.deleted_at.is_(None))
    )
    return await _scalar_one_or_none(result)


async def update_note(
    session: AsyncSession,
    note_id: uuid.UUID,
    **kwargs: object,
) -> Note:
    """Update note fields and resync links when content/title changes."""
    allowed = {
        "title",
        "slug",
        "aliases",
        "kind",
        "daily_date",
        "frontmatter",
        "content",
        "note_type",
        "para_category",
        "progressive_summary_level",
        "executive_summary",
        "source_url",
        "tags",
    }
    updates = {key: value for key, value in kwargs.items() if key in allowed}
    note = await get_note_by_id(session, note_id)
    if note is None:
        msg = f"Note not found: {note_id}"
        raise ValueError(msg)

    if "title" in updates and "slug" not in updates:
        updates["slug"] = await _generate_unique_slug(
            session,
            str(updates["title"]),
            note_id=note_id,
        )

    for key, value in updates.items():
        setattr(note, key, value)
    note.updated_at = func.now()
    await session.flush()

    if {"title", "content", "tags", "para_category", "aliases", "slug"} & updates.keys():
        await sync_note_links(session, note=note)

    logger.info("note_updated", note_id=str(note_id), fields=sorted(updates.keys()))
    return note


async def delete_note(
    session: AsyncSession,
    note_id: uuid.UUID,
) -> bool:
    """Delete a note by ID. Returns True if deleted."""
    stmt = delete(Note).where(Note.id == note_id)
    result = await session.execute(stmt)
    deleted = result.rowcount > 0
    if deleted:
        logger.info("note_deleted", note_id=str(note_id))
    return deleted


async def list_notes(
    session: AsyncSession,
    *,
    limit: int = 25,
    offset: int = 0,
    search: str | None = None,
    note_type: str | None = None,
    para_category: str | None = None,
    kind: str | None = None,
) -> tuple[list[Note], int]:
    """List notes with optional filters and free-text search."""
    stmt = select(Note).where(Note.deleted_at.is_(None))
    if note_type is not None:
        stmt = stmt.where(Note.note_type == note_type)
    if para_category is not None:
        stmt = stmt.where(Note.para_category == para_category)
    if kind is not None:
        stmt = stmt.where(Note.kind == kind)
    if search and search != "*":
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(or_(Note.title.ilike(pattern), Note.content.ilike(pattern)))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await session.execute(count_stmt)
    total_value = await _scalar_one(count_result)
    total = int(total_value)
    result = await session.execute(
        stmt.order_by(Note.updated_at.desc(), Note.created_at.desc()).offset(offset).limit(limit)
    )
    return await _scalars_all(result), total


async def get_linked_notes(
    session: AsyncSession,
    note_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Get notes linked from or to the given note."""
    result = await session.execute(
        select(NoteLink, Note)
        .join(
            Note,
            or_(
                (NoteLink.target_note_id == Note.id) & (NoteLink.source_note_id == note_id),
                (NoteLink.source_note_id == Note.id) & (NoteLink.target_note_id == note_id),
            ),
        )
        .where(
            or_(NoteLink.source_note_id == note_id, NoteLink.target_note_id == note_id),
            Note.deleted_at.is_(None),
        )
        .order_by(NoteLink.similarity_score.desc().nullslast(), Note.updated_at.desc())
    )
    rows: list[dict[str, Any]] = []
    for link, note in result.all():
        rows.append(
            {
                "id": note.id,
                "title": note.title,
                "slug": note.slug,
                "content": note.content,
                "kind": note.kind,
                "note_type": note.note_type,
                "para_category": note.para_category,
                "tags": note.tags,
                "created_at": note.created_at,
                "updated_at": note.updated_at,
                "link_reason": link.link_reason,
                "similarity_score": link.similarity_score,
                "link_type": link.link_type,
                "origin": link.origin,
            }
        )
    return rows


async def get_backlinked_notes(
    session: AsyncSession,
    note_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Get notes that explicitly link to the target note."""
    result = await session.execute(
        select(NoteLink, Note)
        .join(Note, NoteLink.source_note_id == Note.id)
        .where(NoteLink.target_note_id == note_id, Note.deleted_at.is_(None))
        .order_by(Note.updated_at.desc())
    )
    rows: list[dict[str, Any]] = []
    for link, note in result.all():
        rows.append(
            {
                "id": note.id,
                "title": note.title,
                "slug": note.slug,
                "content": note.content,
                "kind": note.kind,
                "note_type": note.note_type,
                "para_category": note.para_category,
                "tags": note.tags,
                "created_at": note.created_at,
                "updated_at": note.updated_at,
                "link_reason": link.link_reason,
                "similarity_score": link.similarity_score,
                "link_type": link.link_type,
                "origin": link.origin,
            }
        )
    return rows


async def get_unlinked_mentions(
    session: AsyncSession,
    note_id: uuid.UUID,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return notes that mention the current note without an explicit link."""
    note = await get_note_by_id(session, note_id)
    if note is None:
        return []

    reference_terms = [note.title.strip(), *(note.aliases or [])]
    normalized_terms: list[str] = []
    seen_terms: set[str] = set()
    for term in reference_terms:
        clean = term.strip()
        if len(clean) < 3:
            continue
        key = clean.casefold()
        if key in seen_terms:
            continue
        seen_terms.add(key)
        normalized_terms.append(clean)

    if not normalized_terms:
        return []

    linked_source_ids_result = await session.execute(
        select(NoteLink.source_note_id).where(NoteLink.target_note_id == note_id)
    )
    linked_source_ids = {
        value for value in linked_source_ids_result.scalars().all() if isinstance(value, uuid.UUID)
    }

    conditions = []
    for term in normalized_terms:
        pattern = f"%{term}%"
        conditions.append(Note.title.ilike(pattern))
        conditions.append(Note.content.ilike(pattern))

    result = await session.execute(
        select(Note)
        .where(
            Note.deleted_at.is_(None),
            Note.id != note_id,
            or_(*conditions),
        )
        .order_by(Note.updated_at.desc(), Note.created_at.desc())
        .limit(limit * 3)
    )

    rows: list[dict[str, Any]] = []
    for candidate in result.scalars().all():
        if candidate.id in linked_source_ids:
            continue
        matched_terms = [
            term
            for term in normalized_terms
            if term.casefold() in candidate.title.casefold()
            or term.casefold() in candidate.content.casefold()
        ]
        if not matched_terms:
            continue
        rows.append(
            {
                "id": candidate.id,
                "title": candidate.title,
                "slug": candidate.slug,
                "content": candidate.content,
                "kind": candidate.kind,
                "note_type": candidate.note_type,
                "para_category": candidate.para_category,
                "tags": candidate.tags,
                "created_at": candidate.created_at,
                "updated_at": candidate.updated_at,
                "link_reason": f"Mentions {', '.join(matched_terms[:3])}",
                "similarity_score": None,
                "link_type": None,
                "origin": "unlinked_mention",
            }
        )
        if len(rows) >= limit:
            break
    return rows


async def search_notes(
    session: AsyncSession,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search notes by content/title; '*' falls back to recent notes."""
    notes, _total = await list_notes(
        session,
        limit=limit,
        offset=0,
        search=query,
    )
    return [
        {
            "id": note.id,
            "title": note.title,
            "slug": note.slug,
            "content": note.content,
            "kind": note.kind,
            "note_type": note.note_type,
            "para_category": note.para_category,
            "tags": note.tags,
            "created_at": note.created_at,
            "updated_at": note.updated_at,
        }
        for note in notes
    ]


async def get_note_graph(
    session: AsyncSession,
    *,
    note_id: uuid.UUID | None = None,
    depth: int = 1,
    limit: int = 60,
    kind: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return a neighborhood-first graph payload for notes and links."""
    edge_ids: set[uuid.UUID] = set()
    selected_ids: set[uuid.UUID] = set()

    if note_id is None:
        notes_stmt = select(Note).where(Note.deleted_at.is_(None))
        if kind is not None:
            notes_stmt = notes_stmt.where(Note.kind == kind)
        recent_result = await session.execute(
            notes_stmt.order_by(Note.updated_at.desc(), Note.created_at.desc()).limit(limit)
        )
        recent_notes = list(recent_result.scalars().all())
        selected_ids = {note.id for note in recent_notes}
    else:
        frontier = {note_id}
        selected_ids = {note_id}
        for _ in range(max(1, min(depth, 2))):
            result = await session.execute(
                select(NoteLink).where(
                    or_(
                        NoteLink.source_note_id.in_(frontier),
                        NoteLink.target_note_id.in_(frontier),
                    )
                )
            )
            next_frontier: set[uuid.UUID] = set()
            for link in result.scalars().all():
                edge_ids.add(link.id)
                next_frontier.add(link.source_note_id)
                next_frontier.add(link.target_note_id)
            next_frontier -= selected_ids
            selected_ids |= next_frontier
            frontier = next_frontier
            if not frontier:
                break

    if not selected_ids:
        return {"nodes": [], "edges": []}

    notes_result = await session.execute(
        select(Note).where(Note.id.in_(selected_ids), Note.deleted_at.is_(None))
    )
    notes = list(notes_result.scalars().all())
    filtered_ids = {note.id for note in notes}

    links_result = await session.execute(
        select(NoteLink).where(
            NoteLink.source_note_id.in_(filtered_ids),
            NoteLink.target_note_id.in_(filtered_ids),
        )
    )
    edges = [
        {
            "id": str(link.id),
            "source": str(link.source_note_id),
            "target": str(link.target_note_id),
            "link_type": link.link_type,
            "origin": link.origin,
            "similarity_score": link.similarity_score,
            "link_reason": link.link_reason,
        }
        for link in links_result.scalars().all()
    ]
    nodes = [
        {
            "id": str(note.id),
            "title": note.title,
            "slug": note.slug,
            "kind": note.kind,
            "note_type": note.note_type,
            "para_category": note.para_category,
            "tags": note.tags or [],
            "created_at": note.created_at.isoformat(),
            "updated_at": note.updated_at.isoformat(),
        }
        for note in notes
    ]
    return {"nodes": nodes, "edges": edges}


async def get_daily_note(
    session: AsyncSession,
    *,
    note_date: date,
) -> Note | None:
    """Fetch the daily note for one date."""
    result = await session.execute(
        select(Note).where(
            Note.kind == "daily",
            Note.daily_date == note_date,
            Note.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def upsert_daily_note(
    session: AsyncSession,
    *,
    note_date: date,
    title: str,
    content: str,
    tags: list[str] | None = None,
    frontmatter: dict[str, Any] | None = None,
) -> Note:
    """Create or update a daily note for a specific calendar date."""
    existing = await get_daily_note(session, note_date=note_date)
    if existing is None:
        return await create_note(
            session,
            title=title,
            content=content,
            note_type="fleeting",
            para_category="area",
            tags=tags,
            slug=slugify_note_title(title),
            kind="daily",
            daily_date=note_date,
            frontmatter=frontmatter,
        )
    return await update_note(
        session,
        existing.id,
        title=title,
        content=content,
        tags=tags,
        frontmatter=frontmatter or {},
        kind="daily",
        daily_date=note_date,
    )


async def create_note_canvas(
    session: AsyncSession,
    *,
    title: str,
    description: str | None = None,
    primary_note_id: uuid.UUID | None = None,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    viewport: dict[str, Any] | None = None,
) -> NoteCanvas:
    """Create a note-centric canvas board."""
    canvas = NoteCanvas(
        title=title,
        description=description,
        primary_note_id=primary_note_id,
        nodes=nodes or [],
        edges=edges or [],
        viewport=viewport or {"x": 0, "y": 0, "zoom": 1},
    )
    await _session_add(session, canvas)
    await session.flush()
    logger.info("note_canvas_created", canvas_id=str(canvas.id))
    return canvas


async def list_note_canvases(
    session: AsyncSession,
    *,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[NoteCanvas], int]:
    """List note canvases."""
    stmt = select(NoteCanvas).where(NoteCanvas.deleted_at.is_(None))
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    result = await session.execute(
        stmt.order_by(NoteCanvas.updated_at.desc(), NoteCanvas.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def get_note_canvas(
    session: AsyncSession,
    canvas_id: uuid.UUID,
) -> NoteCanvas | None:
    """Get one canvas by id."""
    result = await session.execute(
        select(NoteCanvas).where(NoteCanvas.id == canvas_id, NoteCanvas.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_note_canvas(
    session: AsyncSession,
    canvas_id: uuid.UUID,
    *,
    title: str | None = None,
    description: str | None = None,
    primary_note_id: uuid.UUID | None = None,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    viewport: dict[str, Any] | None = None,
) -> NoteCanvas:
    """Update canvas content and layout."""
    canvas = await get_note_canvas(session, canvas_id)
    if canvas is None:
        msg = f"Note canvas not found: {canvas_id}"
        raise ValueError(msg)

    if title is not None:
        canvas.title = title
    if description is not None:
        canvas.description = description
    if primary_note_id is not None:
        canvas.primary_note_id = primary_note_id
    if nodes is not None:
        canvas.nodes = nodes
    if edges is not None:
        canvas.edges = edges
    if viewport is not None:
        canvas.viewport = viewport
    await session.flush()
    logger.info("note_canvas_updated", canvas_id=str(canvas_id))
    return canvas


async def record_note_access(
    session: AsyncSession,
    note_ids: Sequence[uuid.UUID],
) -> None:
    """Record that notes were accessed."""
    if not note_ids:
        return
    await session.execute(
        update(Note)
        .where(Note.id.in_(list(note_ids)))
        .values(
            access_count=Note.access_count + 1,
            last_accessed_at=func.now(),
        )
    )
    logger.info("note_access_recorded", count=len(note_ids))
