"""Add account-scoped RLS policies.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-05-18 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Iterable

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "f9a0b1c2d3e4"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None

ACCOUNT_ID_TABLES = (
    "account_memberships",
    "subscriptions",
    "entitlements",
    "audit_events",
    "usage_metering",
    "data_exports",
    "deletion_requests",
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

CONNECTOR_CHILD_TABLES = (
    "connector_sync_jobs",
    "connector_documents",
)

POLICY_NAME = "app_account_isolation"


def _existing_tables(tables: Iterable[str]) -> list[str]:
    inspector = inspect(op.get_bind())
    names = set(inspector.get_table_names())
    return [table for table in tables if table in names]


def _policy_expr_for(table_name: str) -> str:
    if table_name == "accounts":
        return "id::text = current_setting('app.account_id', true)"
    if table_name == "users":
        return (
            "EXISTS ("
            "SELECT 1 FROM account_memberships am "
            "WHERE am.user_id = users.id "
            "AND am.account_id::text = current_setting('app.account_id', true)"
            ")"
        )
    if table_name in CONNECTOR_CHILD_TABLES:
        return (
            "EXISTS ("
            "SELECT 1 FROM connector_accounts ca "
            f"WHERE ca.id = {table_name}.account_id "
            "AND ca.account_id::text = current_setting('app.account_id', true)"
            ")"
        )
    return "account_id::text = current_setting('app.account_id', true)"


def _enable_policy(table_name: str) -> None:
    expr = _policy_expr_for(table_name)
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS {POLICY_NAME} ON "{table_name}"')
    op.execute(
        f'CREATE POLICY {POLICY_NAME} ON "{table_name}" FOR ALL USING ({expr}) WITH CHECK ({expr})'
    )


def _drop_policy(table_name: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS {POLICY_NAME} ON "{table_name}"')


def upgrade() -> None:
    for table_name in _existing_tables(
        ("accounts", "users", *ACCOUNT_ID_TABLES, *CONNECTOR_CHILD_TABLES)
    ):
        _enable_policy(table_name)


def downgrade() -> None:
    for table_name in _existing_tables(
        ("accounts", "users", *ACCOUNT_ID_TABLES, *CONNECTOR_CHILD_TABLES)
    ):
        _drop_policy(table_name)
