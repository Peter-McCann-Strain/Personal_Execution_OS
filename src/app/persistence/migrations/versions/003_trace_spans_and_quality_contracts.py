"""Add trace spans and richer interaction quality metadata.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-09 00:00:01.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
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


def upgrade() -> None:
    if not _has_table("agent_trace_spans"):
        op.create_table(
            "agent_trace_spans",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("trace_id", sa.String(length=100), nullable=False),
            sa.Column("parent_span_id", sa.String(length=100), nullable=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("span_kind", sa.String(length=50), nullable=False),
            sa.Column("channel", sa.String(length=50), nullable=False),
            sa.Column("specialist", sa.String(length=50), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("error_class", sa.String(length=100), nullable=True),
            sa.Column("model", sa.String(length=100), nullable=True),
            sa.Column("tokens_in", sa.Integer(), nullable=True),
            sa.Column("tokens_out", sa.Integer(), nullable=True),
            sa.Column("tool_name", sa.String(length=100), nullable=True),
            sa.Column("cache_hit", sa.Boolean(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("details", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if not _has_index("agent_trace_spans", "ix_agent_trace_spans_trace_id"):
        op.create_index(
            "ix_agent_trace_spans_trace_id",
            "agent_trace_spans",
            ["trace_id"],
        )
    if not _has_index("agent_trace_spans", "ix_agent_trace_spans_span_kind"):
        op.create_index(
            "ix_agent_trace_spans_span_kind",
            "agent_trace_spans",
            ["span_kind"],
        )
    if not _has_index("agent_trace_spans", "ix_agent_trace_spans_created_at"):
        op.create_index(
            "ix_agent_trace_spans_created_at",
            "agent_trace_spans",
            ["created_at"],
        )

    if not _has_column("interaction_records", "trace_id"):
        op.add_column(
            "interaction_records",
            sa.Column("trace_id", sa.String(length=100), nullable=True),
        )
    if not _has_column("interaction_records", "response_id"):
        op.add_column(
            "interaction_records",
            sa.Column("response_id", sa.String(length=100), nullable=True),
        )
    if not _has_column("interaction_records", "quality_scores"):
        op.add_column(
            "interaction_records",
            sa.Column("quality_scores", JSONB(), nullable=True),
        )
    if not _has_column("interaction_records", "channel_metrics"):
        op.add_column(
            "interaction_records",
            sa.Column("channel_metrics", JSONB(), nullable=True),
        )
    if not _has_index("interaction_records", "ix_interaction_records_trace_id"):
        op.create_index(
            "ix_interaction_records_trace_id",
            "interaction_records",
            ["trace_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_interaction_records_trace_id", table_name="interaction_records")
    op.drop_column("interaction_records", "channel_metrics")
    op.drop_column("interaction_records", "quality_scores")
    op.drop_column("interaction_records", "response_id")

    op.drop_index("ix_agent_trace_spans_created_at", table_name="agent_trace_spans")
    op.drop_index("ix_agent_trace_spans_span_kind", table_name="agent_trace_spans")
    op.drop_index("ix_agent_trace_spans_trace_id", table_name="agent_trace_spans")
    op.drop_table("agent_trace_spans")
