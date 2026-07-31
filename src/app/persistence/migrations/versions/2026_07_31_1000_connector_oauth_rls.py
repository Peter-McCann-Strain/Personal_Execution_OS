"""Protect connector OAuth state with account-scoped RLS.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-07-31 10:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None

TABLE = "connector_oauth_states"
POLICY = "app_account_isolation"


def upgrade() -> None:
    op.execute(f'ALTER TABLE "{TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS {POLICY} ON "{TABLE}"')
    op.execute(
        f'CREATE POLICY {POLICY} ON "{TABLE}" FOR ALL '
        "USING (account_id::text = current_setting('app.account_id', true)) "
        "WITH CHECK (account_id::text = current_setting('app.account_id', true))"
    )


def downgrade() -> None:
    op.execute(f'DROP POLICY IF EXISTS {POLICY} ON "{TABLE}"')
