"""Observability persistence models."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
