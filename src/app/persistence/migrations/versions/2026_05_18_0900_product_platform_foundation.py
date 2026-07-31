"""Add product platform tenancy, billing, audit, and data-governance tables.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-05-18 09:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "e8f9a0b1c2d3"
down_revision: str | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_OWNER_USER_ID = "00000000-0000-0000-0000-000000000010"

ACCOUNT_SCOPED_TABLES = (
    "episodes",
    "goals",
    "notes",
    "note_links",
    "agent_actions",
    "agent_trace_spans",
    "entities",
    "entity_relationships",
    "entity_mentions",
    "contacts",
    "interactions",
    "projects",
    "epics",
    "milestones",
    "tasks",
    "task_dependencies",
    "project_drafts",
    "note_canvases",
    "content_assets",
    "saved_memories",
    "connector_accounts",
    "scheduled_actions",
    "scheduled_action_runs",
    "notifications",
    "web_push_subscriptions",
    "reviews",
    "commitments",
    "decisions",
    "habits",
    "habit_logs",
    "interaction_records",
    "workflow_runs",
    "workflow_checkpoints",
    "workflow_run_steps",
    "approval_requests",
    "browser_sessions",
    "tool_receipts",
    "policy_decisions",
    "artifacts",
    "voice_calls",
    "tutorial_sessions",
)


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def _has_constraint(table_name: str, constraint_name: str) -> bool:
    if not _has_table(table_name):
        return False
    constraints = _inspector().get_foreign_keys(table_name)
    return constraint_name in {constraint.get("name") for constraint in constraints}


def _create_platform_tables() -> None:
    if not _has_table("accounts"):
        op.create_table(
            "accounts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("slug", sa.String(length=120), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
            sa.Column("plan", sa.String(length=40), nullable=False, server_default="pro"),
            sa.Column("clerk_org_id", sa.String(length=120), nullable=True),
            sa.Column("stripe_customer_id", sa.String(length=120), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("slug", name="uq_accounts_slug"),
            sa.UniqueConstraint("clerk_org_id", name="uq_accounts_clerk_org_id"),
            sa.UniqueConstraint("stripe_customer_id", name="uq_accounts_stripe_customer_id"),
        )
        op.create_index("ix_accounts_status", "accounts", ["status"])

    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("clerk_user_id", sa.String(length=120), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("display_name", sa.Text(), nullable=True),
            sa.Column("avatar_url", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("clerk_user_id", name="uq_users_clerk_user_id"),
        )
        op.create_index("ix_users_email", "users", ["email"])
        op.create_index("ix_users_status", "users", ["status"])

    if not _has_table("account_memberships"):
        op.create_table(
            "account_memberships",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("account_id", UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True), nullable=False),
            sa.Column("role", sa.String(length=30), nullable=False, server_default="owner"),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "account_id",
                "user_id",
                name="uq_account_memberships_account_user",
            ),
        )
        op.create_index("ix_account_memberships_account_id", "account_memberships", ["account_id"])
        op.create_index("ix_account_memberships_user_id", "account_memberships", ["user_id"])

    if not _has_table("subscriptions"):
        op.create_table(
            "subscriptions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("account_id", UUID(as_uuid=True), nullable=False),
            sa.Column("stripe_subscription_id", sa.String(length=120), nullable=True),
            sa.Column("stripe_price_id", sa.String(length=120), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="trialing"),
            sa.Column("plan", sa.String(length=40), nullable=False, server_default="pro"),
            sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("stripe_subscription_id", name="uq_subscriptions_stripe_id"),
        )
        op.create_index("ix_subscriptions_account_id", "subscriptions", ["account_id"])
        op.create_index("ix_subscriptions_status", "subscriptions", ["status"])

    if not _has_table("entitlements"):
        op.create_table(
            "entitlements",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("account_id", UUID(as_uuid=True), nullable=False),
            sa.Column("key", sa.String(length=120), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("quantity", sa.Float(), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("account_id", "key", name="uq_entitlements_account_key"),
        )
        op.create_index("ix_entitlements_account_id", "entitlements", ["account_id"])

    if not _has_table("audit_events"):
        op.create_table(
            "audit_events",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("account_id", UUID(as_uuid=True), nullable=True),
            sa.Column("user_id", UUID(as_uuid=True), nullable=True),
            sa.Column("event_type", sa.String(length=120), nullable=False),
            sa.Column("actor_type", sa.String(length=40), nullable=False, server_default="user"),
            sa.Column("resource_type", sa.String(length=80), nullable=True),
            sa.Column("resource_id", sa.String(length=120), nullable=True),
            sa.Column("ip_address", sa.String(length=80), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index(
            "ix_audit_events_account_created", "audit_events", ["account_id", "created_at"]
        )
        op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])

    if not _has_table("usage_metering"):
        op.create_table(
            "usage_metering",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("account_id", UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True), nullable=True),
            sa.Column("metric", sa.String(length=120), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=False, server_default="1"),
            sa.Column("source", sa.String(length=80), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index(
            "ix_usage_metering_account_metric_created",
            "usage_metering",
            ["account_id", "metric", "created_at"],
        )

    if not _has_table("data_exports"):
        op.create_table(
            "data_exports",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("account_id", UUID(as_uuid=True), nullable=False),
            sa.Column("requested_by_user_id", UUID(as_uuid=True), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="queued"),
            sa.Column("storage_url", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index(
            "ix_data_exports_account_created", "data_exports", ["account_id", "created_at"]
        )
        op.create_index("ix_data_exports_status", "data_exports", ["status"])

    if not _has_table("deletion_requests"):
        op.create_table(
            "deletion_requests",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("account_id", UUID(as_uuid=True), nullable=False),
            sa.Column("requested_by_user_id", UUID(as_uuid=True), nullable=True),
            sa.Column("scope", sa.String(length=40), nullable=False, server_default="account"),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
            sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index(
            "ix_deletion_requests_account_status",
            "deletion_requests",
            ["account_id", "status"],
        )


def _seed_first_account() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO accounts (id, name, slug, status, plan)
            VALUES (:account_id, 'Owner Account', 'owner', 'active', 'pro')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"account_id": DEFAULT_ACCOUNT_ID},
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO users (id, clerk_user_id, email, display_name, status)
            VALUES (:user_id, 'seeded-owner', 'owner@example.com', 'Owner', 'active')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"user_id": DEFAULT_OWNER_USER_ID},
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO account_memberships (id, account_id, user_id, role, status)
            VALUES (
              gen_random_uuid(),
              :account_id,
              :user_id,
              'owner',
              'active'
            )
            ON CONFLICT (account_id, user_id) DO NOTHING
            """
        ),
        {"account_id": DEFAULT_ACCOUNT_ID, "user_id": DEFAULT_OWNER_USER_ID},
    )


def _scope_existing_table(table_name: str) -> None:
    if not _has_table(table_name) or _has_column(table_name, "account_id"):
        return

    op.add_column(
        table_name,
        sa.Column(
            "account_id",
            UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ACCOUNT_ID}'::uuid"),
        ),
    )
    fk_name = f"fk_{table_name}_account_id_accounts"
    op.create_foreign_key(
        fk_name,
        table_name,
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="CASCADE",
    )
    index_name = f"ix_{table_name}_account_id"
    if not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, ["account_id"])


def upgrade() -> None:
    _create_platform_tables()
    _seed_first_account()
    for table_name in ACCOUNT_SCOPED_TABLES:
        _scope_existing_table(table_name)


def downgrade() -> None:
    for table_name in reversed(ACCOUNT_SCOPED_TABLES):
        if not _has_column(table_name, "account_id"):
            continue
        index_name = f"ix_{table_name}_account_id"
        if _has_index(table_name, index_name):
            op.drop_index(index_name, table_name=table_name)
        fk_name = f"fk_{table_name}_account_id_accounts"
        if _has_constraint(table_name, fk_name):
            op.drop_constraint(fk_name, table_name, type_="foreignkey")
        op.drop_column(table_name, "account_id")

    for table_name in (
        "deletion_requests",
        "data_exports",
        "usage_metering",
        "audit_events",
        "entitlements",
        "subscriptions",
        "account_memberships",
        "users",
        "accounts",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
