"""Add dlq_jobs table for ARQ dead-letter queue (Phase 7.1).

Jobs that exhaust their retries or fail to deserialize are captured here
so their payload + traceback can be inspected and replayed via
``scripts/dlq_replay.py``.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-04-18 14:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "dlq_jobs"


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("job_id", sa.Text(), nullable=True),
            sa.Column("function", sa.Text(), nullable=False),
            sa.Column("args", JSONB(), nullable=True),
            sa.Column("kwargs", JSONB(), nullable=True),
            sa.Column("exception_class", sa.Text(), nullable=False),
            sa.Column("exception_message", sa.Text(), nullable=True),
            sa.Column("traceback", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "failed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("replay_result", sa.Text(), nullable=True),
        )

    if not _has_index(_TABLE, "ix_dlq_jobs_failed_at"):
        op.create_index(
            "ix_dlq_jobs_failed_at",
            _TABLE,
            ["failed_at"],
        )
    if not _has_index(_TABLE, "ix_dlq_jobs_function_failed_at"):
        op.create_index(
            "ix_dlq_jobs_function_failed_at",
            _TABLE,
            ["function", "failed_at"],
        )
    if not _has_index(_TABLE, "ix_dlq_jobs_replayed_at"):
        # Partial index — only rows still un-replayed. Lets the alert cron
        # scan cheaply (`WHERE replayed_at IS NULL AND failed_at > ...`).
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_dlq_jobs_replayed_at "
                f"ON {_TABLE} (failed_at) WHERE replayed_at IS NULL"
            )
        )


def downgrade() -> None:
    if not _has_table(_TABLE):
        return
    if _has_index(_TABLE, "ix_dlq_jobs_replayed_at"):
        op.execute(sa.text("DROP INDEX IF EXISTS ix_dlq_jobs_replayed_at"))
    if _has_index(_TABLE, "ix_dlq_jobs_function_failed_at"):
        op.drop_index("ix_dlq_jobs_function_failed_at", table_name=_TABLE)
    if _has_index(_TABLE, "ix_dlq_jobs_failed_at"):
        op.drop_index("ix_dlq_jobs_failed_at", table_name=_TABLE)
    op.drop_table(_TABLE)
