"""Projects persistence models."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.persistence.model_defs.base import (
    AccountScopedMixin,
    Base,
    SoftDeleteMixin,
)


class Project(Base, AccountScopedMixin, SoftDeleteMixin):
    """Shape-Up style projects."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="planning")
    appetite: Mapped[str | None] = mapped_column(String(50), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # --- Relationships ---
    epics: Mapped[list["Epic"]] = relationship(back_populates="project", passive_deletes=True)

    __table_args__ = (Index("ix_projects_status", "status"),)


class Epic(Base, AccountScopedMixin):
    """Epics within a project."""

    __tablename__ = "epics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Relationships ---
    project: Mapped["Project"] = relationship(back_populates="epics")
    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="epic", passive_deletes=True
    )

    __table_args__ = (Index("ix_epics_project_id", "project_id"),)


class Milestone(Base, AccountScopedMixin):
    """Milestones within an epic."""

    __tablename__ = "milestones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    epic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("epics.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    success_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Relationships ---
    epic: Mapped["Epic"] = relationship(back_populates="milestones")
    tasks: Mapped[list["Task"]] = relationship(back_populates="milestone", passive_deletes=True)

    __table_args__ = (Index("ix_milestones_epic_id", "epic_id"),)


class Task(Base, AccountScopedMixin):
    """Tasks within a milestone."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("milestones.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="backlog")
    estimate_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    wsjf_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    complexity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    context_tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # --- Relationships ---
    milestone: Mapped["Milestone"] = relationship(back_populates="tasks")
    outgoing_dependencies: Mapped[list["TaskDependency"]] = relationship(
        foreign_keys="[TaskDependency.task_id]",
        back_populates="task",
        passive_deletes=True,
    )
    incoming_dependencies: Mapped[list["TaskDependency"]] = relationship(
        foreign_keys="[TaskDependency.depends_on_task_id]",
        back_populates="depends_on_task",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_milestone_id", "milestone_id"),
    )


class TaskDependency(Base, AccountScopedMixin):
    """Explicit dependency edge between tasks."""

    __tablename__ = "task_dependencies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped["Task"] = relationship(
        foreign_keys=[task_id],
        back_populates="outgoing_dependencies",
    )
    depends_on_task: Mapped["Task"] = relationship(
        foreign_keys=[depends_on_task_id],
        back_populates="incoming_dependencies",
    )

    __table_args__ = (
        UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependencies_edge"),
        CheckConstraint("task_id <> depends_on_task_id", name="ck_task_dependencies_not_self"),
        Index("ix_task_dependencies_task_id", "task_id"),
        Index("ix_task_dependencies_depends_on_task_id", "depends_on_task_id"),
    )


class ProjectDraft(Base, AccountScopedMixin):
    """Draft AI-generated project breakdown awaiting operator apply."""

    __tablename__ = "project_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    applied_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_project_drafts_user_id", "user_id"),
        Index("ix_project_drafts_status", "status"),
        Index("ix_project_drafts_created_at", "created_at"),
    )


class NoteCanvas(Base, AccountScopedMixin, SoftDeleteMixin):
    """Structured note-centric board with positioned nodes and explicit edges."""

    __tablename__ = "note_canvases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    nodes: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, default=list)
    edges: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, default=list)
    viewport: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_note_canvases_primary_note_id", "primary_note_id"),
        Index("ix_note_canvases_updated_at", "updated_at"),
    )


class ContentAsset(Base, AccountScopedMixin, SoftDeleteMixin):
    """Track source packs and output assets for content-factory workflows."""

    __tablename__ = "content_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ready")
    source_pack: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    template_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_content_assets_note_id", "note_id"),
        Index("ix_content_assets_project_id", "project_id"),
        Index("ix_content_assets_asset_type", "asset_type"),
        Index("ix_content_assets_status", "status"),
        Index("ix_content_assets_updated_at", "updated_at"),
    )


class SavedMemory(Base, AccountScopedMixin, SoftDeleteMixin):
    """Explicit durable memories that the user can inspect and edit."""

    __tablename__ = "saved_memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="global")
    scope_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_captured: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "scope IN ('global', 'person', 'project')",
            name="ck_saved_memories_scope",
        ),
        CheckConstraint(
            "state IN ('active', 'snoozed', 'archived')",
            name="ck_saved_memories_state",
        ),
        Index("ix_saved_memories_user_id", "user_id"),
        Index("ix_saved_memories_scope", "scope"),
        Index("ix_saved_memories_state", "state"),
        Index("ix_saved_memories_updated_at", "updated_at"),
    )
