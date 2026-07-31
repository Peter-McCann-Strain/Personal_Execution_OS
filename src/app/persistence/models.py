"""SQLAlchemy ORM models for core tables (Phase 1)."""

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class SoftDeleteMixin:
    """Mixin that adds soft-delete support via a deleted_at timestamp.

    Models using this mixin are not physically deleted — instead, deleted_at
    is set to the current UTC time. Query-level filtering should be applied
    by the caller or via repository helpers.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )

    def soft_delete(self) -> None:
        """Mark this record as soft-deleted."""
        from datetime import UTC

        self.deleted_at = datetime.now(UTC)

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.deleted_at = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


DEFAULT_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_OWNER_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


class AccountScopedMixin:
    """Mixin for customer-owned rows during the SaaS tenancy migration.

    The default account keeps existing single-user write paths working while
    routes and repositories are progressively moved to explicit principals.
    """

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        default=DEFAULT_ACCOUNT_ID,
        server_default=text(f"'{DEFAULT_ACCOUNT_ID}'::uuid"),
        index=True,
    )


def not_deleted(model_class: type) -> Any:
    """Filter condition for excluding soft-deleted rows."""
    return model_class.deleted_at.is_(None)


# ---------------------------------------------------------------------------
# Product platform / tenancy models
# ---------------------------------------------------------------------------


class Account(Base):
    """Local data-ownership boundary for one installation account."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    plan: Mapped[str] = mapped_column(String(40), nullable=False, default="community")
    # Legacy column names are retained at the database boundary so existing
    # installations migrate without data loss; runtime names are neutral.
    external_org_subject: Mapped[str | None] = mapped_column(
        "clerk_org_id", String(120), nullable=True
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_accounts_slug"),
        UniqueConstraint("clerk_org_id", name="uq_accounts_clerk_org_id"),
        Index("ix_accounts_status", "status"),
    )


class User(Base):
    """Application user with an optional provider-neutral external subject."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_subject: Mapped[str] = mapped_column("clerk_user_id", String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("clerk_user_id", name="uq_users_clerk_user_id"),
        Index("ix_users_email", "email"),
        Index("ix_users_status", "status"),
    )


class AccountMembership(Base):
    """Role binding between users and accounts."""

    __tablename__ = "account_memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="owner")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("account_id", "user_id", name="uq_account_memberships_account_user"),
        Index("ix_account_memberships_account_id", "account_id"),
        Index("ix_account_memberships_user_id", "user_id"),
    )


class LocalOwnerCredential(Base):
    """Singleton password credential and cookie-signing secret for self-hosting."""

    __tablename__ = "local_owner_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    session_signing_secret: Mapped[str] = mapped_column(Text, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    initialized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    password_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_local_owner_credentials_singleton"),
        CheckConstraint(
            "failed_login_count >= 0",
            name="ck_local_owner_credentials_failed_login_count",
        ),
    )


class LocalAuthSession(Base):
    """Revocable server-side browser session for the local owner."""

    __tablename__ = "local_auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("local_owner_credentials.id", ondelete="CASCADE"),
        nullable=False,
        default=1,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ip_address: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_local_auth_sessions_expires_at", "expires_at"),
        Index("ix_local_auth_sessions_revoked_at", "revoked_at"),
    )


class Entitlement(Base):
    """Account-level feature/usage entitlement."""

    __tablename__ = "entitlements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("account_id", "key", name="uq_entitlements_account_key"),
        Index("ix_entitlements_account_id", "account_id"),
    )


class AuditEvent(Base):
    """Audit event for account, auth, connector, and data actions."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False, default="user")
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_audit_events_account_created", "account_id", "created_at"),
        Index("ix_audit_events_event_type", "event_type"),
    )


class UsageMetering(Base):
    """Per-account usage events for entitlements and cost controls."""

    __tablename__ = "usage_metering"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metric: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_usage_metering_account_metric_created", "account_id", "metric", "created_at"),
    )


class DataExport(Base):
    """Account data export request lifecycle."""

    __tablename__ = "data_exports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_data_exports_account_created", "account_id", "created_at"),
        Index("ix_data_exports_status", "status"),
    )


class DeletionRequest(Base):
    """Account/user deletion request and retention workflow."""

    __tablename__ = "deletion_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(40), nullable=False, default="account")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)

    __table_args__ = (Index("ix_deletion_requests_account_status", "account_id", "status"),)


class Episode(Base, AccountScopedMixin, SoftDeleteMixin):
    """Diary entries, captures, voice memos, interactions."""

    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    episode_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    para_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mood_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    people_mentioned: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
        nullable=True,
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    access_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Relationships ---
    entity_mentions: Mapped[list["EntityMention"]] = relationship(
        back_populates="episode", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(
            "para_category IN ('project', 'area', 'resource', 'archive') OR para_category IS NULL",
            name="ck_episodes_para_category",
        ),
        Index("ix_episodes_created_at", "created_at"),
        Index("ix_episodes_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_episodes_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Goal(Base, AccountScopedMixin, SoftDeleteMixin):
    """Goals hierarchy — life, quarterly, monthly, weekly."""

    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    goal_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id", ondelete="CASCADE"), nullable=True
    )
    priority: Mapped[int] = mapped_column(default=5)
    status: Mapped[str] = mapped_column(String(20), default="active")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # --- Relationships ---
    children: Mapped[list["Goal"]] = relationship(
        "Goal", back_populates="parent", passive_deletes=True
    )
    parent: Mapped["Goal | None"] = relationship(
        "Goal", back_populates="children", remote_side="[Goal.id]"
    )

    __table_args__ = (
        Index("ix_goals_status", "status"),
        Index("ix_goals_parent_id", "parent_id"),
        Index("ix_goals_priority", "priority"),
    )


class Note(Base, AccountScopedMixin, SoftDeleteMixin):
    """Zettelkasten atomic notes."""

    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str | None] = mapped_column(String(180), nullable=True)
    aliases: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    daily_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    frontmatter: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    note_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    para_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    progressive_summary_level: Mapped[int] = mapped_column(default=1)
    executive_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    access_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Relationships ---
    outgoing_links: Mapped[list["NoteLink"]] = relationship(
        foreign_keys="[NoteLink.source_note_id]",
        back_populates="source_note",
        passive_deletes=True,
    )
    incoming_links: Mapped[list["NoteLink"]] = relationship(
        foreign_keys="[NoteLink.target_note_id]",
        back_populates="target_note",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "para_category IN ('project', 'area', 'resource', 'archive') OR para_category IS NULL",
            name="ck_notes_para_category",
        ),
        CheckConstraint(
            "kind IN ('note', 'daily', 'moc') OR kind IS NULL",
            name="ck_notes_kind",
        ),
        Index("ix_notes_note_type", "note_type"),
        Index("ix_notes_slug", "slug", unique=True),
        Index("ix_notes_kind", "kind"),
        Index("ix_notes_daily_date", "daily_date"),
        Index("ix_notes_updated_at", "updated_at"),
        Index(
            "ix_notes_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class NoteLink(Base, AccountScopedMixin):
    """Connections between notes — Zettelkasten links."""

    __tablename__ = "note_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    target_note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    link_type: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    origin: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    link_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    auto_discovered: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Relationships ---
    source_note: Mapped["Note"] = relationship(
        foreign_keys=[source_note_id], back_populates="outgoing_links"
    )
    target_note: Mapped["Note"] = relationship(
        foreign_keys=[target_note_id], back_populates="incoming_links"
    )

    __table_args__ = (
        UniqueConstraint(
            "source_note_id",
            "target_note_id",
            name="uq_note_link",
        ),
        CheckConstraint(
            "link_type IN ('wiki', 'manual', 'semantic')",
            name="ck_note_links_link_type",
        ),
        CheckConstraint(
            "origin IN ('wiki', 'manual', 'semantic')",
            name="ck_note_links_origin",
        ),
        Index("ix_note_links_source_note_id", "source_note_id"),
        Index("ix_note_links_target_note_id", "target_note_id"),
    )


class AgentAction(Base, AccountScopedMixin):
    """Observability — logs every LLM call with model, tokens, cost, latency."""

    __tablename__ = "agent_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    action_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_agent_actions_agent_name", "agent_name"),
        Index("ix_agent_actions_created_at", "created_at"),
    )


class AgentTraceSpan(Base, AccountScopedMixin):
    """Trace-first runtime span tree for one request lifecycle."""

    __tablename__ = "agent_trace_spans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    span_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    specialist: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cache_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_agent_trace_spans_trace_id", "trace_id"),
        Index("ix_agent_trace_spans_span_kind", "span_kind"),
        Index("ix_agent_trace_spans_created_at", "created_at"),
    )


# ---------------------------------------------------------------------------
# Knowledge Graph models
# ---------------------------------------------------------------------------


class Entity(Base, AccountScopedMixin):
    """Lightweight knowledge graph — named entities extracted from episodes."""

    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    canonical_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    mention_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Relationships ---
    mentions: Mapped[list["EntityMention"]] = relationship(
        back_populates="entity", passive_deletes=True
    )
    outgoing_relationships: Mapped[list["EntityRelationship"]] = relationship(
        foreign_keys="[EntityRelationship.source_entity_id]",
        back_populates="source_entity",
        passive_deletes=True,
    )
    incoming_relationships: Mapped[list["EntityRelationship"]] = relationship(
        foreign_keys="[EntityRelationship.target_entity_id]",
        back_populates="target_entity",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_entities_entity_type", "entity_type"),
        Index(
            "ix_entities_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )


class EntityRelationship(Base, AccountScopedMixin):
    """Edges in the knowledge graph between entities."""

    __tablename__ = "entity_relationships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Relationships ---
    source_entity: Mapped["Entity"] = relationship(
        foreign_keys=[source_entity_id], back_populates="outgoing_relationships"
    )
    target_entity: Mapped["Entity"] = relationship(
        foreign_keys=[target_entity_id], back_populates="incoming_relationships"
    )

    __table_args__ = (
        UniqueConstraint(
            "source_entity_id",
            "target_entity_id",
            "relationship_type",
            "valid_from",
            name="uq_entity_relationship",
        ),
        Index("ix_entity_relationships_source_entity_id", "source_entity_id"),
        Index("ix_entity_relationships_target_entity_id", "target_entity_id"),
    )


class EntityMention(Base, AccountScopedMixin):
    """Links an entity to the episode where it was mentioned."""

    __tablename__ = "entity_mentions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    context_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    mentioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Relationships ---
    entity: Mapped["Entity"] = relationship(back_populates="mentions")
    episode: Mapped["Episode"] = relationship(back_populates="entity_mentions")

    __table_args__ = (
        UniqueConstraint(
            "entity_id",
            "episode_id",
            name="uq_entity_mention",
        ),
        Index("ix_entity_mentions_entity_id", "entity_id"),
        Index("ix_entity_mentions_episode_id", "episode_id"),
    )


# ---------------------------------------------------------------------------
# CRM models
# ---------------------------------------------------------------------------


class Contact(Base, AccountScopedMixin, SoftDeleteMixin):
    """CRM contacts with relationship health tracking."""

    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    how_we_met: Mapped[str | None] = mapped_column(Text, nullable=True)
    interaction_frequency_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relationship_score: Mapped[float] = mapped_column(Float, default=50.0)
    last_interaction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # --- Relationships ---
    interactions: Mapped[list["Interaction"]] = relationship(
        back_populates="contact", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_contacts_relationship_score", "relationship_score"),
        Index("ix_contacts_last_interaction_at", "last_interaction_at"),
    )


class Interaction(Base, AccountScopedMixin):
    """Logged interactions with contacts."""

    __tablename__ = "interactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    interaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), default="outgoing")
    channel: Mapped[str] = mapped_column(String(50), default="manual")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    topics: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Relationships ---
    contact: Mapped["Contact"] = relationship(back_populates="interactions")

    __table_args__ = (Index("ix_interactions_contact_id", "contact_id"),)


# ---------------------------------------------------------------------------
# Project management models
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Notification and review models
# ---------------------------------------------------------------------------


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


class Review(Base, AccountScopedMixin):
    """Stored weekly/quarterly reviews."""

    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_type: Mapped[str] = mapped_column(String(20), nullable=False, default="weekly")
    period: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_reviews_review_type", "review_type"),
        Index("ix_reviews_created_at", "created_at"),
    )


# ---------------------------------------------------------------------------
# Commitments model
# ---------------------------------------------------------------------------


class Commitment(Base, AccountScopedMixin):
    """Tracked promises and follow-ups extracted from conversations."""

    __tablename__ = "commitments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    verbatim_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_action: Mapped[str] = mapped_column(Text, nullable=False)
    who_committed: Mapped[str | None] = mapped_column(String(100), nullable=True)
    who_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temporal_expression_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    temporal_normalized: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    commitment_type: Mapped[str] = mapped_column(String(30), default="promise")
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(20), default="detected")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_commitments_status", "status"),
        Index("ix_commitments_created_at", "created_at"),
        Index("ix_commitments_temporal_normalized", "temporal_normalized"),
    )


# ---------------------------------------------------------------------------
# Decision journal model
# ---------------------------------------------------------------------------


class Decision(Base, AccountScopedMixin):
    """Decision journal — track major decisions with reasoning and outcomes."""

    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    options_considered: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    decision_made: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_rating: Mapped[float | None] = mapped_column(Float, nullable=True)  # 1-10
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    review_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # pending_review | reviewed | archived
    status: Mapped[str] = mapped_column(String(20), default="pending_review")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_decisions_status", "status"),
        Index("ix_decisions_review_date", "review_date"),
        Index("ix_decisions_created_at", "created_at"),
    )


# ---------------------------------------------------------------------------
# Habit tracking models
# ---------------------------------------------------------------------------


class Habit(Base, AccountScopedMixin):
    """Tracked habits with streak monitoring."""

    __tablename__ = "habits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    frequency: Mapped[str] = mapped_column(String(20), default="daily")  # daily, weekly, custom
    frequency_days: Mapped[int] = mapped_column(Integer, default=1)  # every N days
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
    total_completions: Mapped[int] = mapped_column(Integer, default=0)
    last_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(default=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # --- Relationships ---
    logs: Mapped[list["HabitLog"]] = relationship(back_populates="habit", passive_deletes=True)

    __table_args__ = (
        Index("ix_habits_active", "active"),
        Index("ix_habits_name", "name"),
    )


class HabitLog(Base, AccountScopedMixin):
    """Individual habit completion records."""

    __tablename__ = "habit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("habits.id", ondelete="CASCADE"), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="manual")  # manual, auto_detected

    # --- Relationships ---
    habit: Mapped["Habit"] = relationship(back_populates="logs")

    __table_args__ = (
        Index("ix_habit_logs_habit_id", "habit_id"),
        Index("ix_habit_logs_completed_at", "completed_at"),
    )


# ---------------------------------------------------------------------------
# Evaluation / self-improvement models
# ---------------------------------------------------------------------------


class InteractionRecord(Base, AccountScopedMixin):
    """Atomic evaluation unit — one per process_message lifecycle.

    Captures the full request→response pipeline: timing, routing, specialist
    output, evaluator-optimizer decision, auto-judge scores, and user feedback.
    This powers the entire self-improvement loop.
    """

    __tablename__ = "interaction_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # --- Request ---
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # telegram, cli, voice

    # --- Routing ---
    intent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    specialist: Mapped[str] = mapped_column(String(50), nullable=False)
    routing_confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # --- Response ---
    response_content: Mapped[str] = mapped_column(Text, nullable=False)
    response_agent: Mapped[str] = mapped_column(String(50), nullable=False)

    # --- Evaluator-optimizer ---
    optimizer_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    optimizer_issue: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Timing ---
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- Auto-judge scores (populated by worker, NULL until scored) ---
    eval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    score_relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_actionability: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_tone: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_conciseness: Mapped[float | None] = mapped_column(Float, nullable=True)
    auto_judge_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- User feedback (populated via Telegram inline keyboard) ---
    feedback_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Deep evaluation (populated by Claude Code via scripts/evaluate.py store) ---
    deep_scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    deep_eval_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Prompt version (tracks which prompt version produced this response) ---
    prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --- Trace / response observability ---
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    workflow_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    response_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quality_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    channel_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "eval_status IN ('pending', 'auto_scored', 'deep_scored', 'skipped')",
            name="ck_interaction_records_eval_status",
        ),
        CheckConstraint(
            "feedback_rating IN ('thumbs_up', 'thumbs_down') OR feedback_rating IS NULL",
            name="ck_interaction_records_feedback_rating",
        ),
        Index("ix_interaction_records_eval_status", "eval_status"),
        Index("ix_interaction_records_specialist", "specialist"),
        Index("ix_interaction_records_created_at", "created_at"),
        Index("ix_interaction_records_user_id", "user_id"),
        Index("ix_interaction_records_trace_id", "trace_id"),
        Index("ix_interaction_records_workflow_id", "workflow_id"),
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


class ToolReceipt(Base, AccountScopedMixin):
    """Idempotent record of one executed tool call."""

    __tablename__ = "tool_receipts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    interaction_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(150), nullable=False)
    server_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mutation_class: Mapped[str] = mapped_column(String(30), nullable=False, default="read_only")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    argument_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    audit_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_tool_receipts_idempotency_key"),
        Index("ix_tool_receipts_trace_id", "trace_id"),
        Index("ix_tool_receipts_tool_name", "tool_name"),
        Index("ix_tool_receipts_created_at", "created_at"),
    )


class PolicyDecisionRecord(Base, AccountScopedMixin):
    """Audit record for runtime policy decisions."""

    __tablename__ = "policy_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    specialist: Mapped[str | None] = mapped_column(String(50), nullable=True)
    policy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    subject_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_policy_decisions_trace_id", "trace_id"),
        Index("ix_policy_decisions_policy_name", "policy_name"),
        Index("ix_policy_decisions_created_at", "created_at"),
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


class VoiceCall(Base, AccountScopedMixin):
    """Outbound or inbound voice call lifecycle tracked across providers and ingestion."""

    __tablename__ = "voice_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    call_sid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="outbound")
    channel: Mapped[str] = mapped_column(String(30), nullable=False, default="pstn_outbound")
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, default="general_assistant")
    trigger_source: Mapped[str] = mapped_column(String(40), nullable=False)
    call_status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    processing_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    target_phone_number: Mapped[str] = mapped_column(String(40), nullable=False)
    from_phone_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_secs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    config_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provider_route: Mapped[str | None] = mapped_column(String(80), nullable=True)
    connect_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_voice_calls_conversation_id"),
        UniqueConstraint("call_sid", name="uq_voice_calls_call_sid"),
        CheckConstraint(
            "direction IN ('outbound', 'inbound')",
            name="ck_voice_calls_direction",
        ),
        CheckConstraint(
            "channel IN ('pstn_outbound', 'pstn_inbound', 'app_realtime')",
            name="ck_voice_calls_channel",
        ),
        CheckConstraint(
            "purpose IN ('scheduled_reflection', 'on_demand_reflection', 'general_assistant')",
            name="ck_voice_calls_purpose",
        ),
        CheckConstraint(
            "trigger_source IN ('manual_test', 'scheduled_reflection', "
            "'on_demand_reflection', 'inbound_call', 'app_session')",
            name="ck_voice_calls_trigger_source",
        ),
        CheckConstraint(
            "call_status IN ('queued', 'initiated', 'completed', 'failed', 'no_answer', 'busy')",
            name="ck_voice_calls_call_status",
        ),
        CheckConstraint(
            "processing_status IN ('pending', 'transcript_received', 'ingested', 'failed')",
            name="ck_voice_calls_processing_status",
        ),
        Index("ix_voice_calls_created_at", "created_at"),
        Index("ix_voice_calls_channel", "channel"),
        Index("ix_voice_calls_purpose", "purpose"),
        Index("ix_voice_calls_call_status", "call_status"),
        Index("ix_voice_calls_processing_status", "processing_status"),
        Index("ix_voice_calls_target_phone_number", "target_phone_number"),
    )


class TutorialSession(Base, AccountScopedMixin):
    """Socratic tutorial session — transcript, analysis, and growth tracking."""

    __tablename__ = "tutorial_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    work_type: Mapped[str] = mapped_column(String(50), default="other")
    submitted_work: Mapped[str] = mapped_column(Text, nullable=False)

    # Tutorial state
    phase: Mapped[str] = mapped_column(String(50), default="submitted")
    propositions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    preparation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Dialogue transcript (full, with hidden reasoning)
    transcript: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    assessor_log: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    # Post-tutorial analysis
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Growth metrics
    bloom_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bloom_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    turn_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speaking_ratio_student_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    knowledge_gaps_found: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knowledge_gaps_addressed: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_tutorial_sessions_user_id", "user_id"),
        Index("ix_tutorial_sessions_phase", "phase"),
        Index("ix_tutorial_sessions_created_at", "created_at"),
        CheckConstraint(
            "phase IN ('submitted', 'preparing', 'ready', 'opening', 'dialogue', "
            "'closing', 'analysing', 'complete')",
            name="ck_tutorial_sessions_phase",
        ),
    )


# ---------------------------------------------------------------------------
# Idempotency keys (Phase 7.3)
# ---------------------------------------------------------------------------


class IdempotencyKey(Base):
    """HTTP idempotency record for mutating POST requests.

    A client that retries a request (network blip, webhook redelivery, UI
    double-click) resends the same ``Idempotency-Key`` header; if the
    fingerprint matches and the prior attempt completed, we return the cached
    response verbatim instead of re-running the handler. A fingerprint mismatch
    returns 409 so a misuse of the same key never yields a stale response.
    """

    __tablename__ = "idempotency_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    recovery_point: Mapped[str] = mapped_column(
        String(20), nullable=False, default="started", server_default="started"
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    response_headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    route: Mapped[str | None] = mapped_column(String(255), nullable=True)
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now() + interval '24 hours'"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("key", name="uq_idempotency_keys_key"),
        CheckConstraint(
            "recovery_point IN ('started', 'completed', 'failed')",
            name="ck_idempotency_keys_recovery_point",
        ),
        Index("ix_idempotency_keys_active", "key", "expires_at"),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
    )


# ---------------------------------------------------------------------------
# DLQ (dead-letter queue) for ARQ background jobs (Phase 7.1)
# ---------------------------------------------------------------------------


class DLQJob(Base):
    """One captured ARQ job that exhausted retries or failed to deserialize.

    Written best-effort from ``src.app.workers.agent_tasks`` when a background
    task hits its max_tries ceiling, and from the poison-pill guard when a
    payload cannot be deserialized. Replayed via ``scripts/dlq_replay.py``.
    """

    __tablename__ = "dlq_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    function: Mapped[str] = mapped_column(Text, nullable=False)
    args: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    kwargs: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    exception_class: Mapped[str] = mapped_column(Text, nullable=False)
    exception_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replay_result: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_dlq_jobs_failed_at", "failed_at"),
        Index("ix_dlq_jobs_function_failed_at", "function", "failed_at"),
    )


# ---------------------------------------------------------------------------
# Issue dedup for the auto-issue-from-prod feedback loop (Phase 3.9)
# ---------------------------------------------------------------------------


class IssueDedup(Base):
    """Mapping from an alert fingerprint to the GitHub issue it spawned.

    Written by :mod:`src.app.workers.github_filer` when an alert worker
    decides to fan out to GitHub. The unique ``fingerprint`` column
    enforces one-issue-per-recurring-crash — subsequent occurrences
    increment ``recurrence_count`` and post a comment rather than
    creating a duplicate issue. ``resolved_at`` is set by the nightly
    sync cron when either (a) we proactively close an idle issue, or
    (b) we observe a human-closed issue and wipe the row entirely so a
    future recurrence opens a fresh one.
    """

    __tablename__ = "issue_dedup"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    github_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    github_issue_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    recurrence_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_issue_dedup_fingerprint"),
        Index("ix_issue_dedup_last_seen", "last_seen"),
    )
