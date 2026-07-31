"""Notification endpoints — list, dismiss, mark read, unread count."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.core.exceptions import NotFoundError
from src.app.domain.constants import NotificationStatus
from src.app.persistence.models import NotificationRecord

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class NotificationDTO(BaseModel):
    id: str
    message: str
    priority: str
    category: str
    created_at: str
    dismissed: bool


class UnreadCountDTO(BaseModel):
    model_config = {"populate_by_name": True}

    total: int
    has_p0: bool = Field(serialization_alias="hasP0")
    has_p1: bool = Field(serialization_alias="hasP1")


class StatusResponse(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _notification_to_dto(n: NotificationRecord) -> NotificationDTO:
    return NotificationDTO(
        id=str(n.id),
        message=n.message,
        priority=n.priority,
        category=n.category,
        created_at=n.created_at.isoformat(),
        dismissed=n.status == NotificationStatus.DISMISSED,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/notifications", response_model=PaginatedResponse[NotificationDTO])
async def list_notifications(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    priority: str | None = Query(None, description="Comma-separated priorities, e.g. P0,P1"),
    category: str | None = Query(None),
    status: str | None = Query(None, description="unread, read, or dismissed"),
    group_by: str | None = Query(None, description="Ignored for now"),
) -> PaginatedResponse[NotificationDTO]:
    """List notifications with optional filters."""
    query = select(NotificationRecord)

    # --- Filters ---
    if priority:
        priority_list = [p.strip() for p in priority.split(",") if p.strip()]
        if priority_list:
            query = query.where(NotificationRecord.priority.in_(priority_list))

    if category:
        query = query.where(NotificationRecord.category == category)

    if status:
        query = query.where(NotificationRecord.status == status)

    # --- Order ---
    query = query.order_by(NotificationRecord.created_at.desc())

    # --- Count ---
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar_one()

    # --- Paginate ---
    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    notifications = list(result.scalars().all())

    items = [_notification_to_dto(n) for n in notifications]
    return paginate(items=items, total=total, offset=offset, limit=limit)


@router.patch("/notifications/{notification_id}/dismiss", response_model=StatusResponse)
async def dismiss_notification(
    notification_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> StatusResponse:
    """Dismiss a single notification."""
    notif = await session.get(NotificationRecord, notification_id)
    if notif is None:
        raise NotFoundError(f"Notification {notification_id} not found")

    notif.status = "dismissed"
    await session.commit()
    logger.info("notification_dismissed", notification_id=str(notification_id))
    return StatusResponse(status="ok")


@router.patch("/notifications/dismiss-all", response_model=StatusResponse)
async def dismiss_all_notifications(
    session: AsyncSession = Depends(get_db),
) -> StatusResponse:
    """Dismiss all non-dismissed notifications."""
    await session.execute(
        update(NotificationRecord)
        .where(NotificationRecord.status != NotificationStatus.DISMISSED)
        .values(status=NotificationStatus.DISMISSED)
    )
    await session.commit()
    logger.info("notifications_all_dismissed")
    return StatusResponse(status="ok")


@router.patch("/notifications/mark-all-read", response_model=StatusResponse)
async def mark_all_read(
    session: AsyncSession = Depends(get_db),
) -> StatusResponse:
    """Mark all unread notifications as read."""
    await session.execute(
        update(NotificationRecord)
        .where(NotificationRecord.status == NotificationStatus.UNREAD)
        .values(status=NotificationStatus.READ)
    )
    await session.commit()
    logger.info("notifications_all_marked_read")
    return StatusResponse(status="ok")


@router.get("/notifications/unread-count", response_model=UnreadCountDTO)
async def unread_count(
    session: AsyncSession = Depends(get_db),
) -> UnreadCountDTO:
    """Get unread notification count with P0/P1 flags."""
    # Total unread
    total_result = await session.execute(
        select(func.count()).where(NotificationRecord.status == NotificationStatus.UNREAD)
    )
    total = total_result.scalar_one()

    # Has P0
    p0_result = await session.execute(
        select(func.count()).where(
            NotificationRecord.status == NotificationStatus.UNREAD,
            NotificationRecord.priority == "P0",
        )
    )
    has_p0 = p0_result.scalar_one() > 0

    # Has P1
    p1_result = await session.execute(
        select(func.count()).where(
            NotificationRecord.status == NotificationStatus.UNREAD,
            NotificationRecord.priority == "P1",
        )
    )
    has_p1 = p1_result.scalar_one() > 0

    return UnreadCountDTO(total=total, has_p0=has_p0, has_p1=has_p1)
