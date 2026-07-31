"""Persistence helpers for connector accounts, sync jobs, and indexed documents."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import (
    ConnectorAccount,
    ConnectorDocument,
    ConnectorSyncJob,
    not_deleted,
)


async def _session_add(session: AsyncSession, instance: object) -> None:
    result = session.add(instance)
    if inspect.isawaitable(result):
        await result


async def create_connector_account(
    session: AsyncSession,
    *,
    user_id: str,
    connector_type: str,
    display_name: str,
    scopes: list[str] | None = None,
    auto_use: bool = True,
    background_access: bool = False,
    sync_enabled: bool = False,
    status: str = "connected",
    encrypted_refresh_token: str | None = None,
    token_last_rotated_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> ConnectorAccount:
    """Create one connector account."""
    record = ConnectorAccount(
        user_id=user_id,
        connector_type=connector_type,
        display_name=display_name,
        scopes=scopes,
        auto_use=auto_use,
        background_access=background_access,
        sync_enabled=sync_enabled,
        status=status,
        encrypted_refresh_token=encrypted_refresh_token,
        token_last_rotated_at=token_last_rotated_at,
        metadata_=metadata or {},
    )
    await _session_add(session, record)
    await session.flush()
    return record


async def get_connector_account(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    user_id: str,
) -> ConnectorAccount | None:
    """Fetch one connector account for one user."""
    stmt = select(ConnectorAccount).where(
        ConnectorAccount.id == account_id,
        ConnectorAccount.user_id == user_id,
        not_deleted(ConnectorAccount),
    )
    result = await session.execute(stmt.limit(1))
    return result.scalar_one_or_none()


async def list_connector_accounts(
    session: AsyncSession,
    *,
    user_id: str,
    connector_type: str | None = None,
) -> list[ConnectorAccount]:
    """List connector accounts for one user."""
    stmt = select(ConnectorAccount).where(
        ConnectorAccount.user_id == user_id,
        not_deleted(ConnectorAccount),
    )
    if connector_type:
        stmt = stmt.where(ConnectorAccount.connector_type == connector_type)
    result = await session.execute(
        stmt.order_by(ConnectorAccount.connector_type.asc(), ConnectorAccount.created_at.asc())
    )
    return list(result.scalars().all())


async def update_connector_account(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    user_id: str,
    display_name: str | None = None,
    scopes: list[str] | None = None,
    auto_use: bool | None = None,
    background_access: bool | None = None,
    sync_enabled: bool | None = None,
    status: str | None = None,
    encrypted_refresh_token: str | None = None,
    token_last_rotated_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    last_sync_at: datetime | None = None,
) -> ConnectorAccount | None:
    """Update one connector account."""
    record = await get_connector_account(session, account_id=account_id, user_id=user_id)
    if record is None:
        return None

    if display_name is not None:
        record.display_name = display_name
    if scopes is not None:
        record.scopes = scopes
    if auto_use is not None:
        record.auto_use = auto_use
    if background_access is not None:
        record.background_access = background_access
    if sync_enabled is not None:
        record.sync_enabled = sync_enabled
    if status is not None:
        record.status = status
    if encrypted_refresh_token is not None:
        record.encrypted_refresh_token = encrypted_refresh_token
    if token_last_rotated_at is not None:
        record.token_last_rotated_at = token_last_rotated_at
    if metadata is not None:
        record.metadata_ = metadata
    if last_sync_at is not None:
        record.last_sync_at = last_sync_at
    record.updated_at = datetime.now(UTC)
    await session.flush()
    return record


async def purge_connector_account(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    user_id: str,
) -> bool:
    """Permanently remove a connector, its sync history, and indexed copies."""
    record = await get_connector_account(
        session,
        account_id=account_id,
        user_id=user_id,
    )
    if record is None:
        return False
    await session.execute(
        delete(ConnectorDocument).where(ConnectorDocument.account_id == account_id)
    )
    await session.execute(delete(ConnectorSyncJob).where(ConnectorSyncJob.account_id == account_id))
    result = session.delete(record)
    if inspect.isawaitable(result):
        await result
    await session.flush()
    return True


async def create_connector_sync_job(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    sync_type: str = "incremental",
    status: str = "queued",
    metadata: dict[str, Any] | None = None,
) -> ConnectorSyncJob:
    """Create one connector sync job."""
    record = ConnectorSyncJob(
        account_id=account_id,
        sync_type=sync_type,
        status=status,
        metadata_=metadata or {},
        started_at=datetime.now(UTC) if status == "running" else None,
    )
    await _session_add(session, record)
    await session.flush()
    return record


async def update_connector_sync_job(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    status: str,
    document_count: int | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ConnectorSyncJob | None:
    """Update a connector sync job."""
    record = await session.get(ConnectorSyncJob, job_id)
    if record is None:
        return None
    record.status = status
    if document_count is not None:
        record.document_count = document_count
    if error_message is not None:
        record.error_message = error_message
    if metadata is not None:
        record.metadata_ = metadata
    if status == "running":
        record.started_at = record.started_at or datetime.now(UTC)
    if status in {"completed", "failed"}:
        record.completed_at = datetime.now(UTC)
    await session.flush()
    return record


async def list_connector_sync_jobs(
    session: AsyncSession,
    *,
    user_id: str,
    account_id: uuid.UUID | None = None,
    limit: int = 25,
) -> list[ConnectorSyncJob]:
    """List connector sync jobs for one user."""
    stmt = (
        select(ConnectorSyncJob)
        .join(
            ConnectorAccount,
            ConnectorSyncJob.account_id == ConnectorAccount.id,
        )
        .where(
            ConnectorAccount.user_id == user_id,
            not_deleted(ConnectorAccount),
        )
    )
    if account_id is not None:
        stmt = stmt.where(ConnectorSyncJob.account_id == account_id)
    result = await session.execute(stmt.order_by(ConnectorSyncJob.created_at.desc()).limit(limit))
    return list(result.scalars().all())


async def upsert_connector_document(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    external_id: str,
    source_type: str,
    title: str,
    content: str,
    source_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ConnectorDocument:
    """Create or update one indexed connector document."""
    stmt = select(ConnectorDocument).where(
        ConnectorDocument.account_id == account_id,
        ConnectorDocument.external_id == external_id,
        not_deleted(ConnectorDocument),
    )
    result = await session.execute(stmt.limit(1))
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.source_type = source_type
        existing.title = title
        existing.content = content
        existing.source_url = source_url
        existing.metadata_ = metadata or {}
        existing.synced_at = datetime.now(UTC)
        existing.updated_at = datetime.now(UTC)
        await session.flush()
        return existing

    record = ConnectorDocument(
        account_id=account_id,
        external_id=external_id,
        source_type=source_type,
        title=title,
        content=content,
        source_url=source_url,
        metadata_=metadata or {},
    )
    await _session_add(session, record)
    await session.flush()
    return record


async def list_connector_documents(
    session: AsyncSession,
    *,
    user_id: str,
    limit: int = 25,
    offset: int = 0,
    account_id: uuid.UUID | None = None,
    source_type: str | None = None,
    search: str | None = None,
) -> tuple[list[ConnectorDocument], int]:
    """List indexed connector documents for one user."""
    stmt = (
        select(ConnectorDocument)
        .join(
            ConnectorAccount,
            ConnectorDocument.account_id == ConnectorAccount.id,
        )
        .where(
            ConnectorAccount.user_id == user_id,
            not_deleted(ConnectorAccount),
            not_deleted(ConnectorDocument),
        )
    )
    if account_id is not None:
        stmt = stmt.where(ConnectorDocument.account_id == account_id)
    if source_type is not None:
        stmt = stmt.where(ConnectorDocument.source_type == source_type)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                ConnectorDocument.title.ilike(pattern),
                ConnectorDocument.content.ilike(pattern),
            )
        )

    count_result = await session.execute(select(func.count()).select_from(stmt.subquery()))
    total_value = count_result.scalar_one()
    if inspect.isawaitable(total_value):
        total_value = await total_value
    total = int(total_value)
    result = await session.execute(
        stmt.order_by(ConnectorDocument.synced_at.desc()).offset(offset).limit(limit)
    )
    scalars = result.scalars()
    if inspect.isawaitable(scalars):
        scalars = await scalars
    rows = scalars.all()
    if inspect.isawaitable(rows):
        rows = await rows
    return list(rows), total


async def search_connector_documents(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    limit: int = 5,
) -> list[ConnectorDocument]:
    """Return top connector documents for a loose text query."""
    documents, _total = await list_connector_documents(
        session,
        user_id=user_id,
        limit=limit,
        offset=0,
        search=query,
    )
    return documents
