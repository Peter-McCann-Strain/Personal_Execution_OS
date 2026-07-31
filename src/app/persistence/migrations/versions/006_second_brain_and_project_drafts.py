"""Add second-brain, project-draft, dependency, and content-factory tables.

Revision ID: f6a7b8c9d0e1
Revises: f1a2b3c4d5e6
Create Date: 2026-04-13 00:00:01.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "f1a2b3c4d5e6"
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
    # --- notes -----------------------------------------------------------------
    if not _has_column("notes", "slug"):
        op.add_column("notes", sa.Column("slug", sa.String(length=180), nullable=True))
    if not _has_column("notes", "aliases"):
        op.add_column("notes", sa.Column("aliases", ARRAY(sa.Text()), nullable=True))
    if not _has_column("notes", "kind"):
        op.add_column("notes", sa.Column("kind", sa.String(length=30), nullable=True))
    if not _has_column("notes", "daily_date"):
        op.add_column("notes", sa.Column("daily_date", sa.Date(), nullable=True))
    if not _has_column("notes", "frontmatter"):
        op.add_column("notes", sa.Column("frontmatter", JSONB(), nullable=True))
    if not _has_index("notes", "ix_notes_slug"):
        op.create_index("ix_notes_slug", "notes", ["slug"], unique=True)
    if not _has_index("notes", "ix_notes_kind"):
        op.create_index("ix_notes_kind", "notes", ["kind"])
    if not _has_index("notes", "ix_notes_daily_date"):
        op.create_index("ix_notes_daily_date", "notes", ["daily_date"])

    # --- note_links ------------------------------------------------------------
    if not _has_column("note_links", "link_type"):
        op.add_column(
            "note_links",
            sa.Column("link_type", sa.String(length=30), nullable=False, server_default="manual"),
        )
    if not _has_column("note_links", "origin"):
        op.add_column(
            "note_links",
            sa.Column("origin", sa.String(length=30), nullable=False, server_default="manual"),
        )

    # --- tasks/dependencies ----------------------------------------------------
    if not _has_column("tasks", "blocked_reason"):
        op.add_column("tasks", sa.Column("blocked_reason", sa.Text(), nullable=True))
    if not _has_table("task_dependencies"):
        op.create_table(
            "task_dependencies",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("task_id", UUID(as_uuid=True), nullable=False),
            sa.Column("depends_on_task_id", UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["depends_on_task_id"], ["tasks.id"], ondelete="CASCADE"),
            sa.CheckConstraint(
                "task_id <> depends_on_task_id", name="ck_task_dependencies_not_self"
            ),
        )
    if not _has_unique_constraint("task_dependencies", "uq_task_dependencies_edge"):
        op.create_unique_constraint(
            "uq_task_dependencies_edge",
            "task_dependencies",
            ["task_id", "depends_on_task_id"],
        )
    if not _has_index("task_dependencies", "ix_task_dependencies_task_id"):
        op.create_index("ix_task_dependencies_task_id", "task_dependencies", ["task_id"])
    if not _has_index("task_dependencies", "ix_task_dependencies_depends_on_task_id"):
        op.create_index(
            "ix_task_dependencies_depends_on_task_id",
            "task_dependencies",
            ["depends_on_task_id"],
        )

    # --- project drafts --------------------------------------------------------
    if not _has_table("project_drafts"):
        op.create_table(
            "project_drafts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("source_message", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
            sa.Column("breakdown", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("applied_project_id", UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["applied_project_id"], ["projects.id"], ondelete="SET NULL"),
        )
    if not _has_index("project_drafts", "ix_project_drafts_user_id"):
        op.create_index("ix_project_drafts_user_id", "project_drafts", ["user_id"])
    if not _has_index("project_drafts", "ix_project_drafts_status"):
        op.create_index("ix_project_drafts_status", "project_drafts", ["status"])
    if not _has_index("project_drafts", "ix_project_drafts_created_at"):
        op.create_index("ix_project_drafts_created_at", "project_drafts", ["created_at"])

    # --- note canvases ---------------------------------------------------------
    if not _has_table("note_canvases"):
        op.create_table(
            "note_canvases",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("primary_note_id", UUID(as_uuid=True), nullable=True),
            sa.Column("nodes", JSONB(), nullable=True),
            sa.Column("edges", JSONB(), nullable=True),
            sa.Column("viewport", JSONB(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["primary_note_id"], ["notes.id"], ondelete="SET NULL"),
        )
    if not _has_index("note_canvases", "ix_note_canvases_primary_note_id"):
        op.create_index("ix_note_canvases_primary_note_id", "note_canvases", ["primary_note_id"])
    if not _has_index("note_canvases", "ix_note_canvases_updated_at"):
        op.create_index("ix_note_canvases_updated_at", "note_canvases", ["updated_at"])

    # --- content assets --------------------------------------------------------
    if not _has_table("content_assets"):
        op.create_table(
            "content_assets",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("note_id", UUID(as_uuid=True), nullable=True),
            sa.Column("project_id", UUID(as_uuid=True), nullable=True),
            sa.Column("task_id", UUID(as_uuid=True), nullable=True),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("asset_type", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="ready"),
            sa.Column("source_pack", JSONB(), nullable=True),
            sa.Column("template_prompt", sa.Text(), nullable=True),
            sa.Column("run_notes", sa.Text(), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        )
    if not _has_index("content_assets", "ix_content_assets_note_id"):
        op.create_index("ix_content_assets_note_id", "content_assets", ["note_id"])
    if not _has_index("content_assets", "ix_content_assets_project_id"):
        op.create_index("ix_content_assets_project_id", "content_assets", ["project_id"])
    if not _has_index("content_assets", "ix_content_assets_asset_type"):
        op.create_index("ix_content_assets_asset_type", "content_assets", ["asset_type"])
    if not _has_index("content_assets", "ix_content_assets_status"):
        op.create_index("ix_content_assets_status", "content_assets", ["status"])
    if not _has_index("content_assets", "ix_content_assets_updated_at"):
        op.create_index("ix_content_assets_updated_at", "content_assets", ["updated_at"])


def downgrade() -> None:
    if _has_index("content_assets", "ix_content_assets_updated_at"):
        op.drop_index("ix_content_assets_updated_at", table_name="content_assets")
    if _has_index("content_assets", "ix_content_assets_status"):
        op.drop_index("ix_content_assets_status", table_name="content_assets")
    if _has_index("content_assets", "ix_content_assets_asset_type"):
        op.drop_index("ix_content_assets_asset_type", table_name="content_assets")
    if _has_index("content_assets", "ix_content_assets_project_id"):
        op.drop_index("ix_content_assets_project_id", table_name="content_assets")
    if _has_index("content_assets", "ix_content_assets_note_id"):
        op.drop_index("ix_content_assets_note_id", table_name="content_assets")
    if _has_table("content_assets"):
        op.drop_table("content_assets")

    if _has_index("note_canvases", "ix_note_canvases_updated_at"):
        op.drop_index("ix_note_canvases_updated_at", table_name="note_canvases")
    if _has_index("note_canvases", "ix_note_canvases_primary_note_id"):
        op.drop_index("ix_note_canvases_primary_note_id", table_name="note_canvases")
    if _has_table("note_canvases"):
        op.drop_table("note_canvases")

    if _has_index("project_drafts", "ix_project_drafts_created_at"):
        op.drop_index("ix_project_drafts_created_at", table_name="project_drafts")
    if _has_index("project_drafts", "ix_project_drafts_status"):
        op.drop_index("ix_project_drafts_status", table_name="project_drafts")
    if _has_index("project_drafts", "ix_project_drafts_user_id"):
        op.drop_index("ix_project_drafts_user_id", table_name="project_drafts")
    if _has_table("project_drafts"):
        op.drop_table("project_drafts")

    if _has_index("task_dependencies", "ix_task_dependencies_depends_on_task_id"):
        op.drop_index("ix_task_dependencies_depends_on_task_id", table_name="task_dependencies")
    if _has_index("task_dependencies", "ix_task_dependencies_task_id"):
        op.drop_index("ix_task_dependencies_task_id", table_name="task_dependencies")
    if _has_unique_constraint("task_dependencies", "uq_task_dependencies_edge"):
        op.drop_constraint("uq_task_dependencies_edge", "task_dependencies", type_="unique")
    if _has_table("task_dependencies"):
        op.drop_table("task_dependencies")
    if _has_column("tasks", "blocked_reason"):
        op.drop_column("tasks", "blocked_reason")

    if _has_column("note_links", "origin"):
        op.drop_column("note_links", "origin")
    if _has_column("note_links", "link_type"):
        op.drop_column("note_links", "link_type")

    if _has_index("notes", "ix_notes_daily_date"):
        op.drop_index("ix_notes_daily_date", table_name="notes")
    if _has_index("notes", "ix_notes_kind"):
        op.drop_index("ix_notes_kind", table_name="notes")
    if _has_index("notes", "ix_notes_slug"):
        op.drop_index("ix_notes_slug", table_name="notes")
    if _has_column("notes", "frontmatter"):
        op.drop_column("notes", "frontmatter")
    if _has_column("notes", "daily_date"):
        op.drop_column("notes", "daily_date")
    if _has_column("notes", "kind"):
        op.drop_column("notes", "kind")
    if _has_column("notes", "aliases"):
        op.drop_column("notes", "aliases")
    if _has_column("notes", "slug"):
        op.drop_column("notes", "slug")
