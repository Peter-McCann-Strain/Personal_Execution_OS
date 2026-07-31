"""Content asset API routes -- queue and track repurposed content outputs."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.api.transactions import session_transaction
from src.app.config import get_settings
from src.app.core.exceptions import NotFoundError
from src.app.persistence.repositories.content_assets import (
    create_content_asset as repo_create_content_asset,
)
from src.app.persistence.repositories.content_assets import (
    generate_content_source_pack as repo_generate_content_source_pack,
)
from src.app.persistence.repositories.content_assets import (
    get_content_asset as repo_get_content_asset,
)
from src.app.persistence.repositories.content_assets import (
    list_content_assets as repo_list_content_assets,
)
from src.app.persistence.repositories.content_assets import (
    update_content_asset as repo_update_content_asset,
)

router = APIRouter(dependencies=[Depends(get_current_principal)])


def _require_content_factory_enabled() -> None:
    if not bool(getattr(get_settings(), "content_factory_enabled", True)):
        raise NotFoundError("Content factory is not enabled.")


class ContentAssetDTO(BaseModel):
    id: str
    note_id: str | None
    project_id: str | None
    task_id: str | None
    title: str
    asset_type: str
    status: str
    source_pack: dict[str, Any]
    template_prompt: str | None
    run_notes: str | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class CreateContentAssetBody(BaseModel):
    title: str | None = None
    note_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    asset_type: str = "notebooklm_podcast"
    status: str = "ready"
    source_pack: dict[str, Any] | None = None
    template_prompt: str | None = None
    run_notes: str | None = None
    metadata: dict[str, Any] | None = None


class UpdateContentAssetBody(BaseModel):
    title: str | None = None
    status: str | None = None
    source_pack: dict[str, Any] | None = None
    template_prompt: str | None = None
    run_notes: str | None = None
    metadata: dict[str, Any] | None = None


def _asset_to_dto(asset) -> ContentAssetDTO:
    return ContentAssetDTO(
        id=str(asset.id),
        note_id=str(asset.note_id) if asset.note_id else None,
        project_id=str(asset.project_id) if asset.project_id else None,
        task_id=str(asset.task_id) if asset.task_id else None,
        title=asset.title,
        asset_type=asset.asset_type,
        status=asset.status,
        source_pack=asset.source_pack or {},
        template_prompt=asset.template_prompt,
        run_notes=asset.run_notes,
        metadata=asset.metadata_ or {},
        created_at=asset.created_at.isoformat(),
        updated_at=asset.updated_at.isoformat(),
    )


@router.get("/content-assets", response_model=PaginatedResponse[ContentAssetDTO])
async def list_content_assets(
    session: AsyncSession = Depends(get_db),
    asset_type: str | None = Query(None),
    status: str | None = Query(None),
    note_id: uuid.UUID | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[ContentAssetDTO]:
    """List queued and completed content assets."""
    _require_content_factory_enabled()
    assets, total = await repo_list_content_assets(
        session,
        asset_type=asset_type,
        status=status,
        note_id=note_id,
        limit=limit,
        offset=offset,
    )
    return paginate(
        items=[_asset_to_dto(asset) for asset in assets],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/content-assets", response_model=ContentAssetDTO, status_code=201)
async def create_content_asset(
    body: CreateContentAssetBody,
    session: AsyncSession = Depends(get_db),
) -> ContentAssetDTO:
    """Create a tracked content asset from a note/project/task."""
    _require_content_factory_enabled()
    async with session_transaction(session):
        asset = await repo_create_content_asset(
            session,
            title=body.title,
            note_id=body.note_id,
            project_id=body.project_id,
            task_id=body.task_id,
            asset_type=body.asset_type,
            status=body.status,
            source_pack=body.source_pack,
            template_prompt=body.template_prompt,
            run_notes=body.run_notes,
            metadata=body.metadata,
        )
    await session.refresh(asset)
    return _asset_to_dto(asset)


@router.get("/content-assets/{asset_id}", response_model=ContentAssetDTO)
async def get_content_asset(
    asset_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> ContentAssetDTO:
    """Fetch one content asset."""
    _require_content_factory_enabled()
    asset = await repo_get_content_asset(session, asset_id)
    if asset is None:
        raise NotFoundError(f"Content asset not found: {asset_id}")
    return _asset_to_dto(asset)


@router.post("/content-assets/{asset_id}/source-pack", response_model=ContentAssetDTO)
async def generate_content_asset_source_pack(
    asset_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> ContentAssetDTO:
    """Regenerate the normalized source pack for one asset."""
    _require_content_factory_enabled()
    async with session_transaction(session):
        try:
            asset = await repo_generate_content_source_pack(session, asset_id)
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc
    await session.refresh(asset)
    return _asset_to_dto(asset)


@router.patch("/content-assets/{asset_id}", response_model=ContentAssetDTO)
async def update_content_asset(
    asset_id: uuid.UUID,
    body: UpdateContentAssetBody,
    session: AsyncSession = Depends(get_db),
) -> ContentAssetDTO:
    """Update queue state, prompt, or run notes for a content asset."""
    _require_content_factory_enabled()
    async with session_transaction(session):
        try:
            asset = await repo_update_content_asset(
                session,
                asset_id,
                title=body.title,
                status=body.status,
                source_pack=body.source_pack,
                template_prompt=body.template_prompt,
                run_notes=body.run_notes,
                metadata=body.metadata,
            )
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc
    await session.refresh(asset)
    return _asset_to_dto(asset)
