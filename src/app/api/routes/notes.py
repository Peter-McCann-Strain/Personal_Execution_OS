"""Notes API routes -- second-brain CRUD, graph, backlinks, daily notes, and canvases."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.api.transactions import session_transaction
from src.app.config import get_settings
from src.app.core.exceptions import NotFoundError
from src.app.persistence.repositories.notes import (
    create_note as repo_create_note,
)
from src.app.persistence.repositories.notes import (
    create_note_canvas as repo_create_note_canvas,
)
from src.app.persistence.repositories.notes import (
    create_note_link as repo_create_note_link,
)
from src.app.persistence.repositories.notes import (
    get_backlinked_notes as repo_get_backlinked_notes,
)
from src.app.persistence.repositories.notes import (
    get_daily_note as repo_get_daily_note,
)
from src.app.persistence.repositories.notes import (
    get_linked_notes as repo_get_linked_notes,
)
from src.app.persistence.repositories.notes import (
    get_note_by_id as repo_get_note_by_id,
)
from src.app.persistence.repositories.notes import (
    get_note_canvas as repo_get_note_canvas,
)
from src.app.persistence.repositories.notes import (
    get_note_graph as repo_get_note_graph,
)
from src.app.persistence.repositories.notes import (
    get_unlinked_mentions as repo_get_unlinked_mentions,
)
from src.app.persistence.repositories.notes import (
    list_note_canvases as repo_list_note_canvases,
)
from src.app.persistence.repositories.notes import list_notes as repo_list_notes
from src.app.persistence.repositories.notes import search_notes as repo_search_notes
from src.app.persistence.repositories.notes import (
    update_note as repo_update_note,
)
from src.app.persistence.repositories.notes import (
    update_note_canvas as repo_update_note_canvas,
)
from src.app.persistence.repositories.notes import (
    upsert_daily_note as repo_upsert_daily_note,
)

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])


def _require_notes_workspace_enabled() -> None:
    if not bool(getattr(get_settings(), "notes_workspace_enabled", True)):
        raise NotFoundError("Notes workspace is not enabled.")


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _list_of_strings(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _iso_date_value(value: object) -> str | None:
    if hasattr(value, "isoformat"):
        try:
            iso_value = value.isoformat()
        except TypeError:
            return None
        return iso_value if isinstance(iso_value, str) else None
    return None


class NoteDTO(BaseModel):
    id: str
    title: str
    slug: str | None
    aliases: list[str]
    kind: str | None
    daily_date: str | None
    frontmatter: dict[str, Any]
    content: str
    note_type: str | None
    para_category: str | None
    tags: list[str]
    source_url: str | None
    progressive_summary_level: int | None
    executive_summary: str | None
    created_at: str
    updated_at: str


class NoteSearchResultDTO(BaseModel):
    id: str
    title: str
    slug: str | None
    kind: str | None
    content: str
    note_type: str | None
    para_category: str | None
    tags: list[str]
    created_at: str
    updated_at: str


class LinkedNoteDTO(BaseModel):
    id: str
    title: str
    slug: str | None
    kind: str | None
    content: str
    note_type: str | None
    para_category: str | None
    tags: list[str]
    created_at: str
    updated_at: str
    link_reason: str | None
    similarity_score: float | None
    link_type: str | None
    origin: str | None


class NoteGraphNodeDTO(BaseModel):
    id: str
    title: str
    slug: str | None
    kind: str | None
    note_type: str | None
    para_category: str | None
    tags: list[str]
    created_at: str
    updated_at: str


class NoteGraphEdgeDTO(BaseModel):
    id: str
    source: str
    target: str
    link_type: str
    origin: str
    similarity_score: float | None
    link_reason: str | None


class NoteGraphDTO(BaseModel):
    nodes: list[NoteGraphNodeDTO]
    edges: list[NoteGraphEdgeDTO]


class NoteCanvasDTO(BaseModel):
    id: str
    title: str
    description: str | None
    primary_note_id: str | None
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    viewport: dict[str, Any]
    created_at: str
    updated_at: str


class CreateNoteBody(BaseModel):
    title: str
    content: str
    note_type: str = "fleeting"
    para_category: str | None = None
    tags: list[str] | None = None
    source_url: str | None = None
    slug: str | None = None
    aliases: list[str] | None = None
    kind: str | None = None
    daily_date: date | None = None
    frontmatter: dict[str, Any] | None = None


class UpdateNoteBody(BaseModel):
    title: str | None = None
    content: str | None = None
    note_type: str | None = None
    para_category: str | None = None
    tags: list[str] | None = None
    source_url: str | None = None
    slug: str | None = None
    aliases: list[str] | None = None
    kind: str | None = None
    daily_date: date | None = None
    frontmatter: dict[str, Any] | None = None


class CreateNoteLinkBody(BaseModel):
    target_note_id: uuid.UUID
    link_reason: str | None = None
    similarity_score: float | None = None
    auto_discovered: bool = True
    link_type: str = "manual"
    origin: str = "manual"


class UpsertDailyNoteBody(BaseModel):
    title: str | None = None
    content: str = ""
    tags: list[str] | None = None
    frontmatter: dict[str, Any] | None = None


class CreateNoteCanvasBody(BaseModel):
    title: str
    description: str | None = None
    primary_note_id: uuid.UUID | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    viewport: dict[str, Any] = Field(default_factory=lambda: {"x": 0, "y": 0, "zoom": 1})


class UpdateNoteCanvasBody(BaseModel):
    title: str | None = None
    description: str | None = None
    primary_note_id: uuid.UUID | None = None
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None
    viewport: dict[str, Any] | None = None


def _parse_note_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _note_to_dto(note) -> NoteDTO:
    return NoteDTO(
        id=str(note.id),
        title=note.title,
        slug=_optional_str(getattr(note, "slug", None)),
        aliases=_list_of_strings(getattr(note, "aliases", None)),
        kind=_optional_str(getattr(note, "kind", None)),
        daily_date=_iso_date_value(getattr(note, "daily_date", None)),
        frontmatter=_dict_value(getattr(note, "frontmatter", None)),
        content=note.content,
        note_type=note.note_type,
        para_category=note.para_category,
        tags=_list_of_strings(getattr(note, "tags", None)),
        source_url=note.source_url,
        progressive_summary_level=note.progressive_summary_level,
        executive_summary=note.executive_summary,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat(),
    )


def _canvas_to_dto(canvas) -> NoteCanvasDTO:
    return NoteCanvasDTO(
        id=str(canvas.id),
        title=canvas.title,
        description=canvas.description,
        primary_note_id=str(canvas.primary_note_id) if canvas.primary_note_id else None,
        nodes=canvas.nodes or [],
        edges=canvas.edges or [],
        viewport=canvas.viewport or {"x": 0, "y": 0, "zoom": 1},
        created_at=canvas.created_at.isoformat(),
        updated_at=canvas.updated_at.isoformat(),
    )


@router.get("/notes", response_model=PaginatedResponse[NoteDTO])
async def list_notes(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    note_type: str | None = Query(None),
    para_category: str | None = Query(None),
    kind: str | None = Query(None),
) -> PaginatedResponse[NoteDTO]:
    """Paginated listing for notes workspace tabs."""
    notes, total = await repo_list_notes(
        session,
        limit=limit,
        offset=offset,
        search=search,
        note_type=note_type,
        para_category=para_category,
        kind=kind,
    )
    return paginate(
        items=[_note_to_dto(note) for note in notes],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/notes/search", response_model=list[NoteSearchResultDTO])
async def search_notes(
    session: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=1, description="Full-text search query"),
    limit: int = Query(10, ge=1, le=50),
) -> list[NoteSearchResultDTO]:
    """Compatibility search route backed by the new listing/search logic."""
    rows = await repo_search_notes(session, query=q, limit=limit)
    return [
        NoteSearchResultDTO(
            id=str(row["id"]),
            title=row["title"],
            slug=row.get("slug"),
            kind=row.get("kind"),
            content=row["content"],
            note_type=row.get("note_type"),
            para_category=row.get("para_category"),
            tags=row.get("tags") or [],
            created_at=str(row["created_at"]),
            updated_at=str(row.get("updated_at") or row["created_at"]),
        )
        for row in rows
    ]


@router.get("/notes/graph", response_model=NoteGraphDTO)
async def get_note_graph(
    session: AsyncSession = Depends(get_db),
    note_id: uuid.UUID | None = Query(None),
    depth: int = Query(1, ge=1, le=2),
    limit: int = Query(60, ge=1, le=200),
    kind: str | None = Query(None),
) -> NoteGraphDTO:
    """Return a neighborhood-first note graph."""
    _require_notes_workspace_enabled()
    payload = await repo_get_note_graph(
        session,
        note_id=note_id,
        depth=depth,
        limit=limit,
        kind=kind,
    )
    return NoteGraphDTO(
        nodes=[NoteGraphNodeDTO(**node) for node in payload["nodes"]],
        edges=[NoteGraphEdgeDTO(**edge) for edge in payload["edges"]],
    )


@router.get("/notes/daily/{note_date}", response_model=NoteDTO)
async def get_daily_note(
    note_date: date,
    session: AsyncSession = Depends(get_db),
) -> NoteDTO:
    """Get the daily note for a specific date."""
    _require_notes_workspace_enabled()
    note = await repo_get_daily_note(session, note_date=note_date)
    if note is None:
        raise NotFoundError(f"Daily note not found: {note_date}")
    return _note_to_dto(note)


@router.post("/notes/daily/{note_date}", response_model=NoteDTO, status_code=201)
async def upsert_daily_note(
    note_date: date,
    body: UpsertDailyNoteBody,
    session: AsyncSession = Depends(get_db),
) -> NoteDTO:
    """Create or update a daily note."""
    _require_notes_workspace_enabled()
    resolved_title = body.title or f"Daily Note {note_date.isoformat()}"
    async with session_transaction(session):
        note = await repo_upsert_daily_note(
            session,
            note_date=note_date,
            title=resolved_title,
            content=body.content,
            tags=body.tags,
            frontmatter=body.frontmatter,
        )
    await session.refresh(note)
    return _note_to_dto(note)


@router.post("/notes", response_model=NoteDTO, status_code=201)
async def create_note(
    body: CreateNoteBody,
    session: AsyncSession = Depends(get_db),
) -> NoteDTO:
    """Create a new note."""
    async with session_transaction(session):
        note = await repo_create_note(
            session,
            title=body.title,
            content=body.content,
            note_type=body.note_type,
            para_category=body.para_category,
            tags=body.tags,
            source_url=body.source_url,
            slug=body.slug,
            aliases=body.aliases,
            kind=body.kind,
            daily_date=_parse_note_date(body.daily_date),
            frontmatter=body.frontmatter,
        )
    await session.refresh(note)
    logger.info("note_created_via_api", note_id=str(note.id))
    return _note_to_dto(note)


@router.get("/notes/{note_id}", response_model=NoteDTO)
async def get_note(
    note_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> NoteDTO:
    """Get a single note by ID."""
    note = await repo_get_note_by_id(session, note_id)
    if note is None:
        raise NotFoundError(f"Note not found: {note_id}")
    return _note_to_dto(note)


@router.patch("/notes/{note_id}", response_model=NoteDTO)
async def update_note(
    note_id: uuid.UUID,
    body: UpdateNoteBody,
    session: AsyncSession = Depends(get_db),
) -> NoteDTO:
    """Update note fields and resync derived links."""
    kwargs = {key: value for key, value in body.model_dump().items() if value is not None}
    if "daily_date" in kwargs:
        kwargs["daily_date"] = _parse_note_date(kwargs["daily_date"])
    async with session_transaction(session):
        try:
            note = await repo_update_note(session, note_id, **kwargs)
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc
    await session.refresh(note)
    logger.info("note_updated_via_api", note_id=str(note_id))
    return _note_to_dto(note)


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(
    note_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a note by ID."""
    async with session_transaction(session):
        note = await repo_get_note_by_id(session, note_id)
        if note is None:
            raise NotFoundError(f"Note not found: {note_id}")
        note.soft_delete()
    logger.info("note_soft_deleted_via_api", note_id=str(note_id))


@router.get("/notes/{note_id}/links", response_model=list[LinkedNoteDTO])
async def get_linked_notes(
    note_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> list[LinkedNoteDTO]:
    """Get notes linked to the given note in either direction."""
    note = await repo_get_note_by_id(session, note_id)
    if note is None:
        raise NotFoundError(f"Note not found: {note_id}")

    rows = await repo_get_linked_notes(session, note_id)
    return [
        LinkedNoteDTO(
            id=str(row["id"]),
            title=row["title"],
            slug=row.get("slug"),
            kind=row.get("kind"),
            content=row["content"],
            note_type=row.get("note_type"),
            para_category=row.get("para_category"),
            tags=row.get("tags") or [],
            created_at=str(row["created_at"]),
            updated_at=str(row.get("updated_at") or row["created_at"]),
            link_reason=row.get("link_reason"),
            similarity_score=row.get("similarity_score"),
            link_type=row.get("link_type"),
            origin=row.get("origin"),
        )
        for row in rows
    ]


@router.get("/notes/{note_id}/backlinks", response_model=list[LinkedNoteDTO])
async def get_backlinked_notes(
    note_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> list[LinkedNoteDTO]:
    """Get notes linking into the target note."""
    note = await repo_get_note_by_id(session, note_id)
    if note is None:
        raise NotFoundError(f"Note not found: {note_id}")

    rows = await repo_get_backlinked_notes(session, note_id)
    return [
        LinkedNoteDTO(
            id=str(row["id"]),
            title=row["title"],
            slug=row.get("slug"),
            kind=row.get("kind"),
            content=row["content"],
            note_type=row.get("note_type"),
            para_category=row.get("para_category"),
            tags=row.get("tags") or [],
            created_at=str(row["created_at"]),
            updated_at=str(row.get("updated_at") or row["created_at"]),
            link_reason=row.get("link_reason"),
            similarity_score=row.get("similarity_score"),
            link_type=row.get("link_type"),
            origin=row.get("origin"),
        )
        for row in rows
    ]


@router.get("/notes/{note_id}/unlinked-mentions", response_model=list[LinkedNoteDTO])
async def get_unlinked_mentions(
    note_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    limit: int = Query(10, ge=1, le=50),
) -> list[LinkedNoteDTO]:
    """Return notes that mention this note without an explicit note link."""
    note = await repo_get_note_by_id(session, note_id)
    if note is None:
        raise NotFoundError(f"Note not found: {note_id}")
    rows = await repo_get_unlinked_mentions(session, note_id, limit=limit)
    return [
        LinkedNoteDTO(
            id=str(row["id"]),
            title=row["title"],
            slug=row.get("slug"),
            kind=row.get("kind"),
            content=row["content"],
            note_type=row.get("note_type"),
            para_category=row.get("para_category"),
            tags=row.get("tags") or [],
            created_at=str(row["created_at"]),
            updated_at=str(row.get("updated_at") or row["created_at"]),
            link_reason=row.get("link_reason"),
            similarity_score=row.get("similarity_score"),
            link_type=row.get("link_type"),
            origin=row.get("origin"),
        )
        for row in rows
    ]


@router.post("/notes/{note_id}/links", status_code=201)
async def create_note_link(
    note_id: uuid.UUID,
    body: CreateNoteLinkBody,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Create a directed note link."""
    source_note = await repo_get_note_by_id(session, note_id)
    if source_note is None:
        raise NotFoundError(f"Note not found: {note_id}")
    target_uuid = body.target_note_id
    target_note = await repo_get_note_by_id(session, target_uuid)
    if target_note is None:
        raise NotFoundError(f"Target note not found: {target_uuid}")

    async with session_transaction(session):
        await repo_create_note_link(
            session,
            source_note_id=note_id,
            target_note_id=target_uuid,
            link_reason=body.link_reason,
            similarity_score=body.similarity_score,
            auto_discovered=body.auto_discovered,
            link_type=body.link_type,
            origin=body.origin,
        )
    logger.info("note_link_created_via_api", source=str(note_id), target=str(body.target_note_id))
    return {"status": "created"}


@router.get("/note-canvases", response_model=PaginatedResponse[NoteCanvasDTO])
async def list_note_canvases(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[NoteCanvasDTO]:
    """List note canvases."""
    _require_notes_workspace_enabled()
    canvases, total = await repo_list_note_canvases(session, limit=limit, offset=offset)
    return paginate(
        items=[_canvas_to_dto(canvas) for canvas in canvases],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/note-canvases", response_model=NoteCanvasDTO, status_code=201)
async def create_note_canvas(
    body: CreateNoteCanvasBody,
    session: AsyncSession = Depends(get_db),
) -> NoteCanvasDTO:
    """Create a note canvas."""
    _require_notes_workspace_enabled()
    async with session_transaction(session):
        canvas = await repo_create_note_canvas(
            session,
            title=body.title,
            description=body.description,
            primary_note_id=body.primary_note_id,
            nodes=body.nodes,
            edges=body.edges,
            viewport=body.viewport,
        )
    await session.refresh(canvas)
    return _canvas_to_dto(canvas)


@router.patch("/note-canvases/{canvas_id}", response_model=NoteCanvasDTO)
async def update_note_canvas(
    canvas_id: uuid.UUID,
    body: UpdateNoteCanvasBody,
    session: AsyncSession = Depends(get_db),
) -> NoteCanvasDTO:
    """Update canvas nodes, edges, and metadata."""
    _require_notes_workspace_enabled()
    async with session_transaction(session):
        try:
            canvas = await repo_update_note_canvas(
                session,
                canvas_id,
                title=body.title,
                description=body.description,
                primary_note_id=body.primary_note_id,
                nodes=body.nodes,
                edges=body.edges,
                viewport=body.viewport,
            )
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc
    await session.refresh(canvas)
    return _canvas_to_dto(canvas)


@router.get("/note-canvases/{canvas_id}", response_model=NoteCanvasDTO)
async def get_note_canvas(
    canvas_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> NoteCanvasDTO:
    """Get a single note canvas."""
    _require_notes_workspace_enabled()
    canvas = await repo_get_note_canvas(session, canvas_id)
    if canvas is None:
        raise NotFoundError(f"Note canvas not found: {canvas_id}")
    return _canvas_to_dto(canvas)
