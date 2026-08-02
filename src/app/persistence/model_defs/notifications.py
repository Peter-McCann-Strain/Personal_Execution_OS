"""Notifications persistence models."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.persistence.model_defs.base import (
    AccountScopedMixin,
    Base,
    SoftDeleteMixin,
)


class NotificationRecord(Base, AccountScopedMixin):
    """Persistent notifications for the frontend UI."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(5), nullable=False, default="P2")
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="system")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unread")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_notifications_status", "status"),
        Index("ix_notifications_priority", "priority"),
        Index("ix_notifications_created_at", "created_at"),
    )


class WebPushSubscription(Base, AccountScopedMixin, SoftDeleteMixin):
    """Persisted browser push subscription for owner-scoped delivery."""

    __tablename__ = "web_push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    auth_key: Mapped[str] = mapped_column(String(255), nullable=False)
    p256dh_key: Mapped[str] = mapped_column(String(255), nullable=False)
    expiration_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'error', 'revoked')",
            name="ck_web_push_subscriptions_status",
        ),
        UniqueConstraint(
            "user_id",
            "endpoint_hash",
            name="uq_web_push_subscriptions_user_endpoint",
        ),
        Index("ix_web_push_subscriptions_user_id", "user_id"),
        Index("ix_web_push_subscriptions_status", "status"),
        Index("ix_web_push_subscriptions_last_seen_at", "last_seen_at"),
    )
