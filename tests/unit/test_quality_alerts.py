"""Tests for quality degradation alert worker."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_settings() -> MagicMock:
    """Create mock settings for quality alerts."""
    settings = MagicMock()
    settings.quality_alerts_enabled = True
    settings.quality_alert_threshold = 0.5
    settings.quality_alert_window_hours = 24
    settings.quality_alert_baseline_days = 7
    settings.allowed_user_ids = [12345]
    settings.user_timezone = "Europe/London"
    settings.github_issue_filer_enabled = False
    return settings


def _make_session_factory(session: AsyncMock):
    """Create a mock async session factory."""

    @asynccontextmanager
    async def factory():
        yield session

    return factory


class TestRunQualityAlerts:
    @pytest.mark.asyncio
    async def test_no_bot_skips_alerts(self):
        """Worker exits if no Telegram bot is available."""
        ctx = {
            "settings": _make_settings(),
            "bot": None,
            "session_factory": AsyncMock(),
        }

        from src.app.workers.quality_alerts import run_quality_alerts

        # Should not raise
        await run_quality_alerts(ctx)

    @pytest.mark.asyncio
    async def test_no_degradation_no_alert(self):
        """No alert is sent when scores are stable."""
        bot = AsyncMock()
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(),
            "bot": bot,
            "session_factory": _make_session_factory(session),
        }

        # Recent and baseline have similar scores — no degradation
        recent = [
            {
                "specialist": "diary",
                "avg_relevance": 0.85,
                "avg_actionability": 0.80,
                "avg_tone": 0.90,
                "avg_conciseness": 0.82,
                "count": 10,
            }
        ]
        baseline = [
            {
                "specialist": "diary",
                "avg_relevance": 0.86,
                "avg_actionability": 0.81,
                "avg_tone": 0.89,
                "avg_conciseness": 0.83,
                "count": 50,
            }
        ]

        with patch(
            "src.app.workers.quality_alerts.get_specialist_score_averages",
            new_callable=AsyncMock,
            side_effect=[recent, baseline],
        ):
            from src.app.workers.quality_alerts import run_quality_alerts

            await run_quality_alerts(ctx)

        bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_degradation_sends_alert(self):
        """Alert is sent when a score dimension drops beyond threshold."""
        bot = AsyncMock()
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(),
            "bot": bot,
            "session_factory": _make_session_factory(session),
        }

        # Recent relevance dropped 0.6 from baseline (threshold is 0.5)
        recent = [
            {
                "specialist": "diary",
                "avg_relevance": 0.25,
                "avg_actionability": 0.80,
                "avg_tone": 0.90,
                "avg_conciseness": 0.82,
                "count": 10,
            }
        ]
        baseline = [
            {
                "specialist": "diary",
                "avg_relevance": 0.85,
                "avg_actionability": 0.81,
                "avg_tone": 0.89,
                "avg_conciseness": 0.83,
                "count": 50,
            }
        ]

        with patch(
            "src.app.workers.quality_alerts.get_specialist_score_averages",
            new_callable=AsyncMock,
            side_effect=[recent, baseline],
        ):
            from src.app.workers.quality_alerts import run_quality_alerts

            await run_quality_alerts(ctx)

        bot.send_message.assert_awaited_once()
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 12345
        assert "diary" in call_kwargs["text"]
        assert "Relevance" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_skips_small_sample_sizes(self):
        """No alert when sample sizes are too small to be meaningful."""
        bot = AsyncMock()
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(),
            "bot": bot,
            "session_factory": _make_session_factory(session),
        }

        # Small sample sizes — should skip
        recent = [
            {
                "specialist": "diary",
                "avg_relevance": 0.25,
                "avg_actionability": 0.80,
                "avg_tone": 0.90,
                "avg_conciseness": 0.82,
                "count": 2,
            }
        ]  # < 3
        baseline = [
            {
                "specialist": "diary",
                "avg_relevance": 0.85,
                "avg_actionability": 0.81,
                "avg_tone": 0.89,
                "avg_conciseness": 0.83,
                "count": 50,
            }
        ]

        with patch(
            "src.app.workers.quality_alerts.get_specialist_score_averages",
            new_callable=AsyncMock,
            side_effect=[recent, baseline],
        ):
            from src.app.workers.quality_alerts import run_quality_alerts

            await run_quality_alerts(ctx)

        bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_agents_degraded(self):
        """Alert includes all degraded agents/dimensions."""
        bot = AsyncMock()
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(),
            "bot": bot,
            "session_factory": _make_session_factory(session),
        }

        recent = [
            {
                "specialist": "diary",
                "avg_relevance": 0.20,
                "avg_actionability": 0.80,
                "avg_tone": 0.90,
                "avg_conciseness": 0.82,
                "count": 10,
            },
            {
                "specialist": "memory",
                "avg_relevance": 0.80,
                "avg_actionability": 0.10,
                "avg_tone": 0.90,
                "avg_conciseness": 0.82,
                "count": 8,
            },
        ]
        baseline = [
            {
                "specialist": "diary",
                "avg_relevance": 0.85,
                "avg_actionability": 0.81,
                "avg_tone": 0.89,
                "avg_conciseness": 0.83,
                "count": 50,
            },
            {
                "specialist": "memory",
                "avg_relevance": 0.82,
                "avg_actionability": 0.75,
                "avg_tone": 0.88,
                "avg_conciseness": 0.80,
                "count": 40,
            },
        ]

        with patch(
            "src.app.workers.quality_alerts.get_specialist_score_averages",
            new_callable=AsyncMock,
            side_effect=[recent, baseline],
        ):
            from src.app.workers.quality_alerts import run_quality_alerts

            await run_quality_alerts(ctx)

        bot.send_message.assert_awaited_once()
        alert_text = bot.send_message.call_args.kwargs["text"]
        assert "diary" in alert_text
        assert "memory" in alert_text
        assert "Relevance" in alert_text
        assert "Actionability" in alert_text

    @pytest.mark.asyncio
    async def test_no_user_ids_skips_alert(self):
        """No alert when no user IDs are configured."""
        bot = AsyncMock()
        session = AsyncMock()

        settings = _make_settings()
        settings.allowed_user_ids = []

        ctx = {
            "settings": settings,
            "bot": bot,
            "session_factory": _make_session_factory(session),
        }

        recent = [
            {
                "specialist": "diary",
                "avg_relevance": 0.20,
                "avg_actionability": 0.80,
                "avg_tone": 0.90,
                "avg_conciseness": 0.82,
                "count": 10,
            }
        ]
        baseline = [
            {
                "specialist": "diary",
                "avg_relevance": 0.85,
                "avg_actionability": 0.81,
                "avg_tone": 0.89,
                "avg_conciseness": 0.83,
                "count": 50,
            }
        ]

        with patch(
            "src.app.workers.quality_alerts.get_specialist_score_averages",
            new_callable=AsyncMock,
            side_effect=[recent, baseline],
        ):
            from src.app.workers.quality_alerts import run_quality_alerts

            await run_quality_alerts(ctx)

        bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_baseline_skips_specialist(self):
        """Recent specialists without a baseline should be ignored."""
        bot = AsyncMock()
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(),
            "bot": bot,
            "session_factory": _make_session_factory(session),
        }

        recent = [
            {
                "specialist": "diary",
                "avg_custom": 0.20,
                "avg_relevance": 0.20,
                "avg_actionability": 0.80,
                "avg_tone": 0.90,
                "avg_conciseness": 0.82,
                "count": 10,
            }
        ]
        baseline = []

        with patch(
            "src.app.workers.quality_alerts.get_specialist_score_averages",
            new_callable=AsyncMock,
            side_effect=[recent, baseline],
        ):
            from src.app.workers.quality_alerts import run_quality_alerts

            await run_quality_alerts(ctx)

        bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_null_dimension_values_are_skipped(self):
        """Missing metric values should not create false alerts."""
        bot = AsyncMock()
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(),
            "bot": bot,
            "session_factory": _make_session_factory(session),
        }

        recent = [
            {
                "specialist": "diary",
                "avg_relevance": None,
                "avg_actionability": 0.10,
                "avg_tone": 0.90,
                "avg_conciseness": 0.82,
                "count": 10,
            }
        ]
        baseline = [
            {
                "specialist": "diary",
                "avg_relevance": 0.85,
                "avg_actionability": None,
                "avg_tone": 0.89,
                "avg_conciseness": 0.83,
                "count": 50,
            }
        ]

        with patch(
            "src.app.workers.quality_alerts.get_specialist_score_averages",
            new_callable=AsyncMock,
            side_effect=[recent, baseline],
        ):
            from src.app.workers.quality_alerts import run_quality_alerts

            await run_quality_alerts(ctx)

        bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_failure_is_logged_and_raised(self):
        """Telegram send failures should be logged and propagated."""
        bot = AsyncMock()
        bot.send_message.side_effect = RuntimeError("telegram down")
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(),
            "bot": bot,
            "session_factory": _make_session_factory(session),
        }

        recent = [
            {
                "specialist": "diary",
                "avg_custom": 0.20,
                "avg_relevance": 0.20,
                "avg_actionability": 0.80,
                "avg_tone": 0.90,
                "avg_conciseness": 0.82,
                "count": 10,
            }
        ]
        baseline = [
            {
                "specialist": "diary",
                "avg_custom": 0.85,
                "avg_relevance": 0.85,
                "avg_actionability": 0.81,
                "avg_tone": 0.89,
                "avg_conciseness": 0.83,
                "count": 50,
            }
        ]

        with (
            patch(
                "src.app.workers.quality_alerts.get_specialist_score_averages",
                new_callable=AsyncMock,
                side_effect=[recent, baseline],
            ),
            patch("src.app.workers.quality_alerts.logger.exception") as mock_exception,
        ):
            from src.app.workers.quality_alerts import run_quality_alerts

            with pytest.raises(RuntimeError, match="telegram down"):
                await run_quality_alerts(ctx)

        mock_exception.assert_called_once_with("quality_alert_send_failed")

    @pytest.mark.asyncio
    async def test_unknown_dimension_uses_raw_label(self):
        """Unknown score dimensions should fall back to the raw key name."""
        bot = AsyncMock()
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(),
            "bot": bot,
            "session_factory": _make_session_factory(session),
        }

        recent = [
            {
                "specialist": "diary",
                "avg_custom": 0.20,
                "avg_relevance": 0.20,
                "avg_actionability": 0.80,
                "avg_tone": 0.90,
                "avg_conciseness": 0.82,
                "count": 10,
            }
        ]
        baseline = [
            {
                "specialist": "diary",
                "avg_custom": 0.85,
                "avg_relevance": 0.85,
                "avg_actionability": 0.81,
                "avg_tone": 0.89,
                "avg_conciseness": 0.83,
                "count": 50,
            }
        ]

        with (
            patch(
                "src.app.workers.quality_alerts.get_specialist_score_averages",
                new_callable=AsyncMock,
                side_effect=[recent, baseline],
            ),
            patch("src.app.workers.quality_alerts._SCORE_DIMENSIONS", ("avg_custom",)),
        ):
            from src.app.workers.quality_alerts import run_quality_alerts

            await run_quality_alerts(ctx)

        alert_text = bot.send_message.call_args.kwargs["text"]
        assert "avg_custom" in alert_text
