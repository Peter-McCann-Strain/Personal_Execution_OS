"""Local-owner account data controls."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import Principal, get_current_principal, get_db, scope_session_to_principal
from src.app.core.exceptions import NotFoundError
from src.app.domain.services.account_data import build_core_data_export_payload
from src.app.persistence.models import AuditEvent, DataExport

router = APIRouter()


class PrincipalDTO(BaseModel):
    subject: str
    user_id: str
    account_id: str
    role: str
    plan: str
    scopes: list[str]
    auth_method: str


class CoreDataExportDTO(BaseModel):
    id: str
    scope: str = "core_database_records"
    limitations: str = (
        "Exports enumerated core database records only; provider data, files, logs, "
        "caches, backups, and external model-provider records are excluded."
    )
    status: str
    storage_url: str | None
    expires_at: str | None
    created_at: str
    completed_at: str | None


def _core_data_export_to_dto(row: DataExport) -> CoreDataExportDTO:
    return CoreDataExportDTO(
        id=str(row.id),
        status=row.status,
        storage_url=row.storage_url,
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
        created_at=row.created_at.isoformat(),
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
    )


@router.get("/account/me", response_model=PrincipalDTO)
async def get_account_me(principal: Principal = Depends(get_current_principal)) -> PrincipalDTO:
    """Return the resolved account principal for web, PWA, and native clients."""
    return PrincipalDTO(
        subject=principal.subject,
        user_id=str(principal.user_id),
        account_id=str(principal.account_id),
        role=principal.role,
        plan=principal.plan,
        scopes=list(principal.scopes),
        auth_method=principal.auth_method,
    )


@router.get("/account/core-data-exports", response_model=list[CoreDataExportDTO])
async def list_core_data_exports(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> list[CoreDataExportDTO]:
    """List recent explicitly scoped core-data export requests."""
    scope_session_to_principal(session, principal)
    result = await session.execute(
        select(DataExport)
        .where(DataExport.account_id == principal.account_id)
        .order_by(DataExport.created_at.desc())
        .limit(20)
    )
    return [_core_data_export_to_dto(row) for row in result.scalars()]


@router.post("/account/core-data-exports", response_model=CoreDataExportDTO, status_code=201)
async def create_core_data_export(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> CoreDataExportDTO:
    """Queue an export of the documented core database-record scope."""
    now = datetime.now(UTC)
    row = DataExport(
        id=uuid.uuid4(),
        account_id=principal.account_id,
        requested_by_user_id=principal.user_id,
        status="queued",
        expires_at=now + timedelta(days=7),
        created_at=now,
    )
    session.add(row)
    await session.flush()
    session.add(
        AuditEvent(
            account_id=principal.account_id,
            user_id=principal.user_id,
            event_type="core_data_export.requested",
            actor_type="user",
            resource_type="core_data_export",
            resource_id=str(row.id),
        )
    )
    await session.commit()
    return _core_data_export_to_dto(row)


@router.get("/account/core-data-exports/{export_id}/download")
async def download_core_data_export(
    export_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Return only the documented core database-record export."""
    scope_session_to_principal(session, principal)
    row = await session.get(DataExport, export_id)
    if row is None or row.account_id != principal.account_id:
        raise NotFoundError(f"Core data export not found: {export_id}")

    payload = await build_core_data_export_payload(session, account_id=principal.account_id)
    row.status = "completed"
    row.completed_at = datetime.now(UTC)
    row.storage_url = f"download:{row.id}"
    session.add(
        AuditEvent(
            account_id=principal.account_id,
            user_id=principal.user_id,
            event_type="core_data_export.downloaded",
            actor_type="user",
            resource_type="core_data_export",
            resource_id=str(row.id),
        )
    )
    await session.commit()
    return payload
