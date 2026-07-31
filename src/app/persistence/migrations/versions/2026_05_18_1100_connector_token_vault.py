"""Add encrypted connector token columns.

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-05-18 11:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a0b1c2d3e4f5"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connector_accounts", sa.Column("encrypted_refresh_token", sa.Text(), nullable=True)
    )
    op.add_column(
        "connector_accounts",
        sa.Column("token_last_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("connector_accounts", "token_last_rotated_at")
    op.drop_column("connector_accounts", "encrypted_refresh_token")
