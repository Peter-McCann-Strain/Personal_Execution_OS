"""Content asset repository -- source packs and tracked output artifacts."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import ContentAsset, Note, Project, Task

logger = structlog.get_logger()


async def _session_add(session: AsyncSession, instance: object) -> None:
    result = session.add(instance)
    if inspect.isawaitable(result):
        await result


def _default_template_prompt(asset_type: str, title: str) -> str:
    if asset_type == "notebooklm_podcast":
        return (
            f"Create a NotebookLM podcast source pack for '{title}'. "
            "Keep the story arc tight, preserve concrete facts, and call out open questions."
        )
    return f"Prepare the source material for '{title}'."


async def _get_live_note(session: AsyncSession, note_id: uuid.UUID) -> Note | None:
    result = await session.execute(
        select(Note).where(Note.id == note_id, Note.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def _get_live_project(session: AsyncSession, project_id: uuid.UUID) -> Project | None:
    result = await session.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


def _note_source_pack(note: Note) -> dict[str, Any]:
    return {
        "note_id": str(note.id),
        "title": note.title,
        "slug": note.slug,
        "kind": note.kind,
        "summary": note.executive_summary,
        "tags": note.tags or [],
        "content": note.content,
        "source_url": note.source_url,
    }


def _project_source_pack(project: Project) -> dict[str, Any]:
    return {
        "project_id": str(project.id),
        "title": project.title,
        "description": project.description,
        "status": project.status,
        "appetite": project.appetite,
        "deadline": project.deadline.isoformat() if project.deadline else None,
    }


def _task_source_pack(task: Task) -> dict[str, Any]:
    return {
        "task_id": str(task.id),
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "estimate_hours": task.estimate_hours,
        "context_tags": task.context_tags or [],
    }


def _build_source_pack(
    *,
    asset: ContentAsset,
    note: Note | None,
    project: Project | None,
    task: Task | None,
) -> dict[str, Any]:
    documents: list[dict[str, Any]] = []
    if note is not None:
        documents.append(
            {
                "type": "note",
                "title": note.title,
                "summary": note.executive_summary,
                "content": note.content,
                "source_url": note.source_url,
                "tags": note.tags or [],
            }
        )
    if project is not None:
        documents.append(
            {
                "type": "project",
                "title": project.title,
                "summary": project.description,
                "content": project.description or "",
            }
        )
    if task is not None:
        documents.append(
            {
                "type": "task",
                "title": task.title,
                "summary": task.description,
                "content": task.description or "",
            }
        )

    pack: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "asset_type": asset.asset_type,
        "title": asset.title,
        "lineage": {
            "note_id": str(asset.note_id) if asset.note_id else None,
            "project_id": str(asset.project_id) if asset.project_id else None,
            "task_id": str(asset.task_id) if asset.task_id else None,
        },
        "documents": documents,
    }
    if note is not None:
        pack["primary_note"] = _note_source_pack(note)
    if project is not None:
        pack["project"] = _project_source_pack(project)
    if task is not None:
        pack["task"] = _task_source_pack(task)
    if asset.asset_type == "notebooklm_podcast":
        pack["notebooklm_prompt"] = _default_template_prompt(asset.asset_type, asset.title)
    return pack


async def create_content_asset(
    session: AsyncSession,
    *,
    title: str | None,
    asset_type: str,
    status: str = "ready",
    note_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    source_pack: dict[str, Any] | None = None,
    template_prompt: str | None = None,
    run_notes: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ContentAsset:
    """Create a tracked content asset with generated defaults where possible."""
    note: Note | None = None
    if note_id is not None:
        note = await _get_live_note(session, note_id)
    project: Project | None = None
    if project_id is not None:
        project = await _get_live_project(session, project_id)
    task: Task | None = None
    if task_id is not None:
        task = await session.get(Task, task_id)

    resolved_title = (
        title
        or (note.title if note is not None else None)
        or (project.title if project is not None else None)
        or (task.title if task is not None else None)
        or "Untitled content asset"
    )
    resolved_source_pack = source_pack or {}
    if note is not None and not resolved_source_pack:
        resolved_source_pack = _note_source_pack(note)

    asset = ContentAsset(
        note_id=note_id,
        project_id=project_id,
        task_id=task_id,
        title=resolved_title,
        asset_type=asset_type,
        status=status,
        source_pack=resolved_source_pack,
        template_prompt=template_prompt or _default_template_prompt(asset_type, resolved_title),
        run_notes=run_notes,
        metadata_=metadata or {},
    )
    await _session_add(session, asset)
    await session.flush()
    logger.info("content_asset_created", asset_id=str(asset.id), asset_type=asset_type)
    return asset


async def get_content_asset(
    session: AsyncSession,
    asset_id: uuid.UUID,
) -> ContentAsset | None:
    """Get a content asset by id."""
    result = await session.execute(
        select(ContentAsset).where(
            ContentAsset.id == asset_id,
            ContentAsset.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def list_content_assets(
    session: AsyncSession,
    *,
    asset_type: str | None = None,
    status: str | None = None,
    note_id: uuid.UUID | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[ContentAsset], int]:
    """List content assets for the content-factory queue."""
    stmt = select(ContentAsset).where(ContentAsset.deleted_at.is_(None))
    if asset_type is not None:
        stmt = stmt.where(ContentAsset.asset_type == asset_type)
    if status is not None:
        stmt = stmt.where(ContentAsset.status == status)
    if note_id is not None:
        stmt = stmt.where(ContentAsset.note_id == note_id)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    result = await session.execute(
        stmt.order_by(ContentAsset.updated_at.desc(), ContentAsset.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def update_content_asset(
    session: AsyncSession,
    asset_id: uuid.UUID,
    *,
    title: str | None = None,
    status: str | None = None,
    source_pack: dict[str, Any] | None = None,
    template_prompt: str | None = None,
    run_notes: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ContentAsset:
    """Update a content asset's queue state and source materials."""
    asset = await get_content_asset(session, asset_id)
    if asset is None:
        msg = f"Content asset not found: {asset_id}"
        raise ValueError(msg)

    if title is not None:
        asset.title = title
    if status is not None:
        asset.status = status
    if source_pack is not None:
        asset.source_pack = source_pack
    if template_prompt is not None:
        asset.template_prompt = template_prompt
    if run_notes is not None:
        asset.run_notes = run_notes
    if metadata is not None:
        asset.metadata_ = metadata
    await session.flush()
    logger.info("content_asset_updated", asset_id=str(asset_id))
    return asset


async def generate_content_source_pack(
    session: AsyncSession,
    asset_id: uuid.UUID,
) -> ContentAsset:
    """Rebuild a source pack from the linked note/project/task state."""
    asset = await get_content_asset(session, asset_id)
    if asset is None:
        msg = f"Content asset not found: {asset_id}"
        raise ValueError(msg)

    note = await _get_live_note(session, asset.note_id) if asset.note_id else None
    project = await _get_live_project(session, asset.project_id) if asset.project_id else None
    task = await session.get(Task, asset.task_id) if asset.task_id else None

    source_pack = _build_source_pack(
        asset=asset,
        note=note,
        project=project,
        task=task,
    )
    asset.source_pack = source_pack
    asset.metadata_ = {
        **(asset.metadata_ or {}),
        "source_pack_generated_at": source_pack.get("generated_at"),
    }
    await session.flush()
    logger.info("content_asset_source_pack_generated", asset_id=str(asset_id))
    return asset
