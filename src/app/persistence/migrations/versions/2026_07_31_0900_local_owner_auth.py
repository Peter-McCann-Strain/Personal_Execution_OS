"""Add local-owner credential and revocable browser sessions.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-31 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_owner_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("session_signing_secret", sa.Text(), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "initialized_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "password_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("id = 1", name="ck_local_owner_credentials_singleton"),
        sa.CheckConstraint(
            "failed_login_count >= 0",
            name="ck_local_owner_credentials_failed_login_count",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "local_auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ip_address", sa.String(length=80), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["local_owner_credentials.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_local_auth_sessions_expires_at",
        "local_auth_sessions",
        ["expires_at"],
    )
    op.create_index(
        "ix_local_auth_sessions_revoked_at",
        "local_auth_sessions",
        ["revoked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_local_auth_sessions_revoked_at", table_name="local_auth_sessions")
    op.drop_index("ix_local_auth_sessions_expires_at", table_name="local_auth_sessions")
    op.drop_table("local_auth_sessions")
    op.drop_table("local_owner_credentials")
