"""Initial schema -- core tables for Personal Execution OS.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-03-18 12:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Shared column helpers
_uuid_pk = dict(primary_key=True, server_default=sa.text("uuid_generate_v4()"))
_ts_now = sa.func.now()
_tz = dict(timezone=True)


def _pk() -> sa.Column:
    """UUID primary key with server-generated default."""
    return sa.Column("id", UUID(as_uuid=True), **_uuid_pk)


def _created() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(**_tz), server_default=_ts_now)


def _updated() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(**_tz), server_default=_ts_now)


def upgrade() -> None:
    # --- Extensions ----------------------------------------------------------
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # =====================================================================
    # Independent tables (no foreign keys)
    # =====================================================================

    # --- episodes ------------------------------------------------------------
    op.create_table(
        "episodes",
        _pk(),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("episode_type", sa.String(50), nullable=True),
        sa.Column("para_category", sa.String(20), nullable=True),
        sa.Column("mood_score", sa.Float(), nullable=True),
        sa.Column("energy_rating", sa.Float(), nullable=True),
        sa.Column("tags", ARRAY(sa.Text()), nullable=True),
        sa.Column("people_mentioned", ARRAY(sa.Text()), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column(
            "metadata",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "search_vector",
            TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=True,
        ),
        sa.Column("embedding", Vector(768), nullable=True),
        _created(),
        sa.CheckConstraint(
            "para_category IN ('project', 'area', 'resource', 'archive') OR para_category IS NULL",
            name="ck_episodes_para_category",
        ),
    )
    op.create_index("ix_episodes_created_at", "episodes", ["created_at"])
    op.create_index(
        "ix_episodes_search_vector",
        "episodes",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_episodes_embedding_hnsw",
        "episodes",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # --- goals (self-referential FK) -----------------------------------------
    op.create_table(
        "goals",
        _pk(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("goal_type", sa.String(20), nullable=True),
        sa.Column("parent_id", UUID(as_uuid=True), nullable=True),
        sa.Column("priority", sa.Integer(), server_default=sa.text("5")),
        sa.Column(
            "status",
            sa.String(20),
            server_default=sa.text("'active'"),
        ),
        sa.Column("progress", sa.Float(), server_default=sa.text("0.0")),
        sa.Column("deadline", sa.DateTime(**_tz), nullable=True),
        sa.Column("evidence", ARRAY(sa.Text()), nullable=True),
        _created(),
        _updated(),
        sa.ForeignKeyConstraint(["parent_id"], ["goals.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_goals_status", "goals", ["status"])
    op.create_index("ix_goals_parent_id", "goals", ["parent_id"])
    op.create_index("ix_goals_priority", "goals", ["priority"])

    # --- notes ---------------------------------------------------------------
    op.create_table(
        "notes",
        _pk(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("note_type", sa.String(20), nullable=True),
        sa.Column("para_category", sa.String(20), nullable=True),
        sa.Column(
            "progressive_summary_level",
            sa.Integer(),
            server_default=sa.text("1"),
        ),
        sa.Column("executive_summary", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("tags", ARRAY(sa.Text()), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        _created(),
        _updated(),
        sa.CheckConstraint(
            "para_category IN ('project', 'area', 'resource', 'archive') OR para_category IS NULL",
            name="ck_notes_para_category",
        ),
    )
    op.create_index("ix_notes_note_type", "notes", ["note_type"])
    op.create_index("ix_notes_updated_at", "notes", ["updated_at"])
    op.create_index(
        "ix_notes_embedding_hnsw",
        "notes",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # --- entities ------------------------------------------------------------
    op.create_table(
        "entities",
        _pk(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=True),
        sa.Column(
            "mention_count",
            sa.Integer(),
            server_default=sa.text("1"),
        ),
        sa.Column("first_seen", sa.DateTime(**_tz), nullable=True),
        sa.Column("last_seen", sa.DateTime(**_tz), nullable=True),
        sa.Column(
            "metadata",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
        ),
        _created(),
    )
    op.create_index("ix_entities_entity_type", "entities", ["entity_type"])
    op.create_index(
        "ix_entities_name_trgm",
        "entities",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )

    # --- contacts ------------------------------------------------------------
    op.create_table(
        "contacts",
        _pk(),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("tags", ARRAY(sa.Text()), nullable=True),
        sa.Column("how_we_met", sa.Text(), nullable=True),
        sa.Column(
            "interaction_frequency_days",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "relationship_score",
            sa.Float(),
            server_default=sa.text("50.0"),
        ),
        sa.Column("last_interaction_at", sa.DateTime(**_tz), nullable=True),
        _created(),
        _updated(),
    )
    op.create_index(
        "ix_contacts_relationship_score",
        "contacts",
        ["relationship_score"],
    )
    op.create_index(
        "ix_contacts_last_interaction_at",
        "contacts",
        ["last_interaction_at"],
    )

    # --- projects ------------------------------------------------------------
    op.create_table(
        "projects",
        _pk(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            server_default=sa.text("'planning'"),
        ),
        sa.Column("appetite", sa.String(50), nullable=True),
        sa.Column("deadline", sa.DateTime(**_tz), nullable=True),
        _created(),
        _updated(),
    )
    op.create_index("ix_projects_status", "projects", ["status"])

    # --- agent_actions -------------------------------------------------------
    op.create_table(
        "agent_actions",
        _pk(),
        sa.Column("agent_name", sa.String(50), nullable=False),
        sa.Column("action_type", sa.String(50), nullable=True),
        sa.Column("model_used", sa.String(50), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(100), nullable=True),
        _created(),
    )
    op.create_index(
        "ix_agent_actions_agent_name",
        "agent_actions",
        ["agent_name"],
    )
    op.create_index(
        "ix_agent_actions_created_at",
        "agent_actions",
        ["created_at"],
    )

    # --- notifications -------------------------------------------------------
    op.create_table(
        "notifications",
        _pk(),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "priority",
            sa.String(5),
            nullable=False,
            server_default=sa.text("'P2'"),
        ),
        sa.Column(
            "category",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'unread'"),
        ),
        _created(),
    )
    op.create_index("ix_notifications_status", "notifications", ["status"])
    op.create_index("ix_notifications_priority", "notifications", ["priority"])
    op.create_index(
        "ix_notifications_created_at",
        "notifications",
        ["created_at"],
    )

    # --- reviews -------------------------------------------------------------
    op.create_table(
        "reviews",
        _pk(),
        sa.Column(
            "review_type",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'weekly'"),
        ),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column(
            "content",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
        ),
        _created(),
    )
    op.create_index("ix_reviews_review_type", "reviews", ["review_type"])
    op.create_index("ix_reviews_created_at", "reviews", ["created_at"])

    # --- commitments ---------------------------------------------------------
    op.create_table(
        "commitments",
        _pk(),
        sa.Column("verbatim_text", sa.Text(), nullable=False),
        sa.Column("normalized_action", sa.Text(), nullable=False),
        sa.Column("who_committed", sa.String(100), nullable=True),
        sa.Column("who_to", sa.String(100), nullable=True),
        sa.Column("temporal_expression_raw", sa.Text(), nullable=True),
        sa.Column(
            "temporal_normalized",
            sa.DateTime(**_tz),
            nullable=True,
        ),
        sa.Column(
            "commitment_type",
            sa.String(30),
            server_default=sa.text("'promise'"),
        ),
        sa.Column(
            "confidence_score",
            sa.Float(),
            server_default=sa.text("1.0"),
        ),
        sa.Column(
            "status",
            sa.String(20),
            server_default=sa.text("'detected'"),
        ),
        _created(),
        _updated(),
    )
    op.create_index("ix_commitments_status", "commitments", ["status"])
    op.create_index("ix_commitments_created_at", "commitments", ["created_at"])
    op.create_index(
        "ix_commitments_temporal_normalized",
        "commitments",
        ["temporal_normalized"],
    )

    # --- decisions -----------------------------------------------------------
    op.create_table(
        "decisions",
        _pk(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("options_considered", ARRAY(sa.Text()), nullable=True),
        sa.Column("decision_made", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("expected_outcome", sa.Text(), nullable=True),
        sa.Column("actual_outcome", sa.Text(), nullable=True),
        sa.Column("outcome_rating", sa.Float(), nullable=True),
        sa.Column("tags", ARRAY(sa.Text()), nullable=True),
        sa.Column("review_date", sa.DateTime(**_tz), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            server_default=sa.text("'pending_review'"),
        ),
        _created(),
        _updated(),
    )
    op.create_index("ix_decisions_status", "decisions", ["status"])
    op.create_index("ix_decisions_review_date", "decisions", ["review_date"])
    op.create_index("ix_decisions_created_at", "decisions", ["created_at"])

    # --- habits --------------------------------------------------------------
    op.create_table(
        "habits",
        _pk(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "frequency",
            sa.String(20),
            server_default=sa.text("'daily'"),
        ),
        sa.Column(
            "frequency_days",
            sa.Integer(),
            server_default=sa.text("1"),
        ),
        sa.Column(
            "current_streak",
            sa.Integer(),
            server_default=sa.text("0"),
        ),
        sa.Column(
            "longest_streak",
            sa.Integer(),
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_completions",
            sa.Integer(),
            server_default=sa.text("0"),
        ),
        sa.Column("last_completed_at", sa.DateTime(**_tz), nullable=True),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
        ),
        sa.Column("tags", ARRAY(sa.Text()), nullable=True),
        _created(),
        _updated(),
    )
    op.create_index("ix_habits_active", "habits", ["active"])
    op.create_index("ix_habits_name", "habits", ["name"])

    # --- interaction_records -------------------------------------------------
    op.create_table(
        "interaction_records",
        _pk(),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("intent_type", sa.String(50), nullable=False),
        sa.Column("specialist", sa.String(50), nullable=False),
        sa.Column("routing_confidence", sa.Float(), nullable=False),
        sa.Column("response_content", sa.Text(), nullable=False),
        sa.Column("response_agent", sa.String(50), nullable=False),
        sa.Column(
            "optimizer_triggered",
            sa.Boolean(),
            server_default=sa.text("false"),
        ),
        sa.Column("optimizer_issue", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "eval_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("score_relevance", sa.Float(), nullable=True),
        sa.Column("score_actionability", sa.Float(), nullable=True),
        sa.Column("score_tone", sa.Float(), nullable=True),
        sa.Column("score_conciseness", sa.Float(), nullable=True),
        sa.Column("auto_judge_reasoning", sa.Text(), nullable=True),
        sa.Column("scored_at", sa.DateTime(**_tz), nullable=True),
        sa.Column("feedback_rating", sa.String(20), nullable=True),
        sa.Column("feedback_at", sa.DateTime(**_tz), nullable=True),
        sa.Column("deep_scores", JSONB(), nullable=True),
        sa.Column("deep_eval_reasoning", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(20), nullable=True),
        sa.Column("trace_id", sa.String(100), nullable=True),
        _created(),
        sa.CheckConstraint(
            "eval_status IN ('pending', 'auto_scored', 'deep_scored', 'skipped')",
            name="ck_interaction_records_eval_status",
        ),
        sa.CheckConstraint(
            "feedback_rating IN ('thumbs_up', 'thumbs_down') OR feedback_rating IS NULL",
            name="ck_interaction_records_feedback_rating",
        ),
    )
    op.create_index(
        "ix_interaction_records_eval_status",
        "interaction_records",
        ["eval_status"],
    )
    op.create_index(
        "ix_interaction_records_specialist",
        "interaction_records",
        ["specialist"],
    )
    op.create_index(
        "ix_interaction_records_created_at",
        "interaction_records",
        ["created_at"],
    )
    op.create_index(
        "ix_interaction_records_user_id",
        "interaction_records",
        ["user_id"],
    )

    # --- tutorial_sessions ---------------------------------------------------
    op.create_table(
        "tutorial_sessions",
        _pk(),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column(
            "work_type",
            sa.String(50),
            server_default=sa.text("'other'"),
        ),
        sa.Column("submitted_work", sa.Text(), nullable=False),
        sa.Column(
            "phase",
            sa.String(50),
            server_default=sa.text("'submitted'"),
        ),
        sa.Column("propositions", JSONB(), nullable=True),
        sa.Column("preparation", JSONB(), nullable=True),
        sa.Column("transcript", JSONB(), nullable=True),
        sa.Column("assessor_log", JSONB(), nullable=True),
        sa.Column("analysis", JSONB(), nullable=True),
        sa.Column("bloom_start", sa.String(20), nullable=True),
        sa.Column("bloom_end", sa.String(20), nullable=True),
        sa.Column("turn_count", sa.Integer(), nullable=True),
        sa.Column(
            "speaking_ratio_student_pct",
            sa.Float(),
            nullable=True,
        ),
        sa.Column("knowledge_gaps_found", sa.Integer(), nullable=True),
        sa.Column(
            "knowledge_gaps_addressed",
            sa.Integer(),
            nullable=True,
        ),
        _created(),
        sa.Column("started_at", sa.DateTime(**_tz), nullable=True),
        sa.Column("completed_at", sa.DateTime(**_tz), nullable=True),
        sa.CheckConstraint(
            "phase IN ('submitted', 'preparing', 'ready', "
            "'opening', 'dialogue', 'closing', 'analysing', "
            "'complete')",
            name="ck_tutorial_sessions_phase",
        ),
    )
    op.create_index(
        "ix_tutorial_sessions_user_id",
        "tutorial_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_tutorial_sessions_phase",
        "tutorial_sessions",
        ["phase"],
    )
    op.create_index(
        "ix_tutorial_sessions_created_at",
        "tutorial_sessions",
        ["created_at"],
    )

    # =====================================================================
    # Dependent tables (foreign keys to independent tables)
    # =====================================================================

    # --- note_links (FK -> notes) --------------------------------------------
    op.create_table(
        "note_links",
        _pk(),
        sa.Column(
            "source_note_id",
            UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "target_note_id",
            UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("link_reason", sa.Text(), nullable=True),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column(
            "auto_discovered",
            sa.Boolean(),
            server_default=sa.text("true"),
        ),
        _created(),
        sa.ForeignKeyConstraint(
            ["source_note_id"],
            ["notes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_note_id"],
            ["notes.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "source_note_id",
            "target_note_id",
            name="uq_note_link",
        ),
    )
    op.create_index(
        "ix_note_links_source_note_id",
        "note_links",
        ["source_note_id"],
    )
    op.create_index(
        "ix_note_links_target_note_id",
        "note_links",
        ["target_note_id"],
    )

    # --- entity_relationships (FK -> entities) -------------------------------
    op.create_table(
        "entity_relationships",
        _pk(),
        sa.Column(
            "source_entity_id",
            UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "target_entity_id",
            UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.String(50), nullable=False),
        sa.Column("valid_from", sa.DateTime(**_tz), nullable=True),
        sa.Column("valid_to", sa.DateTime(**_tz), nullable=True),
        _created(),
        sa.ForeignKeyConstraint(
            ["source_entity_id"],
            ["entities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"],
            ["entities.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "source_entity_id",
            "target_entity_id",
            "relationship_type",
            "valid_from",
            name="uq_entity_relationship",
        ),
    )
    op.create_index(
        "ix_entity_relationships_source_entity_id",
        "entity_relationships",
        ["source_entity_id"],
    )
    op.create_index(
        "ix_entity_relationships_target_entity_id",
        "entity_relationships",
        ["target_entity_id"],
    )

    # --- entity_mentions (FK -> entities, episodes) --------------------------
    op.create_table(
        "entity_mentions",
        _pk(),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", UUID(as_uuid=True), nullable=False),
        sa.Column("context_snippet", sa.Text(), nullable=True),
        sa.Column("mentioned_at", sa.DateTime(**_tz), nullable=True),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["episodes.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "entity_id",
            "episode_id",
            name="uq_entity_mention",
        ),
    )
    op.create_index(
        "ix_entity_mentions_entity_id",
        "entity_mentions",
        ["entity_id"],
    )
    op.create_index(
        "ix_entity_mentions_episode_id",
        "entity_mentions",
        ["episode_id"],
    )

    # --- interactions (FK -> contacts) ---------------------------------------
    op.create_table(
        "interactions",
        _pk(),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=False),
        sa.Column("interaction_type", sa.String(50), nullable=False),
        sa.Column(
            "direction",
            sa.String(20),
            server_default=sa.text("'outgoing'"),
        ),
        sa.Column(
            "channel",
            sa.String(50),
            server_default=sa.text("'manual'"),
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("topics", ARRAY(sa.Text()), nullable=True),
        sa.Column("interaction_at", sa.DateTime(**_tz), nullable=True),
        _created(),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_interactions_contact_id",
        "interactions",
        ["contact_id"],
    )

    # --- epics (FK -> projects) ----------------------------------------------
    op.create_table(
        "epics",
        _pk(),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default=sa.text("0"),
        ),
        _created(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_epics_project_id", "epics", ["project_id"])

    # --- milestones (FK -> epics) --------------------------------------------
    op.create_table(
        "milestones",
        _pk(),
        sa.Column("epic_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("success_criteria", sa.Text(), nullable=True),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default=sa.text("0"),
        ),
        _created(),
        sa.ForeignKeyConstraint(["epic_id"], ["epics.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_milestones_epic_id", "milestones", ["epic_id"])

    # --- tasks (FK -> milestones) --------------------------------------------
    op.create_table(
        "tasks",
        _pk(),
        sa.Column("milestone_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            server_default=sa.text("'backlog'"),
        ),
        sa.Column("estimate_hours", sa.Float(), nullable=True),
        sa.Column("actual_hours", sa.Float(), nullable=True),
        sa.Column("wsjf_score", sa.Float(), nullable=True),
        sa.Column("complexity", sa.String(20), nullable=True),
        sa.Column("context_tags", ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default=sa.text("0"),
        ),
        sa.Column("started_at", sa.DateTime(**_tz), nullable=True),
        sa.Column("completed_at", sa.DateTime(**_tz), nullable=True),
        _created(),
        _updated(),
        sa.ForeignKeyConstraint(
            ["milestone_id"],
            ["milestones.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_milestone_id", "tasks", ["milestone_id"])

    # --- habit_logs (FK -> habits) -------------------------------------------
    op.create_table(
        "habit_logs",
        _pk(),
        sa.Column("habit_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(**_tz),
            server_default=_ts_now,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.String(50),
            server_default=sa.text("'manual'"),
        ),
        sa.ForeignKeyConstraint(["habit_id"], ["habits.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_habit_logs_habit_id", "habit_logs", ["habit_id"])
    op.create_index(
        "ix_habit_logs_completed_at",
        "habit_logs",
        ["completed_at"],
    )


def downgrade() -> None:
    # Drop dependent tables first (reverse of creation order)
    op.drop_table("habit_logs")
    op.drop_table("tasks")
    op.drop_table("milestones")
    op.drop_table("epics")
    op.drop_table("interactions")
    op.drop_table("entity_mentions")
    op.drop_table("entity_relationships")
    op.drop_table("note_links")

    # Drop independent tables
    op.drop_table("tutorial_sessions")
    op.drop_table("interaction_records")
    op.drop_table("habits")
    op.drop_table("decisions")
    op.drop_table("commitments")
    op.drop_table("reviews")
    op.drop_table("notifications")
    op.drop_table("agent_actions")
    op.drop_table("projects")
    op.drop_table("contacts")
    op.drop_table("entities")
    op.drop_table("notes")
    op.drop_table("goals")
    op.drop_table("episodes")

    # Extensions (careful in shared databases)
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS ltree")
    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
