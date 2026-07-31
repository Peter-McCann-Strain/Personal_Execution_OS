"""Tests for evaluation-related constants — EvalStatus and FeedbackRating."""

from src.app.domain.constants import EvalStatus, FeedbackRating


class TestEvalStatus:
    def test_all_values_present(self):
        """EvalStatus has exactly 4 lifecycle states."""
        values = {s.value for s in EvalStatus}
        assert values == {"pending", "auto_scored", "deep_scored", "skipped"}

    def test_string_conversion(self):
        """EvalStatus members convert to their string values."""
        assert str(EvalStatus.PENDING) == "pending"
        assert str(EvalStatus.AUTO_SCORED) == "auto_scored"
        assert str(EvalStatus.DEEP_SCORED) == "deep_scored"
        assert str(EvalStatus.SKIPPED) == "skipped"

    def test_is_strenum(self):
        """EvalStatus members are valid strings (StrEnum)."""
        assert EvalStatus.PENDING == "pending"
        assert isinstance(EvalStatus.AUTO_SCORED, str)


class TestFeedbackRating:
    def test_all_values_present(self):
        """FeedbackRating has exactly 2 options."""
        values = {f.value for f in FeedbackRating}
        assert values == {"thumbs_up", "thumbs_down"}

    def test_string_conversion(self):
        """FeedbackRating members convert to their string values."""
        assert str(FeedbackRating.THUMBS_UP) == "thumbs_up"
        assert str(FeedbackRating.THUMBS_DOWN) == "thumbs_down"
