"""Saved-memory control-center routes."""

from __future__ import annotations

import inspect
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import Principal, get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.core.exceptions import NotFoundError
from src.app.persistence.models import AuditEvent, SavedMemory
from src.app.persistence.repositories.saved_memories import (
    create_saved_memory as repo_create_saved_memory,
)
from src.app.persistence.repositories.saved_memories import (
    get_saved_memory as repo_get_saved_memory,
)
from src.app.persistence.repositories.saved_memories import (
    list_saved_memories as repo_list_saved_memories,
)
from src.app.persistence.repositories.saved_memories import (
    merge_saved_memories as repo_merge_saved_memories,
)
from src.app.persistence.repositories.saved_memories import (
    soft_delete_saved_memory as repo_soft_delete_saved_memory,
)
from src.app.persistence.repositories.saved_memories import (
    update_saved_memory as repo_update_saved_memory,
)

router = APIRouter()


class SavedMemoryDTO(BaseModel):
    id: str
    user_id: str
    title: str
    content: str
    scope: str
    scope_key: str | None
    state: str
    source_type: str | None
    source_id: str | None
    provenance: dict[str, Any]
    pinned: bool
    auto_captured: bool
    last_used_at: str | None
    last_confirmed_at: str | None
    created_at: str
    updated_at: str


class CreateSavedMemoryBody(BaseModel):
    title: str
    content: str
    scope: str = "global"
    scope_key: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    provenance: dict[str, Any] | None = None
    pinned: bool = False
    auto_captured: bool = False


class UpdateSavedMemoryBody(BaseModel):
    title: str | None = None
    content: str | None = None
    scope: str | None = None
    scope_key: str | None = None
    state: str | None = None
    provenance: dict[str, Any] | None = None
    pinned: bool | None = None
    auto_captured: bool | None = None
    confirm_now: bool = False
    mark_used: bool = False


class MergeSavedMemoriesBody(BaseModel):
    target_memory_id: uuid.UUID
    source_memory_ids: list[uuid.UUID]


def _to_dto(memory: SavedMemory) -> SavedMemoryDTO:
    return SavedMemoryDTO(
        id=str(memory.id),
        user_id=memory.user_id,
        title=memory.title,
        content=memory.content,
        scope=memory.scope,
        scope_key=memory.scope_key,
        state=memory.state,
        source_type=memory.source_type,
        source_id=memory.source_id,
        provenance=memory.provenance or {},
        pinned=bool(memory.pinned),
        auto_captured=bool(memory.auto_captured),
        last_used_at=memory.last_used_at.isoformat() if memory.last_used_at else None,
        last_confirmed_at=(
            memory.last_confirmed_at.isoformat() if memory.last_confirmed_at else None
        ),
        created_at=memory.created_at.isoformat(),
        updated_at=memory.updated_at.isoformat(),
    )


async def _session_add(session: AsyncSession, instance: object) -> None:
    result = session.add(instance)
    if inspect.isawaitable(result):
        await result


def _principal_user_ref(principal: Principal) -> str:
    return principal.external_subject or principal.subject


async def _record_saved_memory_audit_event(
    session: AsyncSession,
    *,
    principal: Principal,
    event_type: str,
    memory_id: uuid.UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    await _session_add(
        session,
        AuditEvent(
            account_id=principal.account_id,
            user_id=principal.user_id,
            event_type=event_type,
            actor_type="user",
            resource_type="saved_memory",
            resource_id=str(memory_id),
            metadata_=metadata or {},
        ),
    )


@router.get("/saved-memories", response_model=PaginatedResponse[SavedMemoryDTO])
async def list_saved_memories(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    scope: str | None = Query(None),
    state: str | None = Query(None),
) -> PaginatedResponse[SavedMemoryDTO]:
    """List explicit saved memories for the current owner."""
    user_id = _principal_user_ref(principal)
    items, total = await repo_list_saved_memories(
        session,
        user_id=user_id,
        limit=limit,
        offset=offset,
        search=search,
        scope=scope,
        state=state,
    )
    return paginate(
        items=[_to_dto(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/saved-memories", response_model=SavedMemoryDTO, status_code=201)
async def create_saved_memory(
    body: CreateSavedMemoryBody,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> SavedMemoryDTO:
    """Create one explicit saved memory."""
    user_id = _principal_user_ref(principal)
    memory = await repo_create_saved_memory(
        session,
        user_id=user_id,
        title=body.title,
        content=body.content,
        scope=body.scope,
        scope_key=body.scope_key,
        source_type=body.source_type,
        source_id=body.source_id,
        provenance=body.provenance,
        pinned=body.pinned,
        auto_captured=body.auto_captured,
    )
    await _record_saved_memory_audit_event(
        session,
        principal=principal,
        event_type="saved_memory.created",
        memory_id=memory.id,
        metadata={
            "scope": body.scope,
            "source_type": body.source_type,
            "pinned": body.pinned,
            "auto_captured": body.auto_captured,
        },
    )
    await session.commit()
    return _to_dto(memory)


@router.post("/saved-memories/merge", response_model=SavedMemoryDTO)
async def merge_saved_memories(
    body: MergeSavedMemoriesBody,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> SavedMemoryDTO:
    """Merge multiple saved memories into one durable record."""
    user_id = _principal_user_ref(principal)
    source_ids = [
        memory_id for memory_id in body.source_memory_ids if memory_id != body.target_memory_id
    ]
    if not source_ids:
        raise HTTPException(status_code=400, detail="Provide at least one source memory to merge.")

    memory = await repo_merge_saved_memories(
        session,
        target_memory_id=body.target_memory_id,
        source_memory_ids=source_ids,
        user_id=user_id,
    )
    if memory is None:
        raise NotFoundError("Unable to merge saved memories.")
    await _record_saved_memory_audit_event(
        session,
        principal=principal,
        event_type="saved_memory.merged",
        memory_id=memory.id,
        metadata={
            "source_memory_ids": [str(memory_id) for memory_id in source_ids],
            "source_count": len(source_ids),
        },
    )
    await session.commit()
    return _to_dto(memory)


@router.patch("/saved-memories/{memory_id}", response_model=SavedMemoryDTO)
async def update_saved_memory(
    memory_id: uuid.UUID,
    body: UpdateSavedMemoryBody,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> SavedMemoryDTO:
    """Update one saved memory."""
    user_id = _principal_user_ref(principal)
    memory = await repo_update_saved_memory(
        session,
        memory_id=memory_id,
        user_id=user_id,
        title=body.title,
        content=body.content,
        scope=body.scope,
        scope_key=body.scope_key,
        state=body.state,
        provenance=body.provenance,
        pinned=body.pinned,
        auto_captured=body.auto_captured,
        last_used=body.mark_used,
        confirm_now=body.confirm_now,
    )
    if memory is None:
        raise NotFoundError(f"Saved memory not found: {memory_id}")
    fields_set: set[str] = set(
        getattr(body, "model_fields_set", getattr(body, "__fields_set__", set()))
    )
    await _record_saved_memory_audit_event(
        session,
        principal=principal,
        event_type="saved_memory.updated",
        memory_id=memory.id,
        metadata={
            "changed_fields": sorted(fields_set),
            "state": body.state,
            "pinned": body.pinned,
            "confirm_now": body.confirm_now,
            "mark_used": body.mark_used,
        },
    )
    await session.commit()
    return _to_dto(memory)


@router.get("/saved-memories/{memory_id}", response_model=SavedMemoryDTO)
async def get_saved_memory(
    memory_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> SavedMemoryDTO:
    """Get one saved memory by id."""
    user_id = _principal_user_ref(principal)
    memory = await repo_get_saved_memory(session, memory_id=memory_id, user_id=user_id)
    if memory is None:
        raise NotFoundError(f"Saved memory not found: {memory_id}")
    return _to_dto(memory)


@router.delete("/saved-memories/{memory_id}", status_code=204)
async def delete_saved_memory(
    memory_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Forget one saved memory."""
    user_id = _principal_user_ref(principal)
    deleted = await repo_soft_delete_saved_memory(
        session,
        memory_id=memory_id,
        user_id=user_id,
    )
    if not deleted:
        raise NotFoundError(f"Saved memory not found: {memory_id}")
    await _record_saved_memory_audit_event(
        session,
        principal=principal,
        event_type="saved_memory.deleted",
        memory_id=memory_id,
    )
    await session.commit()
    return Response(status_code=204)
