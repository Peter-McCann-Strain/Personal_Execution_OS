"""Drop api_keys table — reverts Phase 7.5 rotation machinery.

The versioned ``api_keys`` table and the SOPS/age decrypt ceremony turned
out to be overkill for a single-user app. This migration removes the
table; authentication falls back to the single ``CHAT_API_KEY`` env var
compared via ``hmac.compare_digest`` in ``src.app.api.deps.verify_api_key``.

``downgrade()`` recreates the table verbatim from the original
``2026_04_18_1500_add_api_keys_table.py`` migration so the schema stays
reversible if we ever want to re-introduce versioned keys.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-04-24 17:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "c6d7e8f9a0b1"
down_revision: str | None = "b5c6d7e8f9a0"
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
        return
    if _has_index(_TABLE, _LIVE_INDEX):
        op.execute(sa.text(f"DROP INDEX IF EXISTS {_LIVE_INDEX}"))
    op.drop_table(_TABLE)


def downgrade() -> None:
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

    if not _has_index(_TABLE, _LIVE_INDEX):
        op.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS {_LIVE_INDEX} "
                f"ON {_TABLE} (status) "
                f"WHERE status IN ('active', 'rotating')"
            )
        )
