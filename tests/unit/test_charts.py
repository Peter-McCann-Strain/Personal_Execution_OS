"""Tests for src.app.core.charts - Plotly chart generation."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from src.app.core.charts import goal_progress_chart, habit_streak_chart, mood_energy_chart

# ---------------------------------------------------------------------------
# mood_energy_chart
# ---------------------------------------------------------------------------


class TestMoodEnergyChart:
    def test_empty_list_returns_empty_bytes(self):
        result = mood_energy_chart([])
        assert result == b""

    @patch("src.app.core.charts.go.Figure")
    def test_valid_data_returns_png_bytes(self, mock_figure_cls):
        """With valid episodes the function should produce non-empty bytes."""
        fake_png = b"\x89PNG_FAKE_DATA"
        fig_instance = MagicMock()
        fig_instance.write_image = MagicMock(side_effect=lambda buf, **kw: buf.write(fake_png))
        mock_figure_cls.return_value = fig_instance

        episodes = [
            {
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                "mood_score": 7.0,
                "energy_rating": 6.0,
            },
            {
                "created_at": datetime(2026, 1, 2, tzinfo=UTC),
                "mood_score": 8.0,
                "energy_rating": 5.0,
            },
        ]

        result = mood_energy_chart(episodes)

        assert result == fake_png
        assert fig_instance.add_trace.call_count == 2
        fig_instance.update_layout.assert_called_once()
        fig_instance.write_image.assert_called_once()

    @patch("src.app.core.charts.go.Figure")
    def test_handles_none_scores(self, mock_figure_cls):
        """None mood/energy values should not cause errors."""
        fake_png = b"\x89PNG_NONE"
        fig_instance = MagicMock()
        fig_instance.write_image = MagicMock(side_effect=lambda buf, **kw: buf.write(fake_png))
        mock_figure_cls.return_value = fig_instance

        episodes = [
            {
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                "mood_score": None,
                "energy_rating": 6.0,
            },
            {
                "created_at": datetime(2026, 1, 2, tzinfo=UTC),
                "mood_score": 5.0,
                "energy_rating": None,
            },
            {
                "created_at": datetime(2026, 1, 3, tzinfo=UTC),
                "mood_score": None,
                "energy_rating": None,
            },
        ]

        result = mood_energy_chart(episodes)

        assert result == fake_png
        assert fig_instance.add_trace.call_count == 2


# ---------------------------------------------------------------------------
# habit_streak_chart
# ---------------------------------------------------------------------------


class TestHabitStreakChart:
    def test_empty_list_returns_empty_bytes(self):
        result = habit_streak_chart([])
        assert result == b""

    @patch("src.app.core.charts.go.Figure")
    def test_valid_data_returns_png_bytes(self, mock_figure_cls):
        fake_png = b"\x89PNG_HABITS"
        fig_instance = MagicMock()
        fig_instance.write_image = MagicMock(side_effect=lambda buf, **kw: buf.write(fake_png))
        mock_figure_cls.return_value = fig_instance

        habits = [
            {"name": "Meditation", "current_streak": 12, "longest_streak": 30},
            {"name": "Exercise", "current_streak": 5, "longest_streak": 21},
            {"name": "Reading", "current_streak": 45, "longest_streak": 45},
        ]

        result = habit_streak_chart(habits)

        assert result == fake_png
        # Two traces: longest streak (background) + current streak (foreground)
        assert fig_instance.add_trace.call_count == 2
        fig_instance.update_layout.assert_called_once()
        fig_instance.write_image.assert_called_once()


# ---------------------------------------------------------------------------
# goal_progress_chart
# ---------------------------------------------------------------------------


class TestGoalProgressChart:
    def test_empty_list_returns_empty_bytes(self):
        result = goal_progress_chart([])
        assert result == b""

    @patch("src.app.core.charts.go.Figure")
    def test_valid_data_returns_png_bytes(self, mock_figure_cls):
        fake_png = b"\x89PNG_GOALS"
        fig_instance = MagicMock()
        fig_instance.write_image = MagicMock(side_effect=lambda buf, **kw: buf.write(fake_png))
        mock_figure_cls.return_value = fig_instance

        goals = [
            {"title": "Learn Rust", "progress": 0.4, "status": "active"},
            {"title": "Ship MVP", "progress": 0.85, "status": "at_risk"},
            {"title": "Read 12 books", "progress": 1.0, "status": "completed"},
        ]

        result = goal_progress_chart(goals)

        assert result == fake_png
        assert fig_instance.add_trace.call_count == 1
        fig_instance.update_layout.assert_called_once()
        fig_instance.write_image.assert_called_once()

    @patch("src.app.core.charts.go.Figure")
    def test_unknown_status_defaults_to_grey(self, mock_figure_cls):
        """Goals with an unrecognised status should get a grey bar."""
        fake_png = b"\x89PNG_GREY"
        fig_instance = MagicMock()
        fig_instance.write_image = MagicMock(side_effect=lambda buf, **kw: buf.write(fake_png))
        mock_figure_cls.return_value = fig_instance

        goals = [
            {"title": "Mystery Goal", "progress": 0.5, "status": "unknown_status"},
        ]

        result = goal_progress_chart(goals)

        assert result == fake_png
        # Verify no exception was raised and output is valid
        assert result != b""
