"""Operations persistence models."""

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.persistence.model_defs.base import (
    Base,
)


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
