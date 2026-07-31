"""Add voice_calls table for outbound reflection call lifecycle tracking.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-12 00:00:01.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
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
    if not _has_table("voice_calls"):
        op.create_table(
            "voice_calls",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("conversation_id", sa.String(length=100), nullable=True),
            sa.Column("call_sid", sa.String(length=100), nullable=True),
            sa.Column("direction", sa.String(length=20), nullable=False, server_default="outbound"),
            sa.Column("trigger_source", sa.String(length=40), nullable=False),
            sa.Column("call_status", sa.String(length=30), nullable=False, server_default="queued"),
            sa.Column(
                "processing_status",
                sa.String(length=30),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("target_phone_number", sa.String(length=40), nullable=False),
            sa.Column("from_phone_number", sa.String(length=40), nullable=True),
            sa.Column("agent_id", sa.String(length=100), nullable=False),
            sa.Column("duration_secs", sa.Integer(), nullable=True),
            sa.Column("failure_reason", sa.String(length=80), nullable=True),
            sa.Column("episode_id", UUID(as_uuid=True), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(
                ["episode_id"],
                ["episodes.id"],
                ondelete="SET NULL",
            ),
            sa.CheckConstraint(
                "direction IN ('outbound', 'inbound')",
                name="ck_voice_calls_direction",
            ),
            sa.CheckConstraint(
                "trigger_source IN ('manual_test', 'scheduled_reflection')",
                name="ck_voice_calls_trigger_source",
            ),
            sa.CheckConstraint(
                "call_status IN "
                "('queued', 'initiated', 'completed', 'failed', 'no_answer', 'busy')",
                name="ck_voice_calls_call_status",
            ),
            sa.CheckConstraint(
                "processing_status IN ('pending', 'transcript_received', 'ingested', 'failed')",
                name="ck_voice_calls_processing_status",
            ),
        )

    if not _has_unique_constraint("voice_calls", "uq_voice_calls_conversation_id"):
        op.create_unique_constraint(
            "uq_voice_calls_conversation_id",
            "voice_calls",
            ["conversation_id"],
        )
    if not _has_unique_constraint("voice_calls", "uq_voice_calls_call_sid"):
        op.create_unique_constraint(
            "uq_voice_calls_call_sid",
            "voice_calls",
            ["call_sid"],
        )
    if not _has_index("voice_calls", "ix_voice_calls_created_at"):
        op.create_index("ix_voice_calls_created_at", "voice_calls", ["created_at"])
    if not _has_index("voice_calls", "ix_voice_calls_call_status"):
        op.create_index("ix_voice_calls_call_status", "voice_calls", ["call_status"])
    if not _has_index("voice_calls", "ix_voice_calls_processing_status"):
        op.create_index(
            "ix_voice_calls_processing_status",
            "voice_calls",
            ["processing_status"],
        )
    if not _has_index("voice_calls", "ix_voice_calls_target_phone_number"):
        op.create_index(
            "ix_voice_calls_target_phone_number",
            "voice_calls",
            ["target_phone_number"],
        )


def downgrade() -> None:
    if _has_index("voice_calls", "ix_voice_calls_target_phone_number"):
        op.drop_index("ix_voice_calls_target_phone_number", table_name="voice_calls")
    if _has_index("voice_calls", "ix_voice_calls_processing_status"):
        op.drop_index("ix_voice_calls_processing_status", table_name="voice_calls")
    if _has_index("voice_calls", "ix_voice_calls_call_status"):
        op.drop_index("ix_voice_calls_call_status", table_name="voice_calls")
    if _has_index("voice_calls", "ix_voice_calls_created_at"):
        op.drop_index("ix_voice_calls_created_at", table_name="voice_calls")
    if _has_unique_constraint("voice_calls", "uq_voice_calls_call_sid"):
        op.drop_constraint("uq_voice_calls_call_sid", "voice_calls", type_="unique")
    if _has_unique_constraint("voice_calls", "uq_voice_calls_conversation_id"):
        op.drop_constraint("uq_voice_calls_conversation_id", "voice_calls", type_="unique")
    if _has_table("voice_calls"):
        op.drop_table("voice_calls")
