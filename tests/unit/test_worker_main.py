"""Tests for ARQ worker settings and entry point."""

from datetime import datetime, time
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# _local_hour_to_utc
# ---------------------------------------------------------------------------


class TestLocalHourToUtc:
    """Test timezone conversion helper."""

    def test_utc_timezone_no_offset(self):
        """UTC timezone should return the same hour."""
        from src.app.workers.main import _local_hour_to_utc

        result = _local_hour_to_utc(14, 0, "UTC")
        assert result == 14

    def test_london_matches_manual_calculation(self):
        """London timezone should match a manual datetime conversion."""
        from src.app.workers.main import _local_hour_to_utc

        result = _local_hour_to_utc(8, 0, "Europe/London")

        # Verify by computing the expected UTC hour the same way
        tz = ZoneInfo("Europe/London")
        local_dt = datetime.combine(datetime.today(), time(8, 0), tzinfo=tz)
        expected = local_dt.astimezone(ZoneInfo("UTC")).hour
        assert result == expected

    def test_new_york_offset(self):
        """New York timezone should apply correct offset."""
        from src.app.workers.main import _local_hour_to_utc

        result = _local_hour_to_utc(21, 0, "America/New_York")

        tz = ZoneInfo("America/New_York")
        local_dt = datetime.combine(datetime.today(), time(21, 0), tzinfo=tz)
        expected = local_dt.astimezone(ZoneInfo("UTC")).hour
        assert result == expected

    def test_different_minutes_same_hour(self):
        """Minutes should not affect the returned hour."""
        from src.app.workers.main import _local_hour_to_utc

        result_0 = _local_hour_to_utc(10, 0, "UTC")
        result_30 = _local_hour_to_utc(10, 30, "UTC")
        assert result_0 == result_30 == 10

    def test_midnight_conversion(self):
        """Midnight local in UTC should convert to 0."""
        from src.app.workers.main import _local_hour_to_utc

        result = _local_hour_to_utc(0, 0, "UTC")
        assert result == 0

    def test_tokyo_positive_offset(self):
        """Tokyo (UTC+9) — local 08:00 → UTC 23:00 previous day."""
        from src.app.workers.main import _local_hour_to_utc

        result = _local_hour_to_utc(8, 0, "Asia/Tokyo")

        tz = ZoneInfo("Asia/Tokyo")
        local_dt = datetime.combine(datetime.today(), time(8, 0), tzinfo=tz)
        expected = local_dt.astimezone(ZoneInfo("UTC")).hour
        assert result == expected


# ---------------------------------------------------------------------------
# startup
# ---------------------------------------------------------------------------


class TestStartup:
    """Test worker startup hook."""

    async def test_startup_initializes_context(self):
        from src.app.workers.main import startup

        mock_settings = MagicMock()
        mock_settings.telegram_configured = False
        mock_settings.llm_provider = "disabled"
        mock_settings.anthropic_api_key = SecretStr("")
        mock_settings.redis_url = SecretStr("redis://localhost:6379")
        mock_settings.database_url = SecretStr("postgresql+asyncpg://user:pass@localhost:5432/db")

        mock_engine = MagicMock()
        mock_factory = MagicMock()

        ctx: dict = {}

        with (
            patch("src.app.workers.main.get_settings", return_value=mock_settings),
            patch("src.app.workers.main.init_engine", return_value=mock_engine),
            patch("src.app.workers.main.init_session_factory", return_value=mock_factory),
            patch("src.app.workers.main.init_fatigue_manager"),
        ):
            await startup(ctx)

        assert ctx["settings"] is mock_settings
        assert ctx["bot"] is None  # telegram not configured
        assert ctx["session_factory"] is mock_factory

    async def test_startup_initializes_telegram_bot(self):
        from src.app.workers.main import startup

        mock_settings = MagicMock()
        mock_settings.telegram_configured = True
        mock_settings.llm_provider = "disabled"
        mock_settings.anthropic_api_key = SecretStr("")
        mock_settings.telegram_bot_token.get_secret_value.return_value = "123:ABC"
        mock_settings.redis_url = SecretStr("redis://localhost:6379")
        mock_settings.database_url = SecretStr("postgresql+asyncpg://user:pass@localhost:5432/db")

        ctx: dict = {}

        with (
            patch("src.app.workers.main.get_settings", return_value=mock_settings),
            patch("src.app.workers.main.Bot") as mock_bot_cls,
            patch("src.app.workers.main.init_engine", return_value=MagicMock()),
            patch("src.app.workers.main.init_session_factory", return_value=MagicMock()),
            patch("src.app.workers.main.init_fatigue_manager"),
        ):
            await startup(ctx)

        mock_bot_cls.assert_called_once_with(token="123:ABC")
        assert ctx["bot"] is mock_bot_cls.return_value

    async def test_startup_raises_on_telegram_init_failure(self):
        from src.app.workers.main import startup

        mock_settings = MagicMock()
        mock_settings.telegram_configured = True
        mock_settings.telegram_bot_token.get_secret_value.side_effect = RuntimeError("bad token")
        mock_settings.redis_url = SecretStr("redis://localhost:6379")
        mock_settings.database_url = SecretStr("postgresql+asyncpg://user:pass@localhost:5432/db")

        ctx: dict = {}

        with (
            patch("src.app.workers.main.get_settings", return_value=mock_settings),
            patch("src.app.workers.main.init_engine", return_value=MagicMock()),
            patch("src.app.workers.main.init_session_factory", return_value=MagicMock()),
            patch("src.app.workers.main.init_fatigue_manager"),
            pytest.raises(Exception, match="Worker Telegram initialization failed: bad token"),
        ):
            await startup(ctx)


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    """Test worker shutdown hook."""

    async def test_shutdown_closes_bot_and_engine(self):
        from src.app.workers.main import shutdown

        mock_bot = AsyncMock()
        ctx = {"bot": mock_bot}

        with patch(
            "src.app.persistence.database.close_engine", new_callable=AsyncMock
        ) as mock_close:
            await shutdown(ctx)

        mock_bot.session.close.assert_awaited_once()
        mock_close.assert_awaited_once()

    async def test_shutdown_no_bot(self):
        from src.app.workers.main import shutdown

        ctx: dict = {}

        with patch(
            "src.app.persistence.database.close_engine", new_callable=AsyncMock
        ) as mock_close:
            await shutdown(ctx)

        mock_close.assert_awaited_once()

    async def test_shutdown_handles_bot_close_failure(self):
        from src.app.workers.main import shutdown

        mock_bot = AsyncMock()
        mock_bot.session.close.side_effect = RuntimeError("close failed")
        ctx = {"bot": mock_bot}

        with patch(
            "src.app.persistence.database.close_engine", new_callable=AsyncMock
        ) as mock_close:
            # Should not raise
            await shutdown(ctx)

        mock_close.assert_awaited_once()


# ---------------------------------------------------------------------------
# WorkerSettings
# ---------------------------------------------------------------------------


class TestWorkerSettings:
    """Test WorkerSettings configuration."""

    def test_worker_settings_has_required_attributes(self):
        from src.app.workers.main import WorkerSettings

        assert WorkerSettings.on_startup is not None
        assert WorkerSettings.on_shutdown is not None
        assert WorkerSettings.max_jobs == 5
        assert WorkerSettings.max_tries == 3
        assert WorkerSettings.job_timeout == 300

    def test_worker_settings_has_cron_jobs(self):
        from src.app.workers.main import WorkerSettings

        # Cron job count grows as new scheduled workers land (schema-drift
        # alerts, daily eval pipeline, etc). Assert we have *at least* the
        # foundational set instead of pinning the exact count.
        assert len(WorkerSettings.cron_jobs) >= 14

    def test_disabled_provider_omits_model_cron_jobs(self):
        from src.app.workers.main import _build_cron_schedule
        from src.app.workers.scheduled import morning_briefing, weekly_review
        from src.app.workers.scheduled_actions_runtime import run_due_scheduled_actions

        settings = MagicMock()
        settings.user_timezone = "UTC"
        settings.llm_configured = False

        with patch("src.app.workers.main.get_settings", return_value=settings):
            coroutines = {job.coroutine for job in _build_cron_schedule()}

        assert morning_briefing not in coroutines
        assert weekly_review not in coroutines
        assert run_due_scheduled_actions not in coroutines

    def test_configured_provider_does_not_imply_proactive_model_cron_jobs(self):
        from src.app.workers.main import _build_cron_schedule
        from src.app.workers.scheduled import morning_briefing, weekly_review
        from src.app.workers.scheduled_actions_runtime import run_due_scheduled_actions

        settings = MagicMock()
        settings.user_timezone = "UTC"
        settings.llm_configured = True
        settings.proactive_automation_enabled = False

        with patch("src.app.workers.main.get_settings", return_value=settings):
            coroutines = {job.coroutine for job in _build_cron_schedule()}

        assert morning_briefing not in coroutines
        assert weekly_review not in coroutines
        assert run_due_scheduled_actions not in coroutines

    def test_proactive_model_cron_jobs_require_explicit_opt_in(self):
        from src.app.workers.main import _build_cron_schedule
        from src.app.workers.scheduled import morning_briefing, weekly_review
        from src.app.workers.scheduled_actions_runtime import run_due_scheduled_actions

        settings = MagicMock()
        settings.user_timezone = "UTC"
        settings.llm_configured = True
        settings.proactive_automation_enabled = True
        settings.auto_judge_cron_interval_hours = 4

        with patch("src.app.workers.main.get_settings", return_value=settings):
            coroutines = {job.coroutine for job in _build_cron_schedule()}

        assert morning_briefing in coroutines
        assert weekly_review in coroutines
        assert run_due_scheduled_actions in coroutines

    def test_worker_settings_has_functions(self):
        from src.app.workers.main import WorkerSettings

        assert len(WorkerSettings.functions) == 1

    def test_redis_settings_from_env(self):
        from src.app.workers.main import WorkerSettings

        with patch("src.app.workers.main.get_settings") as mock_gs:
            mock_gs.return_value.redis_url = SecretStr("redis://localhost:6379")
            with patch("arq.connections.RedisSettings.from_dsn") as mock_from_dsn:
                WorkerSettings.redis_settings()
                mock_from_dsn.assert_called_once_with("redis://localhost:6379")


# ---------------------------------------------------------------------------
# Additional coverage: run_pattern_detection
# ---------------------------------------------------------------------------


class TestRunPatternDetection:
    async def test_run_pattern_detection_calls_detect(self):
        """run_pattern_detection delegates to detect_patterns (line 101)."""
        ctx = {"session_factory": MagicMock()}

        with patch(
            "src.app.workers.main.detect_patterns",
            new_callable=AsyncMock,
        ) as mock_detect:
            from src.app.workers.main import run_pattern_detection

            await run_pattern_detection(ctx)

        mock_detect.assert_awaited_once_with(ctx)
