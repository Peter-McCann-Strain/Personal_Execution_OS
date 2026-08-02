"""People persistence models."""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.persistence.model_defs.base import (
    AccountScopedMixin,
    Base,
    SoftDeleteMixin,
)


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
