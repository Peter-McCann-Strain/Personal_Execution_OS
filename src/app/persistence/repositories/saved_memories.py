"""Persistence helpers for explicit saved memories."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.async_utils import maybe_await
from src.app.persistence.models import SavedMemory, not_deleted


async def _session_add(session: AsyncSession, instance: object) -> None:
    result = session.add(instance)
    if inspect.isawaitable(result):
        await result


async def create_saved_memory(
    session: AsyncSession,
    *,
    user_id: str,
    title: str,
    content: str,
    scope: str = "global",
    scope_key: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    provenance: dict[str, Any] | None = None,
    pinned: bool = False,
    auto_captured: bool = False,
) -> SavedMemory:
    """Create one explicit saved memory."""
    record = SavedMemory(
        user_id=user_id,
        title=title,
        content=content,
        scope=scope,
        scope_key=scope_key,
        source_type=source_type,
        source_id=source_id,
        provenance=provenance or {},
        pinned=pinned,
        auto_captured=auto_captured,
    )
    await _session_add(session, record)
    await session.flush()
    return record


async def get_saved_memory(
    session: AsyncSession,
    *,
    memory_id: uuid.UUID,
    user_id: str,
) -> SavedMemory | None:
    """Fetch one saved memory for one user."""
    stmt = select(SavedMemory).where(
        SavedMemory.id == memory_id,
        SavedMemory.user_id == user_id,
        not_deleted(SavedMemory),
    )
    result = await session.execute(stmt.limit(1))
    return result.scalar_one_or_none()


async def list_saved_memories(
    session: AsyncSession,
    *,
    user_id: str,
    limit: int = 25,
    offset: int = 0,
    search: str | None = None,
    scope: str | None = None,
    state: str | None = None,
) -> tuple[list[SavedMemory], int]:
    """List saved memories with basic search/filter support."""
    stmt = select(SavedMemory).where(
        SavedMemory.user_id == user_id,
        not_deleted(SavedMemory),
    )
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                SavedMemory.title.ilike(pattern),
                SavedMemory.content.ilike(pattern),
            )
        )
    if scope:
        stmt = stmt.where(SavedMemory.scope == scope)
    if state:
        stmt = stmt.where(SavedMemory.state == state)

    count_result = await session.execute(select(func.count()).select_from(stmt.subquery()))
    total_value = await maybe_await(count_result.scalar_one())
    if isinstance(total_value, bool) or not isinstance(total_value, int):
        msg = "saved-memory count query returned a non-integer value"
        raise TypeError(msg)
    if total_value < 0:
        msg = "saved-memory count query returned a negative value"
        raise ValueError(msg)
    total = total_value

    result = await session.execute(
        stmt.order_by(
            SavedMemory.pinned.desc(),
            SavedMemory.updated_at.desc(),
            SavedMemory.created_at.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    scalars = await maybe_await(result.scalars())
    rows = await maybe_await(scalars.all())
    return list(rows), total


async def update_saved_memory(
    session: AsyncSession,
    *,
    memory_id: uuid.UUID,
    user_id: str,
    title: str | None = None,
    content: str | None = None,
    scope: str | None = None,
    scope_key: str | None = None,
    state: str | None = None,
    provenance: dict[str, Any] | None = None,
    pinned: bool | None = None,
    auto_captured: bool | None = None,
    last_used: bool = False,
    confirm_now: bool = False,
) -> SavedMemory | None:
    """Update one saved memory and return the fresh row."""
    record = await get_saved_memory(session, memory_id=memory_id, user_id=user_id)
    if record is None:
        return None

    if title is not None:
        record.title = title
    if content is not None:
        record.content = content
    if scope is not None:
        record.scope = scope
    if scope_key is not None:
        record.scope_key = scope_key
    if state is not None:
        record.state = state
    if provenance is not None:
        record.provenance = provenance
    if pinned is not None:
        record.pinned = pinned
    if auto_captured is not None:
        record.auto_captured = auto_captured
    if last_used:
        record.last_used_at = datetime.now(UTC)
    if confirm_now:
        record.last_confirmed_at = datetime.now(UTC)
    record.updated_at = datetime.now(UTC)
    await session.flush()
    return record


def _merge_memory_content(blocks: list[str]) -> str:
    """Combine memory blocks while removing trivial duplicates."""
    merged: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        normalized_block = " ".join(block.split()).strip().casefold()
        if not normalized_block or normalized_block in seen:
            continue
        seen.add(normalized_block)
        merged.append(block.strip())
    return "\n\n---\n\n".join(merged)


async def merge_saved_memories(
    session: AsyncSession,
    *,
    target_memory_id: uuid.UUID,
    source_memory_ids: list[uuid.UUID],
    user_id: str,
) -> SavedMemory | None:
    """Merge multiple saved memories into one surviving record."""
    target = await get_saved_memory(session, memory_id=target_memory_id, user_id=user_id)
    if target is None:
        return None

    unique_source_ids = [
        memory_id for memory_id in dict.fromkeys(source_memory_ids) if memory_id != target_memory_id
    ]
    if not unique_source_ids:
        return target

    stmt = select(SavedMemory).where(
        SavedMemory.user_id == user_id,
        SavedMemory.id.in_(unique_source_ids),
        not_deleted(SavedMemory),
    )
    result = await session.execute(stmt)
    sources = list(result.scalars().all())
    if len(sources) != len(unique_source_ids):
        return None

    now = datetime.now(UTC)
    merged_records = [target, *sources]
    merged_provenance = dict(target.provenance or {})
    merged_provenance["merged_at"] = now.isoformat()
    merged_provenance["merged_from_ids"] = [str(record.id) for record in sources]
    merged_provenance["merged_from_titles"] = [record.title for record in sources]
    merged_provenance["merged_count"] = len(sources)

    target.content = _merge_memory_content([record.content for record in merged_records])
    target.pinned = any(record.pinned for record in merged_records)
    target.auto_captured = all(record.auto_captured for record in merged_records)
    target.state = (
        "active"
        if any(record.state == "active" for record in merged_records)
        else "snoozed"
        if any(record.state == "snoozed" for record in merged_records)
        else "archived"
    )
    target.last_used_at = max(
        (record.last_used_at for record in merged_records if record.last_used_at is not None),
        default=target.last_used_at,
    )
    target.last_confirmed_at = max(
        (
            record.last_confirmed_at
            for record in merged_records
            if record.last_confirmed_at is not None
        ),
        default=target.last_confirmed_at,
    )
    target.provenance = merged_provenance
    target.updated_at = now

    for record in sources:
        record.deleted_at = now
        record.updated_at = now

    await session.flush()
    return target


async def soft_delete_saved_memory(
    session: AsyncSession,
    *,
    memory_id: uuid.UUID,
    user_id: str,
) -> bool:
    """Soft-delete one saved memory."""
    record = await get_saved_memory(session, memory_id=memory_id, user_id=user_id)
    if record is None:
        return False
    record.deleted_at = datetime.now(UTC)
    record.updated_at = datetime.now(UTC)
    await session.flush()
    return True


async def mark_saved_memories_used(
    session: AsyncSession,
    *,
    user_id: str,
    memory_ids: list[uuid.UUID],
) -> int:
    """Touch one or more saved memories after they materially informed an answer."""
    unique_ids = list(dict.fromkeys(memory_ids))
    if not unique_ids:
        return 0

    stmt = select(SavedMemory).where(
        SavedMemory.user_id == user_id,
        SavedMemory.id.in_(unique_ids),
        not_deleted(SavedMemory),
    )
    result = await session.execute(stmt)
    records = list(result.scalars().all())
    if not records:
        return 0

    now = datetime.now(UTC)
    for record in records:
        record.last_used_at = now
        record.updated_at = now

    await session.flush()
    return len(records)


async def search_saved_memories(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    limit: int = 5,
) -> list[SavedMemory]:
    """Return top saved memories matching a loose text query."""
    memories, _total = await list_saved_memories(
        session,
        user_id=user_id,
        limit=limit,
        offset=0,
        search=query,
        state="active",
    )
    return memories
