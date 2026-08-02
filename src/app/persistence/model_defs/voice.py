"""Voice persistence models."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.persistence.model_defs.base import (
    AccountScopedMixin,
    Base,
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
