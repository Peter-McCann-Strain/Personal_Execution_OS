"""Add missing columns: access_count, last_accessed_at, deleted_at.

These columns existed in the ORM models and repositories but were omitted
from the initial migration. Applied via direct SQL during production setup;
this migration brings Alembic's version table into sync.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-09 00:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # episodes
    op.add_column(
        "episodes",
        sa.Column("access_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "episodes",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "episodes",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # notes
    op.add_column(
        "notes",
        sa.Column("access_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "notes",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notes",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # goals
    op.add_column(
        "goals",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # contacts
    op.add_column(
        "contacts",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # projects
    op.add_column(
        "projects",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "deleted_at")
    op.drop_column("contacts", "deleted_at")
    op.drop_column("goals", "deleted_at")
    op.drop_column("notes", "deleted_at")
    op.drop_column("notes", "last_accessed_at")
    op.drop_column("notes", "access_count")
    op.drop_column("episodes", "deleted_at")
    op.drop_column("episodes", "last_accessed_at")
    op.drop_column("episodes", "access_count")
