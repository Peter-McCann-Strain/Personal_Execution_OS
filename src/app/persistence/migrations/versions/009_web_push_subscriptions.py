"""Add owner-scoped web push subscriptions for durable browser delivery.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-04-13 23:58:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def _has_unique_constraint(table_name: str, constraint_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return constraint_name in {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint.get("name")
    }


def upgrade() -> None:
    if not _has_table("web_push_subscriptions"):
        op.create_table(
            "web_push_subscriptions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("endpoint", sa.Text(), nullable=False),
            sa.Column("endpoint_hash", sa.String(length=64), nullable=False),
            sa.Column("auth_key", sa.String(length=255), nullable=False),
            sa.Column("p256dh_key", sa.String(length=255), nullable=False),
            sa.Column("expiration_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.CheckConstraint(
                "status IN ('active', 'error', 'revoked')",
                name="ck_web_push_subscriptions_status",
            ),
        )
    if not _has_unique_constraint(
        "web_push_subscriptions",
        "uq_web_push_subscriptions_user_endpoint",
    ):
        op.create_unique_constraint(
            "uq_web_push_subscriptions_user_endpoint",
            "web_push_subscriptions",
            ["user_id", "endpoint_hash"],
        )
    if not _has_index("web_push_subscriptions", "ix_web_push_subscriptions_deleted_at"):
        op.create_index(
            "ix_web_push_subscriptions_deleted_at",
            "web_push_subscriptions",
            ["deleted_at"],
        )
    if not _has_index("web_push_subscriptions", "ix_web_push_subscriptions_user_id"):
        op.create_index(
            "ix_web_push_subscriptions_user_id",
            "web_push_subscriptions",
            ["user_id"],
        )
    if not _has_index("web_push_subscriptions", "ix_web_push_subscriptions_status"):
        op.create_index(
            "ix_web_push_subscriptions_status",
            "web_push_subscriptions",
            ["status"],
        )
    if not _has_index("web_push_subscriptions", "ix_web_push_subscriptions_last_seen_at"):
        op.create_index(
            "ix_web_push_subscriptions_last_seen_at",
            "web_push_subscriptions",
            ["last_seen_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "web_push_subscriptions" in inspector.get_table_names():
        op.drop_table("web_push_subscriptions")
