"""Connectors persistence models."""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.persistence.model_defs.base import (
    AccountScopedMixin,
    Base,
    SoftDeleteMixin,
)


class ConnectorAccount(Base, AccountScopedMixin, SoftDeleteMixin):
    """Persisted connector configuration and sync policy."""

    __tablename__ = "connector_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="connected")
    scopes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_last_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auto_use: Mapped[bool] = mapped_column(Boolean, default=True)
    background_access: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "connector_type IN ('gmail', 'google_calendar', 'google_drive', 'tavily')",
            name="ck_connector_accounts_type",
        ),
        CheckConstraint(
            "status IN ('connected', 'disconnected', 'error')",
            name="ck_connector_accounts_status",
        ),
        Index("ix_connector_accounts_user_id", "user_id"),
        Index("ix_connector_accounts_connector_type", "connector_type"),
        Index("ix_connector_accounts_status", "status"),
    )


class ConnectorOAuthState(Base):
    """Short-lived OAuth state for customer connector authorization callbacks."""

    __tablename__ = "connector_oauth_states"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(40), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    scopes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "connector_type IN ('gmail', 'google_calendar', 'google_drive')",
            name="ck_connector_oauth_states_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'consumed', 'failed')",
            name="ck_connector_oauth_states_status",
        ),
        Index("ix_connector_oauth_states_account_id", "account_id"),
        Index("ix_connector_oauth_states_user_id", "user_id"),
        Index("ix_connector_oauth_states_state_hash", "state_hash"),
        Index("ix_connector_oauth_states_expires_at", "expires_at"),
    )


class ConnectorSyncJob(Base):
    """One background sync attempt for a connector."""

    __tablename__ = "connector_sync_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_accounts.id", ondelete="CASCADE"), nullable=False
    )
    sync_type: Mapped[str] = mapped_column(String(30), nullable=False, default="incremental")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "sync_type IN ('incremental', 'full', 'reindex')",
            name="ck_connector_sync_jobs_sync_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_connector_sync_jobs_status",
        ),
        Index("ix_connector_sync_jobs_account_id", "account_id"),
        Index("ix_connector_sync_jobs_status", "status"),
        Index("ix_connector_sync_jobs_created_at", "created_at"),
    )


class ConnectorDocument(Base, SoftDeleteMixin):
    """Normalized synced connector document retained for retrieval and citation."""

    __tablename__ = "connector_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_accounts.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("account_id", "external_id", name="uq_connector_documents_external"),
        Index("ix_connector_documents_account_id", "account_id"),
        Index("ix_connector_documents_source_type", "source_type"),
        Index("ix_connector_documents_synced_at", "synced_at"),
        Index(
            "ix_connector_documents_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class ScheduledAction(Base, AccountScopedMixin, SoftDeleteMixin):
    """User-facing recurring or one-off proactive action."""

    __tablename__ = "scheduled_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    schedule_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="Europe/London")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    delivery_channel: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "schedule_type IN ('once', 'daily', 'weekly', 'monthly')",
            name="ck_scheduled_actions_schedule_type",
        ),
        CheckConstraint(
            "status IN ('active', 'paused', 'archived')",
            name="ck_scheduled_actions_status",
        ),
        CheckConstraint(
            "delivery_channel IN ('web', 'telegram', 'email', 'voice')",
            name="ck_scheduled_actions_delivery_channel",
        ),
        Index("ix_scheduled_actions_user_id", "user_id"),
        Index("ix_scheduled_actions_status", "status"),
        Index("ix_scheduled_actions_next_run_at", "next_run_at"),
    )


class ScheduledActionRun(Base, AccountScopedMixin):
    """Execution history for scheduled actions."""

    __tablename__ = "scheduled_action_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scheduled_actions.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_scheduled_action_runs_status",
        ),
        Index("ix_scheduled_action_runs_action_id", "action_id"),
        Index("ix_scheduled_action_runs_triggered_at", "triggered_at"),
    )
