"""Planning persistence models."""

import uuid
from datetime import datetime
from typing import Any

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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.persistence.model_defs.base import (
    AccountScopedMixin,
    Base,
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
