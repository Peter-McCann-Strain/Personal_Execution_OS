"""Add api_keys table for versioned CHAT_API_KEY rotation with dual-accept.

Phase 7.5 — replaces the single-value ``CHAT_API_KEY`` env var with a
database-backed key registry so an operator can issue a new key, keep the
old one live for a grace window, and have a nightly cron auto-promote the
successor + revoke the predecessor.

Design notes
------------

* Only the sha256 hash of the raw key is stored. This was inherited from a
  hosted-product rotation design; the public release does not ship its former
  key-rotation CLI and uses the environment bootstrap path.
* ``status`` is a CHECK-constrained enum-in-text. Using text (not a PG
  ENUM type) keeps migrations cheap — adding a fourth state later is an
  idempotent CHECK swap rather than an ``ALTER TYPE ADD VALUE``.
* The partial index ``ix_api_keys_live_status`` covers the auth hot path
  (``WHERE status IN ('active','rotating')``). Revoked history rows stay
  out of the index so the planner never touches them on every request.
* We fall back to ``settings.chat_api_key`` in the auth dependency when
  no rows exist in this table yet — required for the bootstrap case on
  a brand-new deployment (the env var is the seed).

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-04-18 15:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "b5c6d7e8f9a0"
down_revision: str | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "api_keys"
_UNIQUE_KEY_ID = "uq_api_keys_key_id"
_STATUS_CHECK = "ck_api_keys_status"
_LIVE_INDEX = "ix_api_keys_live_status"


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
            sa.Column("key_id", sa.String(length=64), nullable=False),
            sa.Column("key_hash", sa.String(length=128), nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="rotating",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "status IN ('active', 'rotating', 'revoked')",
                name=_STATUS_CHECK,
            ),
        )

    if not _has_unique_constraint(_TABLE, _UNIQUE_KEY_ID):
        op.create_unique_constraint(_UNIQUE_KEY_ID, _TABLE, ["key_id"])

    # Partial index — only ever scanned on the auth hot path. CONCURRENTLY is
    # not allowed inside a transactional migration, so we lean on
    # IF NOT EXISTS for safe re-runs against a partially-applied schema.
    if not _has_index(_TABLE, _LIVE_INDEX):
        op.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS {_LIVE_INDEX} "
                f"ON {_TABLE} (status) "
                f"WHERE status IN ('active', 'rotating')"
            )
        )


def downgrade() -> None:
    if not _has_table(_TABLE):
        return
    if _has_index(_TABLE, _LIVE_INDEX):
        op.execute(sa.text(f"DROP INDEX IF EXISTS {_LIVE_INDEX}"))
    op.drop_table(_TABLE)
