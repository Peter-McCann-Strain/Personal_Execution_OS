"""Add world-class control-plane tables for runs, approvals, scheduling, memory, and connectors.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-13 22:45:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
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
        constraint["name"] for constraint in inspector.get_unique_constraints(table_name)
    }


def upgrade() -> None:
    if not _has_table("workflow_run_steps"):
        op.create_table(
            "workflow_run_steps",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("workflow_id", UUID(as_uuid=True), nullable=False),
            sa.Column("step_type", sa.String(length=50), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("details", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        )
    if not _has_index("workflow_run_steps", "ix_workflow_run_steps_workflow_id"):
        op.create_index("ix_workflow_run_steps_workflow_id", "workflow_run_steps", ["workflow_id"])
    if not _has_index("workflow_run_steps", "ix_workflow_run_steps_status"):
        op.create_index("ix_workflow_run_steps_status", "workflow_run_steps", ["status"])
    if not _has_index("workflow_run_steps", "ix_workflow_run_steps_created_at"):
        op.create_index("ix_workflow_run_steps_created_at", "workflow_run_steps", ["created_at"])

    if not _has_table("approval_requests"):
        op.create_table(
            "approval_requests",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("workflow_id", UUID(as_uuid=True), nullable=False),
            sa.Column("checkpoint_id", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "request_kind",
                sa.String(length=40),
                nullable=False,
                server_default="tool_confirmation",
            ),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("payload", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["checkpoint_id"], ["workflow_checkpoints.id"], ondelete="SET NULL"
            ),
            sa.CheckConstraint(
                "request_kind IN ('tool_confirmation', 'browser_action', 'sensitive_memory')",
                name="ck_approval_requests_kind",
            ),
            sa.CheckConstraint(
                "status IN ('pending', 'approved', 'rejected', 'cancelled')",
                name="ck_approval_requests_status",
            ),
        )
    if not _has_index("approval_requests", "ix_approval_requests_workflow_id"):
        op.create_index("ix_approval_requests_workflow_id", "approval_requests", ["workflow_id"])
    if not _has_index("approval_requests", "ix_approval_requests_status"):
        op.create_index("ix_approval_requests_status", "approval_requests", ["status"])
    if not _has_index("approval_requests", "ix_approval_requests_created_at"):
        op.create_index("ix_approval_requests_created_at", "approval_requests", ["created_at"])

    if not _has_table("browser_sessions"):
        op.create_table(
            "browser_sessions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("workflow_id", UUID(as_uuid=True), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="planned"),
            sa.Column("start_url", sa.Text(), nullable=True),
            sa.Column("current_url", sa.Text(), nullable=True),
            sa.Column("timeline", JSONB(), nullable=True),
            sa.Column("screenshot_artifacts", JSONB(), nullable=True),
            sa.Column("risk_flags", ARRAY(sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.id"], ondelete="CASCADE"),
            sa.CheckConstraint(
                "status IN ('planned', 'active', 'paused', 'completed', 'failed')",
                name="ck_browser_sessions_status",
            ),
        )
    if not _has_index("browser_sessions", "ix_browser_sessions_workflow_id"):
        op.create_index("ix_browser_sessions_workflow_id", "browser_sessions", ["workflow_id"])
    if not _has_index("browser_sessions", "ix_browser_sessions_status"):
        op.create_index("ix_browser_sessions_status", "browser_sessions", ["status"])
    if not _has_index("browser_sessions", "ix_browser_sessions_created_at"):
        op.create_index("ix_browser_sessions_created_at", "browser_sessions", ["created_at"])

    if not _has_table("saved_memories"):
        op.create_table(
            "saved_memories",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("scope", sa.String(length=20), nullable=False, server_default="global"),
            sa.Column("scope_key", sa.String(length=120), nullable=True),
            sa.Column("state", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("source_type", sa.String(length=50), nullable=True),
            sa.Column("source_id", sa.String(length=120), nullable=True),
            sa.Column("provenance", JSONB(), nullable=True),
            sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column(
                "auto_captured", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.CheckConstraint(
                "scope IN ('global', 'person', 'project')",
                name="ck_saved_memories_scope",
            ),
            sa.CheckConstraint(
                "state IN ('active', 'snoozed', 'archived')",
                name="ck_saved_memories_state",
            ),
        )
    if not _has_index("saved_memories", "ix_saved_memories_user_id"):
        op.create_index("ix_saved_memories_user_id", "saved_memories", ["user_id"])
    if not _has_index("saved_memories", "ix_saved_memories_scope"):
        op.create_index("ix_saved_memories_scope", "saved_memories", ["scope"])
    if not _has_index("saved_memories", "ix_saved_memories_state"):
        op.create_index("ix_saved_memories_state", "saved_memories", ["state"])
    if not _has_index("saved_memories", "ix_saved_memories_updated_at"):
        op.create_index("ix_saved_memories_updated_at", "saved_memories", ["updated_at"])

    if not _has_table("connector_accounts"):
        op.create_table(
            "connector_accounts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("connector_type", sa.String(length=40), nullable=False),
            sa.Column("display_name", sa.String(length=160), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="connected"),
            sa.Column("scopes", ARRAY(sa.Text()), nullable=True),
            sa.Column("auto_use", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column(
                "background_access",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "sync_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.CheckConstraint(
                "connector_type IN ('gmail', 'google_calendar', 'google_drive', 'tavily')",
                name="ck_connector_accounts_type",
            ),
            sa.CheckConstraint(
                "status IN ('connected', 'disconnected', 'error')",
                name="ck_connector_accounts_status",
            ),
        )
    if not _has_index("connector_accounts", "ix_connector_accounts_user_id"):
        op.create_index("ix_connector_accounts_user_id", "connector_accounts", ["user_id"])
    if not _has_index("connector_accounts", "ix_connector_accounts_connector_type"):
        op.create_index(
            "ix_connector_accounts_connector_type",
            "connector_accounts",
            ["connector_type"],
        )
    if not _has_index("connector_accounts", "ix_connector_accounts_status"):
        op.create_index("ix_connector_accounts_status", "connector_accounts", ["status"])

    if not _has_table("connector_sync_jobs"):
        op.create_table(
            "connector_sync_jobs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("account_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "sync_type", sa.String(length=30), nullable=False, server_default="incremental"
            ),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
            sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["account_id"], ["connector_accounts.id"], ondelete="CASCADE"),
            sa.CheckConstraint(
                "sync_type IN ('incremental', 'full', 'reindex')",
                name="ck_connector_sync_jobs_sync_type",
            ),
            sa.CheckConstraint(
                "status IN ('queued', 'running', 'completed', 'failed')",
                name="ck_connector_sync_jobs_status",
            ),
        )
    if not _has_index("connector_sync_jobs", "ix_connector_sync_jobs_account_id"):
        op.create_index("ix_connector_sync_jobs_account_id", "connector_sync_jobs", ["account_id"])
    if not _has_index("connector_sync_jobs", "ix_connector_sync_jobs_status"):
        op.create_index("ix_connector_sync_jobs_status", "connector_sync_jobs", ["status"])
    if not _has_index("connector_sync_jobs", "ix_connector_sync_jobs_created_at"):
        op.create_index("ix_connector_sync_jobs_created_at", "connector_sync_jobs", ["created_at"])

    if not _has_table("connector_documents"):
        op.create_table(
            "connector_documents",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("account_id", UUID(as_uuid=True), nullable=False),
            sa.Column("external_id", sa.String(length=200), nullable=False),
            sa.Column("source_type", sa.String(length=50), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column("embedding", Vector(768), nullable=True),
            sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["account_id"], ["connector_accounts.id"], ondelete="CASCADE"),
        )
    if not _has_unique_constraint("connector_documents", "uq_connector_documents_external"):
        op.create_unique_constraint(
            "uq_connector_documents_external",
            "connector_documents",
            ["account_id", "external_id"],
        )
    if not _has_index("connector_documents", "ix_connector_documents_account_id"):
        op.create_index("ix_connector_documents_account_id", "connector_documents", ["account_id"])
    if not _has_index("connector_documents", "ix_connector_documents_source_type"):
        op.create_index(
            "ix_connector_documents_source_type", "connector_documents", ["source_type"]
        )
    if not _has_index("connector_documents", "ix_connector_documents_synced_at"):
        op.create_index("ix_connector_documents_synced_at", "connector_documents", ["synced_at"])
    if not _has_index("connector_documents", "ix_connector_documents_embedding_hnsw"):
        op.create_index(
            "ix_connector_documents_embedding_hnsw",
            "connector_documents",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )

    if not _has_table("scheduled_actions"):
        op.create_table(
            "scheduled_actions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("schedule_type", sa.String(length=20), nullable=False),
            sa.Column("schedule_config", JSONB(), nullable=True),
            sa.Column(
                "timezone", sa.String(length=80), nullable=False, server_default="Europe/London"
            ),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column(
                "delivery_channel", sa.String(length=20), nullable=False, server_default="web"
            ),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_result_summary", sa.Text(), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.CheckConstraint(
                "schedule_type IN ('once', 'daily', 'weekly', 'monthly')",
                name="ck_scheduled_actions_schedule_type",
            ),
            sa.CheckConstraint(
                "status IN ('active', 'paused', 'archived')",
                name="ck_scheduled_actions_status",
            ),
            sa.CheckConstraint(
                "delivery_channel IN ('web', 'telegram', 'email', 'voice')",
                name="ck_scheduled_actions_delivery_channel",
            ),
        )
    if not _has_index("scheduled_actions", "ix_scheduled_actions_user_id"):
        op.create_index("ix_scheduled_actions_user_id", "scheduled_actions", ["user_id"])
    if not _has_index("scheduled_actions", "ix_scheduled_actions_status"):
        op.create_index("ix_scheduled_actions_status", "scheduled_actions", ["status"])
    if not _has_index("scheduled_actions", "ix_scheduled_actions_next_run_at"):
        op.create_index("ix_scheduled_actions_next_run_at", "scheduled_actions", ["next_run_at"])

    if not _has_table("scheduled_action_runs"):
        op.create_table(
            "scheduled_action_runs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("action_id", UUID(as_uuid=True), nullable=False),
            sa.Column("workflow_id", UUID(as_uuid=True), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
            sa.Column("result_summary", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("payload", JSONB(), nullable=True),
            sa.Column("triggered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["action_id"], ["scheduled_actions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.id"], ondelete="SET NULL"),
            sa.CheckConstraint(
                "status IN ('queued', 'running', 'completed', 'failed')",
                name="ck_scheduled_action_runs_status",
            ),
        )
    if not _has_index("scheduled_action_runs", "ix_scheduled_action_runs_action_id"):
        op.create_index(
            "ix_scheduled_action_runs_action_id", "scheduled_action_runs", ["action_id"]
        )
    if not _has_index("scheduled_action_runs", "ix_scheduled_action_runs_triggered_at"):
        op.create_index(
            "ix_scheduled_action_runs_triggered_at",
            "scheduled_action_runs",
            ["triggered_at"],
        )


def downgrade() -> None:
    tables_and_indexes = [
        (
            "scheduled_action_runs",
            ["ix_scheduled_action_runs_triggered_at", "ix_scheduled_action_runs_action_id"],
        ),
        (
            "scheduled_actions",
            [
                "ix_scheduled_actions_next_run_at",
                "ix_scheduled_actions_status",
                "ix_scheduled_actions_user_id",
            ],
        ),
        (
            "connector_documents",
            [
                "ix_connector_documents_embedding_hnsw",
                "ix_connector_documents_synced_at",
                "ix_connector_documents_source_type",
                "ix_connector_documents_account_id",
            ],
        ),
        (
            "connector_sync_jobs",
            [
                "ix_connector_sync_jobs_created_at",
                "ix_connector_sync_jobs_status",
                "ix_connector_sync_jobs_account_id",
            ],
        ),
        (
            "connector_accounts",
            [
                "ix_connector_accounts_status",
                "ix_connector_accounts_connector_type",
                "ix_connector_accounts_user_id",
            ],
        ),
        (
            "saved_memories",
            [
                "ix_saved_memories_updated_at",
                "ix_saved_memories_state",
                "ix_saved_memories_scope",
                "ix_saved_memories_user_id",
            ],
        ),
        (
            "browser_sessions",
            [
                "ix_browser_sessions_created_at",
                "ix_browser_sessions_status",
                "ix_browser_sessions_workflow_id",
            ],
        ),
        (
            "approval_requests",
            [
                "ix_approval_requests_created_at",
                "ix_approval_requests_status",
                "ix_approval_requests_workflow_id",
            ],
        ),
        (
            "workflow_run_steps",
            [
                "ix_workflow_run_steps_created_at",
                "ix_workflow_run_steps_status",
                "ix_workflow_run_steps_workflow_id",
            ],
        ),
    ]
    for table_name, indexes in tables_and_indexes:
        for index_name in indexes:
            if _has_index(table_name, index_name):
                op.drop_index(index_name, table_name=table_name)

    if _has_unique_constraint("connector_documents", "uq_connector_documents_external"):
        op.drop_constraint("uq_connector_documents_external", "connector_documents", type_="unique")

    for table_name, _indexes in tables_and_indexes:
        if _has_table(table_name):
            op.drop_table(table_name)
