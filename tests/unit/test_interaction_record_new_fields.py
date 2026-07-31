"""Tests for new InteractionRecord fields: deep_scores, deep_eval_reasoning, prompt_version."""

from src.app.persistence.models import InteractionRecord


class TestDeepScoresField:
    """Test the deep_scores JSONB field on InteractionRecord."""

    def test_deep_scores_column_exists(self):
        mapper = InteractionRecord.__table__
        assert "deep_scores" in mapper.columns

    def test_deep_scores_is_nullable(self):
        col = InteractionRecord.__table__.columns["deep_scores"]
        assert col.nullable is True

    def test_deep_scores_type_is_jsonb(self):
        from sqlalchemy.dialects.postgresql import JSONB

        col = InteractionRecord.__table__.columns["deep_scores"]
        assert isinstance(col.type, JSONB)


class TestDeepEvalReasoningField:
    """Test the deep_eval_reasoning Text field."""

    def test_column_exists(self):
        mapper = InteractionRecord.__table__
        assert "deep_eval_reasoning" in mapper.columns

    def test_is_nullable(self):
        col = InteractionRecord.__table__.columns["deep_eval_reasoning"]
        assert col.nullable is True


class TestPromptVersionField:
    """Test the prompt_version field."""

    def test_column_exists(self):
        mapper = InteractionRecord.__table__
        assert "prompt_version" in mapper.columns

    def test_is_nullable(self):
        col = InteractionRecord.__table__.columns["prompt_version"]
        assert col.nullable is True

    def test_max_length(self):
        col = InteractionRecord.__table__.columns["prompt_version"]
        assert col.type.length == 20
