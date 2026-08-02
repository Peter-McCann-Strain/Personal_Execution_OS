"""Memory persistence models."""

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
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
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.persistence.model_defs.base import (
    AccountScopedMixin,
    Base,
    SoftDeleteMixin,
)


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
