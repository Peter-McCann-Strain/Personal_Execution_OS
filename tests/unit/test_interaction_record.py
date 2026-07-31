"""Tests for InteractionRecord ORM model definition."""

from sqlalchemy import inspect

from src.app.persistence.models import InteractionRecord


class TestInteractionRecordModel:
    def test_tablename(self):
        """InteractionRecord uses 'interaction_records' table."""
        assert InteractionRecord.__tablename__ == "interaction_records"

    def test_primary_key_is_uuid(self):
        """Primary key is a UUID column."""
        mapper = inspect(InteractionRecord)
        pk_cols = [c.name for c in mapper.primary_key]
        assert pk_cols == ["id"]

    def test_all_required_columns_exist(self):
        """All expected columns are defined on the model."""
        mapper = inspect(InteractionRecord)
        column_names = {c.key for c in mapper.columns}
        required = {
            "id",
            "user_id",
            "user_message",
            "source",
            "intent_type",
            "specialist",
            "routing_confidence",
            "response_content",
            "response_agent",
            "optimizer_triggered",
            "optimizer_issue",
            "duration_ms",
            "eval_status",
            "score_relevance",
            "score_actionability",
            "score_tone",
            "score_conciseness",
            "auto_judge_reasoning",
            "scored_at",
            "feedback_rating",
            "feedback_at",
            "trace_id",
            "created_at",
        }
        assert required.issubset(column_names), f"Missing: {required - column_names}"

    def test_nullable_score_columns(self):
        """Score columns are nullable (populated later by auto-judge)."""
        mapper = inspect(InteractionRecord)
        cols = {c.key: c for c in mapper.columns}
        for score_col in [
            "score_relevance",
            "score_actionability",
            "score_tone",
            "score_conciseness",
        ]:
            assert cols[score_col].nullable is True, f"{score_col} should be nullable"

    def test_nullable_feedback_columns(self):
        """Feedback columns are nullable (populated later by user)."""
        mapper = inspect(InteractionRecord)
        cols = {c.key: c for c in mapper.columns}
        assert cols["feedback_rating"].nullable is True
        assert cols["feedback_at"].nullable is True

    def test_non_nullable_required_columns(self):
        """Core request/response columns are NOT nullable."""
        mapper = inspect(InteractionRecord)
        cols = {c.key: c for c in mapper.columns}
        non_nullable = [
            "user_id",
            "user_message",
            "source",
            "intent_type",
            "specialist",
            "routing_confidence",
            "response_content",
            "response_agent",
            "duration_ms",
            "eval_status",
        ]
        for col_name in non_nullable:
            assert cols[col_name].nullable is False, f"{col_name} should NOT be nullable"

    def test_default_eval_status(self):
        """eval_status column has a default of 'pending'."""
        mapper = inspect(InteractionRecord)
        col = mapper.columns["eval_status"]
        assert col.default.arg == "pending"

    def test_default_optimizer_triggered(self):
        """optimizer_triggered column has a default of False."""
        mapper = inspect(InteractionRecord)
        col = mapper.columns["optimizer_triggered"]
        assert col.default.arg is False

    def test_default_id_is_uuid(self):
        """Default ID factory produces valid UUIDs."""
        mapper = inspect(InteractionRecord)
        id_col = mapper.columns["id"]
        # Verify the default callable is uuid4 (compare by name since module references differ)
        assert id_col.default is not None
        assert callable(id_col.default.arg)
        assert id_col.default.arg.__name__ == "uuid4"

    def test_table_args_has_indexes(self):
        """Table args include expected indexes."""
        table_args = InteractionRecord.__table_args__
        index_names = {
            arg.name for arg in table_args if hasattr(arg, "name") and "ix_" in (arg.name or "")
        }
        expected = {
            "ix_interaction_records_eval_status",
            "ix_interaction_records_specialist",
            "ix_interaction_records_created_at",
            "ix_interaction_records_user_id",
        }
        assert expected.issubset(index_names), f"Missing indexes: {expected - index_names}"

    def test_table_args_has_check_constraints(self):
        """Table args include check constraints for eval_status and feedback_rating."""
        table_args = InteractionRecord.__table_args__
        constraint_names = {
            arg.name for arg in table_args if hasattr(arg, "name") and "ck_" in (arg.name or "")
        }
        assert "ck_interaction_records_eval_status" in constraint_names
        assert "ck_interaction_records_feedback_rating" in constraint_names
