"""Add workflow runtime, tool receipt, policy decision, and artifact tables.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-10 00:00:01.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


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
    if not _has_column("interaction_records", "workflow_id"):
        op.add_column(
            "interaction_records",
            sa.Column("workflow_id", sa.String(length=100), nullable=True),
        )
    if not _has_column("interaction_records", "workflow_status"):
        op.add_column(
            "interaction_records",
            sa.Column("workflow_status", sa.String(length=50), nullable=True),
        )
    if not _has_index("interaction_records", "ix_interaction_records_workflow_id"):
        op.create_index(
            "ix_interaction_records_workflow_id",
            "interaction_records",
            ["workflow_id"],
        )

    if not _has_table("workflow_runs"):
        op.create_table(
            "workflow_runs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("source", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("request_excerpt", sa.Text(), nullable=True),
            sa.Column("specialist", sa.String(length=50), nullable=True),
            sa.Column("trace_id", sa.String(length=100), nullable=True),
            sa.Column("response_id", sa.String(length=100), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
        )
    if not _has_index("workflow_runs", "ix_workflow_runs_user_id"):
        op.create_index("ix_workflow_runs_user_id", "workflow_runs", ["user_id"])
    if not _has_index("workflow_runs", "ix_workflow_runs_status"):
        op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])
    if not _has_index("workflow_runs", "ix_workflow_runs_trace_id"):
        op.create_index("ix_workflow_runs_trace_id", "workflow_runs", ["trace_id"])
    if not _has_index("workflow_runs", "ix_workflow_runs_created_at"):
        op.create_index("ix_workflow_runs_created_at", "workflow_runs", ["created_at"])

    if not _has_table("workflow_checkpoints"):
        op.create_table(
            "workflow_checkpoints",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("workflow_id", UUID(as_uuid=True), nullable=False),
            sa.Column("checkpoint_kind", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("payload", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(
                ["workflow_id"],
                ["workflow_runs.id"],
                ondelete="CASCADE",
            ),
        )
    if not _has_index("workflow_checkpoints", "ix_workflow_checkpoints_workflow_id"):
        op.create_index(
            "ix_workflow_checkpoints_workflow_id",
            "workflow_checkpoints",
            ["workflow_id"],
        )
    if not _has_index("workflow_checkpoints", "ix_workflow_checkpoints_status"):
        op.create_index(
            "ix_workflow_checkpoints_status",
            "workflow_checkpoints",
            ["status"],
        )
    if not _has_index("workflow_checkpoints", "ix_workflow_checkpoints_created_at"):
        op.create_index(
            "ix_workflow_checkpoints_created_at",
            "workflow_checkpoints",
            ["created_at"],
        )

    if not _has_table("tool_receipts"):
        op.create_table(
            "tool_receipts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("workflow_id", sa.String(length=100), nullable=True),
            sa.Column("trace_id", sa.String(length=100), nullable=True),
            sa.Column("interaction_id", sa.String(length=100), nullable=True),
            sa.Column("idempotency_key", sa.String(length=100), nullable=False),
            sa.Column("tool_name", sa.String(length=150), nullable=False),
            sa.Column("server_name", sa.String(length=100), nullable=True),
            sa.Column("mutation_class", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("argument_hash", sa.String(length=128), nullable=False),
            sa.Column("arguments", JSONB(), nullable=True),
            sa.Column("audit_metadata", JSONB(), nullable=True),
            sa.Column("result_summary", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if not _has_unique_constraint("tool_receipts", "uq_tool_receipts_idempotency_key"):
        op.create_unique_constraint(
            "uq_tool_receipts_idempotency_key",
            "tool_receipts",
            ["idempotency_key"],
        )
    if not _has_index("tool_receipts", "ix_tool_receipts_trace_id"):
        op.create_index("ix_tool_receipts_trace_id", "tool_receipts", ["trace_id"])
    if not _has_index("tool_receipts", "ix_tool_receipts_tool_name"):
        op.create_index("ix_tool_receipts_tool_name", "tool_receipts", ["tool_name"])
    if not _has_index("tool_receipts", "ix_tool_receipts_created_at"):
        op.create_index("ix_tool_receipts_created_at", "tool_receipts", ["created_at"])

    if not _has_table("policy_decisions"):
        op.create_table(
            "policy_decisions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("workflow_id", sa.String(length=100), nullable=True),
            sa.Column("trace_id", sa.String(length=100), nullable=True),
            sa.Column("specialist", sa.String(length=50), nullable=True),
            sa.Column("policy_name", sa.String(length=100), nullable=False),
            sa.Column("decision", sa.String(length=50), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("subject_type", sa.String(length=50), nullable=False),
            sa.Column("subject_id", sa.String(length=100), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if not _has_index("policy_decisions", "ix_policy_decisions_trace_id"):
        op.create_index("ix_policy_decisions_trace_id", "policy_decisions", ["trace_id"])
    if not _has_index("policy_decisions", "ix_policy_decisions_policy_name"):
        op.create_index(
            "ix_policy_decisions_policy_name",
            "policy_decisions",
            ["policy_name"],
        )
    if not _has_index("policy_decisions", "ix_policy_decisions_created_at"):
        op.create_index(
            "ix_policy_decisions_created_at",
            "policy_decisions",
            ["created_at"],
        )

    if not _has_table("artifacts"):
        op.create_table(
            "artifacts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("workflow_id", sa.String(length=100), nullable=True),
            sa.Column("trace_id", sa.String(length=100), nullable=True),
            sa.Column("source_id", sa.String(length=100), nullable=True),
            sa.Column("artifact_type", sa.String(length=50), nullable=False),
            sa.Column("scope", sa.String(length=30), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("payload", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if not _has_index("artifacts", "ix_artifacts_user_id"):
        op.create_index("ix_artifacts_user_id", "artifacts", ["user_id"])
    if not _has_index("artifacts", "ix_artifacts_trace_id"):
        op.create_index("ix_artifacts_trace_id", "artifacts", ["trace_id"])
    if not _has_index("artifacts", "ix_artifacts_artifact_type"):
        op.create_index("ix_artifacts_artifact_type", "artifacts", ["artifact_type"])
    if not _has_index("artifacts", "ix_artifacts_created_at"):
        op.create_index("ix_artifacts_created_at", "artifacts", ["created_at"])


def downgrade() -> None:
    if _has_index("artifacts", "ix_artifacts_created_at"):
        op.drop_index("ix_artifacts_created_at", table_name="artifacts")
    if _has_index("artifacts", "ix_artifacts_artifact_type"):
        op.drop_index("ix_artifacts_artifact_type", table_name="artifacts")
    if _has_index("artifacts", "ix_artifacts_trace_id"):
        op.drop_index("ix_artifacts_trace_id", table_name="artifacts")
    if _has_index("artifacts", "ix_artifacts_user_id"):
        op.drop_index("ix_artifacts_user_id", table_name="artifacts")
    if _has_table("artifacts"):
        op.drop_table("artifacts")

    if _has_index("policy_decisions", "ix_policy_decisions_created_at"):
        op.drop_index("ix_policy_decisions_created_at", table_name="policy_decisions")
    if _has_index("policy_decisions", "ix_policy_decisions_policy_name"):
        op.drop_index("ix_policy_decisions_policy_name", table_name="policy_decisions")
    if _has_index("policy_decisions", "ix_policy_decisions_trace_id"):
        op.drop_index("ix_policy_decisions_trace_id", table_name="policy_decisions")
    if _has_table("policy_decisions"):
        op.drop_table("policy_decisions")

    if _has_index("tool_receipts", "ix_tool_receipts_created_at"):
        op.drop_index("ix_tool_receipts_created_at", table_name="tool_receipts")
    if _has_index("tool_receipts", "ix_tool_receipts_tool_name"):
        op.drop_index("ix_tool_receipts_tool_name", table_name="tool_receipts")
    if _has_index("tool_receipts", "ix_tool_receipts_trace_id"):
        op.drop_index("ix_tool_receipts_trace_id", table_name="tool_receipts")
    if _has_unique_constraint("tool_receipts", "uq_tool_receipts_idempotency_key"):
        op.drop_constraint(
            "uq_tool_receipts_idempotency_key",
            "tool_receipts",
            type_="unique",
        )
    if _has_table("tool_receipts"):
        op.drop_table("tool_receipts")

    if _has_index("workflow_checkpoints", "ix_workflow_checkpoints_created_at"):
        op.drop_index(
            "ix_workflow_checkpoints_created_at",
            table_name="workflow_checkpoints",
        )
    if _has_index("workflow_checkpoints", "ix_workflow_checkpoints_status"):
        op.drop_index("ix_workflow_checkpoints_status", table_name="workflow_checkpoints")
    if _has_index("workflow_checkpoints", "ix_workflow_checkpoints_workflow_id"):
        op.drop_index(
            "ix_workflow_checkpoints_workflow_id",
            table_name="workflow_checkpoints",
        )
    if _has_table("workflow_checkpoints"):
        op.drop_table("workflow_checkpoints")

    if _has_index("workflow_runs", "ix_workflow_runs_created_at"):
        op.drop_index("ix_workflow_runs_created_at", table_name="workflow_runs")
    if _has_index("workflow_runs", "ix_workflow_runs_trace_id"):
        op.drop_index("ix_workflow_runs_trace_id", table_name="workflow_runs")
    if _has_index("workflow_runs", "ix_workflow_runs_status"):
        op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    if _has_index("workflow_runs", "ix_workflow_runs_user_id"):
        op.drop_index("ix_workflow_runs_user_id", table_name="workflow_runs")
    if _has_table("workflow_runs"):
        op.drop_table("workflow_runs")

    if _has_index("interaction_records", "ix_interaction_records_workflow_id"):
        op.drop_index(
            "ix_interaction_records_workflow_id",
            table_name="interaction_records",
        )
    if _has_column("interaction_records", "workflow_status"):
        op.drop_column("interaction_records", "workflow_status")
    if _has_column("interaction_records", "workflow_id"):
        op.drop_column("interaction_records", "workflow_id")
