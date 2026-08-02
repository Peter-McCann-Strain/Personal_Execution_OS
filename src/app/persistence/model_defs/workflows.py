"""Workflows persistence models."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.persistence.model_defs.base import (
    AccountScopedMixin,
    Base,
)


class WorkflowRun(Base, AccountScopedMixin):
    """One workflow-backed request lifecycle."""

    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running")
    request_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    specialist: Mapped[str | None] = mapped_column(String(50), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    response_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_workflow_runs_user_id", "user_id"),
        Index("ix_workflow_runs_status", "status"),
        Index("ix_workflow_runs_trace_id", "trace_id"),
        Index("ix_workflow_runs_created_at", "created_at"),
    )


class WorkflowCheckpoint(Base, AccountScopedMixin):
    """Persisted pause or resume point for a workflow."""

    __tablename__ = "workflow_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    checkpoint_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_workflow_checkpoints_workflow_id", "workflow_id"),
        Index("ix_workflow_checkpoints_status", "status"),
        Index("ix_workflow_checkpoints_created_at", "created_at"),
    )


class WorkflowRunStep(Base, AccountScopedMixin):
    """User-visible step timeline for a workflow run."""

    __tablename__ = "workflow_run_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_workflow_run_steps_workflow_id", "workflow_id"),
        Index("ix_workflow_run_steps_status", "status"),
        Index("ix_workflow_run_steps_created_at", "created_at"),
    )


class ApprovalRequest(Base, AccountScopedMixin):
    """Explicit approval surfaced to the product UI."""

    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_checkpoints.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_kind: Mapped[str] = mapped_column(
        String(40), nullable=False, default="tool_confirmation"
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "request_kind IN ('tool_confirmation', 'browser_action', 'sensitive_memory')",
            name="ck_approval_requests_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_approval_requests_status",
        ),
        Index("ix_approval_requests_workflow_id", "workflow_id"),
        Index("ix_approval_requests_status", "status"),
        Index("ix_approval_requests_created_at", "created_at"),
    )


class BrowserSession(Base, AccountScopedMixin):
    """Fallback browser automation session attached to a workflow."""

    __tablename__ = "browser_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    start_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeline: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, default=list)
    screenshot_artifacts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, default=list)
    risk_flags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('planned', 'active', 'paused', 'completed', 'failed')",
            name="ck_browser_sessions_status",
        ),
        Index("ix_browser_sessions_workflow_id", "workflow_id"),
        Index("ix_browser_sessions_status", "status"),
        Index("ix_browser_sessions_created_at", "created_at"),
    )


class ArtifactRecordModel(Base, AccountScopedMixin):
    """Typed response or tool artifact retained beyond raw conversation history."""

    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scope: Mapped[str] = mapped_column(String(30), nullable=False, default="session")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_artifacts_user_id", "user_id"),
        Index("ix_artifacts_trace_id", "trace_id"),
        Index("ix_artifacts_artifact_type", "artifact_type"),
        Index("ix_artifacts_created_at", "created_at"),
    )
