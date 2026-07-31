"""Add connector OAuth state table.

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-05-18 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b1c2d3e4f5a6"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector_oauth_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("connector_type", sa.String(length=40), nullable=False),
        sa.Column("state_hash", sa.String(length=96), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "connector_type IN ('gmail', 'google_calendar', 'google_drive')",
            name="ck_connector_oauth_states_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'consumed', 'failed')",
            name="ck_connector_oauth_states_status",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index(
        "ix_connector_oauth_states_account_id",
        "connector_oauth_states",
        ["account_id"],
    )
    op.create_index("ix_connector_oauth_states_user_id", "connector_oauth_states", ["user_id"])
    op.create_index(
        "ix_connector_oauth_states_state_hash",
        "connector_oauth_states",
        ["state_hash"],
    )
    op.create_index(
        "ix_connector_oauth_states_expires_at",
        "connector_oauth_states",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_connector_oauth_states_expires_at", table_name="connector_oauth_states")
    op.drop_index("ix_connector_oauth_states_state_hash", table_name="connector_oauth_states")
    op.drop_index("ix_connector_oauth_states_user_id", table_name="connector_oauth_states")
    op.drop_index("ix_connector_oauth_states_account_id", table_name="connector_oauth_states")
    op.drop_table("connector_oauth_states")
