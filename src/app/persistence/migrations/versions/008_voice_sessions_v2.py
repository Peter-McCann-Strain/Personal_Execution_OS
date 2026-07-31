"""Expand voice_calls into managed voice sessions for phone and app runtimes.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-04-13 23:40:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "a7b8c9d0e1f2"
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


def _has_check_constraint(table_name: str, constraint_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return constraint_name in {
        constraint["name"]
        for constraint in inspector.get_check_constraints(table_name)
        if constraint.get("name")
    }


def upgrade() -> None:
    if not _has_table("voice_calls"):
        return

    if not _has_column("voice_calls", "channel"):
        op.add_column(
            "voice_calls",
            sa.Column(
                "channel", sa.String(length=30), nullable=False, server_default="pstn_outbound"
            ),
        )
    if not _has_column("voice_calls", "purpose"):
        op.add_column(
            "voice_calls",
            sa.Column(
                "purpose", sa.String(length=40), nullable=False, server_default="general_assistant"
            ),
        )
    if not _has_column("voice_calls", "config_version"):
        op.add_column(
            "voice_calls", sa.Column("config_version", sa.String(length=160), nullable=True)
        )
    if not _has_column("voice_calls", "provider_route"):
        op.add_column(
            "voice_calls", sa.Column("provider_route", sa.String(length=80), nullable=True)
        )
    if not _has_column("voice_calls", "connect_latency_ms"):
        op.add_column("voice_calls", sa.Column("connect_latency_ms", sa.Integer(), nullable=True))
    if not _has_column("voice_calls", "transcript_quality_score"):
        op.add_column(
            "voice_calls", sa.Column("transcript_quality_score", sa.Float(), nullable=True)
        )

    op.execute(
        sa.text(
            """
            UPDATE voice_calls
            SET channel = CASE
                WHEN direction = 'inbound' THEN 'pstn_inbound'
                ELSE 'pstn_outbound'
            END
            WHERE channel IS NULL
               OR channel NOT IN ('pstn_outbound', 'pstn_inbound', 'app_realtime')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE voice_calls
            SET purpose = CASE
                WHEN trigger_source = 'scheduled_reflection' THEN 'scheduled_reflection'
                ELSE 'on_demand_reflection'
            END
            WHERE purpose IS NULL
               OR purpose NOT IN ('scheduled_reflection', 'on_demand_reflection', 'general_assistant')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE voice_calls
            SET provider_route = CASE
                WHEN direction = 'inbound' THEN 'elevenlabs_twilio_inbound'
                ELSE 'elevenlabs_twilio'
            END
            WHERE provider_route IS NULL
            """
        )
    )

    op.execute("ALTER TABLE voice_calls DROP CONSTRAINT IF EXISTS ck_voice_calls_trigger_source")
    op.execute("ALTER TABLE voice_calls DROP CONSTRAINT IF EXISTS ck_voice_calls_channel")
    op.execute("ALTER TABLE voice_calls DROP CONSTRAINT IF EXISTS ck_voice_calls_purpose")

    if not _has_check_constraint("voice_calls", "ck_voice_calls_channel"):
        op.create_check_constraint(
            "ck_voice_calls_channel",
            "voice_calls",
            "channel IN ('pstn_outbound', 'pstn_inbound', 'app_realtime')",
        )
    if not _has_check_constraint("voice_calls", "ck_voice_calls_purpose"):
        op.create_check_constraint(
            "ck_voice_calls_purpose",
            "voice_calls",
            "purpose IN ('scheduled_reflection', 'on_demand_reflection', 'general_assistant')",
        )
    if not _has_check_constraint("voice_calls", "ck_voice_calls_trigger_source"):
        op.create_check_constraint(
            "ck_voice_calls_trigger_source",
            "voice_calls",
            "trigger_source IN ('manual_test', 'scheduled_reflection', "
            "'on_demand_reflection', 'inbound_call', 'app_session')",
        )

    if not _has_index("voice_calls", "ix_voice_calls_channel"):
        op.create_index("ix_voice_calls_channel", "voice_calls", ["channel"])
    if not _has_index("voice_calls", "ix_voice_calls_purpose"):
        op.create_index("ix_voice_calls_purpose", "voice_calls", ["purpose"])


def downgrade() -> None:
    if not _has_table("voice_calls"):
        return

    if _has_index("voice_calls", "ix_voice_calls_purpose"):
        op.drop_index("ix_voice_calls_purpose", table_name="voice_calls")
    if _has_index("voice_calls", "ix_voice_calls_channel"):
        op.drop_index("ix_voice_calls_channel", table_name="voice_calls")

    op.execute("ALTER TABLE voice_calls DROP CONSTRAINT IF EXISTS ck_voice_calls_trigger_source")
    op.execute("ALTER TABLE voice_calls DROP CONSTRAINT IF EXISTS ck_voice_calls_purpose")
    op.execute("ALTER TABLE voice_calls DROP CONSTRAINT IF EXISTS ck_voice_calls_channel")

    if not _has_check_constraint("voice_calls", "ck_voice_calls_trigger_source"):
        op.create_check_constraint(
            "ck_voice_calls_trigger_source",
            "voice_calls",
            "trigger_source IN ('manual_test', 'scheduled_reflection')",
        )

    for column_name in (
        "transcript_quality_score",
        "connect_latency_ms",
        "provider_route",
        "config_version",
        "purpose",
        "channel",
    ):
        if _has_column("voice_calls", column_name):
            op.drop_column("voice_calls", column_name)
