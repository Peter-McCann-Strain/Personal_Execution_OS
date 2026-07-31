"""Add idempotency_keys table for HTTP request idempotency.

Phase 7.3 — ensures POST handlers that mutate state can be safely retried by a
client without producing duplicate records. The table stores a client-supplied
``Idempotency-Key`` header value together with a SHA-256 fingerprint of the
request (method + path + body) and the eventual response. Lookups use the key
as the primary hit, the fingerprint enforces "same key must carry the same
body", and a ``recovery_point`` column lets us distinguish in-flight from
completed requests.

Rows expire after 24 hours (see ``expires_at`` default). A worker cron deletes
rows where ``expires_at < now()``.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-04-18 13:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "idempotency_keys"
_UNIQUE_KEY = "uq_idempotency_keys_key"
_ACTIVE_INDEX = "ix_idempotency_keys_active"
_EXPIRES_INDEX = "ix_idempotency_keys_expires_at"


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def _has_unique_constraint(table_name: str, constraint_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return constraint_name in {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint.get("name")
    }


def upgrade() -> None:
    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("key", sa.String(length=255), nullable=False),
            sa.Column("request_fingerprint", sa.Text(), nullable=False),
            sa.Column(
                "recovery_point",
                sa.String(length=20),
                nullable=False,
                server_default="started",
            ),
            sa.Column("response_status", sa.Integer(), nullable=True),
            sa.Column("response_body", JSONB(), nullable=True),
            sa.Column("response_headers", JSONB(), nullable=True),
            sa.Column("route", sa.String(length=255), nullable=True),
            sa.Column("method", sa.String(length=10), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "expires_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now() + interval '24 hours'"),
                nullable=False,
            ),
            sa.CheckConstraint(
                "recovery_point IN ('started', 'completed', 'failed')",
                name="ck_idempotency_keys_recovery_point",
            ),
        )

    if not _has_unique_constraint(_TABLE, _UNIQUE_KEY):
        op.create_unique_constraint(_UNIQUE_KEY, _TABLE, ["key"])

    # PostgreSQL requires every function in an index predicate to be IMMUTABLE,
    # so a partial index with ``expires_at > now()`` is invalid. Keep a regular
    # composite index for key-plus-expiry lookups; the dedicated expiry index
    # below supports cleanup of stale rows.
    if not _has_index(_TABLE, _ACTIVE_INDEX):
        op.create_index(_ACTIVE_INDEX, _TABLE, ["key", "expires_at"])

    # Full-column index for the cleanup DELETE (expires_at < now()).
    if not _has_index(_TABLE, _EXPIRES_INDEX):
        op.create_index(_EXPIRES_INDEX, _TABLE, ["expires_at"])


def downgrade() -> None:
    if not _has_table(_TABLE):
        return
    if _has_index(_TABLE, _ACTIVE_INDEX):
        op.execute(sa.text(f"DROP INDEX IF EXISTS {_ACTIVE_INDEX}"))
    if _has_index(_TABLE, _EXPIRES_INDEX):
        op.drop_index(_EXPIRES_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
