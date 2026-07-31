"""Add deleted_at column to web_push_subscriptions to match SoftDeleteMixin.

The 009 migration created the table with deleted_at when the table did not yet
exist, but a prior managed PostgreSQL schema was created out-of-band (without that
column). On 2026-04-18 a verification run surfaced
``asyncpg.exceptions.UndefinedColumnError: column web_push_subscriptions.deleted_at
does not exist`` firing roughly 60x per runtime_stream tick.

This migration is idempotent — it only adds the column / partial index when
they do not already exist — so it is safe to run on environments where 009
already populated the schema correctly.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-04-18 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "web_push_subscriptions"
_COLUMN = "deleted_at"
_PARTIAL_INDEX = "ix_web_push_subscriptions_deleted_at_null"
_LEGACY_INDEX = "ix_web_push_subscriptions_deleted_at"


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if not _has_table(_TABLE):
        # Nothing to do — 009 will have created the table with the column already.
        return

    if not _has_column(_TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True),
        )

    # Partial index limits scan cost to live rows — the dominant query shape
    # for SoftDeleteMixin tables is `WHERE deleted_at IS NULL`. CONCURRENTLY is
    # not allowed inside a migration transaction, so we use a plain CREATE
    # INDEX wrapped in IF NOT EXISTS for safety.
    if not _has_index(_TABLE, _PARTIAL_INDEX):
        op.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS {_PARTIAL_INDEX} "
                f"ON {_TABLE} ({_COLUMN}) WHERE {_COLUMN} IS NULL"
            )
        )


def downgrade() -> None:
    if not _has_table(_TABLE):
        return

    if _has_index(_TABLE, _PARTIAL_INDEX):
        op.execute(sa.text(f"DROP INDEX IF EXISTS {_PARTIAL_INDEX}"))

    # Only drop the column if no legacy full-column index references it; if a
    # prior migration created `ix_web_push_subscriptions_deleted_at` we leave
    # it in place since the column is needed by the SoftDeleteMixin contract.
    if _has_column(_TABLE, _COLUMN) and not _has_index(_TABLE, _LEGACY_INDEX):
        op.drop_column(_TABLE, _COLUMN)
