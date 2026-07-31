"""Tests for evaluation-related configuration settings."""

from __future__ import annotations


class TestEvalConfigDefaults:
    """Verify evaluation config defaults are set correctly."""

    def test_auto_judge_enabled_default(self):
        """auto_judge_enabled is opt-in to avoid surprise model spend."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.auto_judge_enabled is False

    def test_auto_judge_model_default(self):
        """auto_judge_model defaults to Sonnet (upgraded from Haiku for quality accuracy)."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.auto_judge_model == "claude-sonnet-4-6"

    def test_auto_judge_max_tokens_default(self):
        """auto_judge_max_tokens defaults to 512."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.auto_judge_max_tokens == 512

    def test_auto_judge_batch_size_default(self):
        """auto_judge_batch_size defaults to 50."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.auto_judge_batch_size == 50

    def test_auto_judge_cron_interval_default(self):
        """auto_judge_cron_interval_hours defaults to 4."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.auto_judge_cron_interval_hours == 4

    def test_quality_alert_threshold_default(self):
        """quality_alert_threshold defaults to 0.5."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.quality_alert_threshold == 0.5

    def test_quality_alert_window_default(self):
        """quality_alert_window_hours defaults to 24."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.quality_alert_window_hours == 24

    def test_quality_alert_baseline_days_default(self):
        """quality_alert_baseline_days defaults to 7."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.quality_alert_baseline_days == 7

    def test_evaluation_export_dir_default(self):
        """evaluation_export_dir defaults to data/evaluation/exports."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.evaluation_export_dir == "data/evaluation/exports"

    def test_feedback_enabled_default(self):
        """feedback_enabled defaults to True."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.feedback_enabled is True

    def test_startup_preflight_enabled_default(self):
        """startup_preflight_enabled defaults to True."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.startup_preflight_enabled is True

    def test_startup_preflight_fail_fast_default(self):
        """startup_preflight_fail_fast defaults to False."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.startup_preflight_fail_fast is False

    def test_runtime_eval_mode_default(self):
        """runtime_eval_mode defaults to async."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.runtime_eval_mode == "async"

    def test_runtime_eval_sample_rate_default(self):
        """runtime_eval_sample_rate defaults to 1.0."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.runtime_eval_sample_rate == 1.0

    def test_runtime_eval_optimizer_enabled_default(self):
        """runtime_eval_optimizer_enabled defaults to False."""
        from src.app.config import get_settings

        settings = get_settings()
        assert settings.runtime_eval_optimizer_enabled is False
