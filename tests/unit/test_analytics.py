"""Tests for src.app.core.analytics — shared metric aggregation helpers."""

from src.app.core.analytics import average_metric


class TestAverageMetric:
    def test_returns_average_of_valid_values(self):
        episodes = [{"mood_score": 8}, {"mood_score": 6}, {"mood_score": 4}]
        assert average_metric(episodes, "mood_score") == 6.0

    def test_ignores_none_values(self):
        episodes = [{"mood_score": 10}, {"mood_score": None}, {"mood_score": 6}]
        assert average_metric(episodes, "mood_score") == 8.0

    def test_returns_none_when_all_none(self):
        episodes = [{"mood_score": None}, {"mood_score": None}]
        assert average_metric(episodes, "mood_score") is None

    def test_returns_none_for_empty_list(self):
        assert average_metric([], "mood_score") is None

    def test_single_value(self):
        assert average_metric([{"energy": 7.5}], "energy") == 7.5

    def test_works_with_different_keys(self):
        episodes = [{"energy_rating": 3}, {"energy_rating": 5}]
        assert average_metric(episodes, "energy_rating") == 4.0
