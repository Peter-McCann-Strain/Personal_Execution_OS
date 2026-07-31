"""Bridge phantom revision f1a2b3c4d5e6 to allow upgrade to current heads.

This migration exists only to reconnect the alembic_version chain after a
previous development migration (f1a2b3c4d5e6) was applied to production but
its file was later replaced. The upgrade/downgrade bodies are intentionally
empty — they only establish the parent-child relationship in the chain.

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-04-15 18:00:00.000000+00:00
"""

from collections.abc import Sequence

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
