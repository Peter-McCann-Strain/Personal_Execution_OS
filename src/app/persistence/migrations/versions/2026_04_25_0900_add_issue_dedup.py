"""Add issue_dedup table for the auto-issue-from-prod feedback loop (P3.9).

The six alert workers (DLQ, schema-drift, quality, quality-gates, SLO
burn-rate, cost-ceiling) each fan out to GitHub via
:mod:`src.app.workers.github_filer`. ``issue_dedup`` maps a stable
sha256 fingerprint of each alert's identity fields to its GitHub issue
number so recurrences post comments + bump a ``count:<N>`` label rather
than spamming duplicate issues. A nightly sync job auto-resolves rows
whose ``last_seen`` is older than ``github_issue_dedup_window_days``
and drops rows whose GitHub issue has been closed by a human (so a
future recurrence re-opens a fresh issue).

Unique constraint on ``fingerprint`` enforces the single-issue-per-crash
invariant at the DB layer — the filer relies on a simple UPSERT-style
lookup by fingerprint and will otherwise race with itself under
concurrent alert cron collisions.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-04-25 09:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "c6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "issue_dedup"
_UNIQUE_FINGERPRINT = "uq_issue_dedup_fingerprint"
_LAST_SEEN_INDEX = "ix_issue_dedup_last_seen"


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
            sa.Column("fingerprint", sa.Text(), nullable=False),
            sa.Column("github_issue_number", sa.Integer(), nullable=True),
            sa.Column("github_issue_url", sa.Text(), nullable=True),
            sa.Column("category", sa.String(length=64), nullable=False),
            sa.Column(
                "first_seen",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "last_seen",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "recurrence_count",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_unique_constraint(_TABLE, _UNIQUE_FINGERPRINT):
        op.create_unique_constraint(_UNIQUE_FINGERPRINT, _TABLE, ["fingerprint"])

    # Used by the auto-resolve cron which scans for stale rows; a plain
    # btree on ``last_seen`` is enough because the table is small (one
    # row per distinct production incident fingerprint).
    if not _has_index(_TABLE, _LAST_SEEN_INDEX):
        op.create_index(_LAST_SEEN_INDEX, _TABLE, ["last_seen"])


def downgrade() -> None:
    if not _has_table(_TABLE):
        return
    if _has_index(_TABLE, _LAST_SEEN_INDEX):
        op.drop_index(_LAST_SEEN_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
