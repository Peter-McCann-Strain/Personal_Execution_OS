"""Tests for the daily evaluation pipeline worker."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_settings(tmp_path: Path, *, enabled: bool = True, min_samples: int = 2) -> MagicMock:
    """Mock Settings pointing exports into tmp_path."""
    settings = MagicMock()
    settings.eval_pipeline_enabled = enabled
    settings.eval_pipeline_min_samples = min_samples
    settings.evaluation_export_dir = str(tmp_path / "data" / "evaluation" / "exports")
    settings.allowed_user_ids = [42]
    return settings


def _session_factory(session: AsyncMock):
    """Async context manager yielding the provided session."""

    @asynccontextmanager
    async def factory():
        yield session

    return factory


def _make_record(
    *,
    specialist: str = "diary",
    user_message: str = "How was my day?",
    response_content: str = "You had three meetings and finished two tasks.",
    score_relevance: float | None = 0.90,
    score_actionability: float | None = 0.85,
    score_tone: float | None = 0.88,
    score_conciseness: float | None = 0.80,
    reasoning: str = "Clear and grounded.",
    feedback_rating: str | None = None,
) -> MagicMock:
    record = MagicMock()
    record.id = uuid4()
    record.specialist = specialist
    record.user_message = user_message
    record.response_content = response_content
    record.score_relevance = score_relevance
    record.score_actionability = score_actionability
    record.score_tone = score_tone
    record.score_conciseness = score_conciseness
    record.auto_judge_reasoning = reasoning
    record.feedback_rating = feedback_rating
    record.created_at = datetime.now(UTC)
    return record


def _avg_row(
    specialist: str,
    *,
    rel: float | None = 0.88,
    act: float | None = 0.84,
    tone: float | None = 0.90,
    conc: float | None = 0.82,
    count: int = 10,
) -> dict:
    return {
        "specialist": specialist,
        "avg_relevance": rel,
        "avg_actionability": act,
        "avg_tone": tone,
        "avg_conciseness": conc,
        "count": count,
    }


def _expected_eval_root(tmp_path: Path) -> Path:
    return tmp_path / "data" / "evaluation"


class TestRunDailyEvalPipeline:
    @pytest.mark.asyncio
    async def test_writes_exports_failures_and_report(self, tmp_path: Path):
        """Happy path: files land in the expected dirs and Telegram is called."""
        bot = AsyncMock()

        records = [
            _make_record(specialist="diary"),
            _make_record(specialist="diary", score_relevance=0.92),
            # A failure on the memory agent (< 3.0/5 == < 0.6/1 on one dim)
            _make_record(
                specialist="memory",
                score_relevance=0.40,
                score_actionability=0.85,
                score_tone=0.80,
                score_conciseness=0.75,
            ),
            _make_record(specialist="memory"),
        ]

        today_rows = [
            _avg_row("diary", rel=0.91, count=2),
            _avg_row("memory", rel=0.62, act=0.85, tone=0.80, conc=0.77, count=2),
        ]
        baseline_rows = [
            _avg_row("diary", rel=0.90, count=40),
            _avg_row("memory", rel=0.88, act=0.84, tone=0.88, conc=0.82, count=30),
        ]

        ctx = {
            "settings": _make_settings(tmp_path),
            "bot": bot,
            "session_factory": _session_factory(AsyncMock()),
        }

        with (
            patch(
                "src.app.workers.eval_pipeline.get_interactions_for_export",
                new_callable=AsyncMock,
                return_value=records,
            ),
            patch(
                "src.app.workers.eval_pipeline.get_specialist_score_averages",
                new_callable=AsyncMock,
                side_effect=[today_rows, baseline_rows],
            ),
        ):
            from src.app.workers.eval_pipeline import run_daily_eval_pipeline

            await run_daily_eval_pipeline(ctx)

        root = _expected_eval_root(tmp_path)
        exports = list((root / "exports").glob("*_diary.md"))
        assert len(exports) == 1
        memory_exports = list((root / "exports").glob("*_memory.md"))
        assert len(memory_exports) == 1

        # Failure file written for memory, none for diary
        failure_files = list((root / "failures").glob("*.md"))
        assert len(failure_files) == 1
        assert "memory" in failure_files[0].name

        # Summary report written
        reports = list((root / "reports").glob("*_summary.md"))
        assert len(reports) == 1
        report_text = reports[0].read_text(encoding="utf-8")
        assert "diary" in report_text
        assert "memory" in report_text
        # Regression row for memory relevance (0.88 -> 0.62 == 1.3/5 drop)
        assert "Regressions" in report_text
        assert "memory" in report_text
        # YAML frontmatter at top
        assert report_text.startswith("---")
        assert "n_samples:" in report_text

        # Telegram sent to first allowed user with the right shape
        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.call_args.kwargs
        assert kwargs["chat_id"] == 42
        assert "Eval Summary" in kwargs["text"]
        assert "Diary" in kwargs["text"]

    @pytest.mark.asyncio
    async def test_export_file_starts_with_frontmatter(self, tmp_path: Path):
        """Per-agent export file begins with a YAML frontmatter block."""
        records = [_make_record(specialist="diary"), _make_record(specialist="diary")]

        ctx = {
            "settings": _make_settings(tmp_path),
            "bot": None,
            "session_factory": _session_factory(AsyncMock()),
        }

        with (
            patch(
                "src.app.workers.eval_pipeline.get_interactions_for_export",
                new_callable=AsyncMock,
                return_value=records,
            ),
            patch(
                "src.app.workers.eval_pipeline.get_specialist_score_averages",
                new_callable=AsyncMock,
                side_effect=[[_avg_row("diary", count=2)], []],
            ),
        ):
            from src.app.workers.eval_pipeline import run_daily_eval_pipeline

            await run_daily_eval_pipeline(ctx)

        exports = list((_expected_eval_root(tmp_path) / "exports").glob("*_diary.md"))
        assert len(exports) == 1
        text = exports[0].read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "date:" in text
        assert "agent: diary" in text
        assert "n_samples: 2" in text
        # Mean scores block must be present
        assert "mean_scores:" in text

    @pytest.mark.asyncio
    async def test_no_telegram_when_bot_missing(self, tmp_path: Path):
        """When no bot is configured, files are still written and we don't crash."""
        ctx = {
            "settings": _make_settings(tmp_path),
            "bot": None,
            "session_factory": _session_factory(AsyncMock()),
        }

        with (
            patch(
                "src.app.workers.eval_pipeline.get_interactions_for_export",
                new_callable=AsyncMock,
                return_value=[_make_record()],
            ),
            patch(
                "src.app.workers.eval_pipeline.get_specialist_score_averages",
                new_callable=AsyncMock,
                side_effect=[[_avg_row("diary", count=1)], []],
            ),
        ):
            from src.app.workers.eval_pipeline import run_daily_eval_pipeline

            # Should not raise
            await run_daily_eval_pipeline(ctx)

        reports = list((_expected_eval_root(tmp_path) / "reports").glob("*_summary.md"))
        assert len(reports) == 1

    @pytest.mark.asyncio
    async def test_disabled_is_noop(self, tmp_path: Path):
        """When eval_pipeline_enabled=False, nothing happens."""
        ctx = {
            "settings": _make_settings(tmp_path, enabled=False),
            "bot": AsyncMock(),
            "session_factory": _session_factory(AsyncMock()),
        }

        with (
            patch(
                "src.app.workers.eval_pipeline.get_interactions_for_export",
                new_callable=AsyncMock,
            ) as fetch,
            patch(
                "src.app.workers.eval_pipeline.get_specialist_score_averages",
                new_callable=AsyncMock,
            ),
        ):
            from src.app.workers.eval_pipeline import run_daily_eval_pipeline

            await run_daily_eval_pipeline(ctx)

            fetch.assert_not_called()

        assert not (_expected_eval_root(tmp_path) / "reports").exists()

    @pytest.mark.asyncio
    async def test_telegram_failure_does_not_crash(self, tmp_path: Path):
        """A Telegram send error is logged but the pipeline still completes."""
        bot = AsyncMock()
        bot.send_message.side_effect = RuntimeError("telegram down")

        ctx = {
            "settings": _make_settings(tmp_path),
            "bot": bot,
            "session_factory": _session_factory(AsyncMock()),
        }

        with (
            patch(
                "src.app.workers.eval_pipeline.get_interactions_for_export",
                new_callable=AsyncMock,
                return_value=[_make_record()],
            ),
            patch(
                "src.app.workers.eval_pipeline.get_specialist_score_averages",
                new_callable=AsyncMock,
                side_effect=[[_avg_row("diary", count=1)], []],
            ),
        ):
            from src.app.workers.eval_pipeline import run_daily_eval_pipeline

            # Should not raise — failure is swallowed after logging
            await run_daily_eval_pipeline(ctx)

        reports = list((_expected_eval_root(tmp_path) / "reports").glob("*_summary.md"))
        assert len(reports) == 1

    @pytest.mark.asyncio
    async def test_min_samples_suppresses_regression_calls(self, tmp_path: Path):
        """Agents below min_samples show in table but skip regression checks."""
        records = [
            _make_record(specialist="research", score_relevance=0.20),
        ]
        today_rows = [_avg_row("research", rel=0.20, count=1)]
        baseline_rows = [_avg_row("research", rel=0.90, count=30)]

        ctx = {
            "settings": _make_settings(tmp_path, min_samples=5),
            "bot": AsyncMock(),
            "session_factory": _session_factory(AsyncMock()),
        }

        with (
            patch(
                "src.app.workers.eval_pipeline.get_interactions_for_export",
                new_callable=AsyncMock,
                return_value=records,
            ),
            patch(
                "src.app.workers.eval_pipeline.get_specialist_score_averages",
                new_callable=AsyncMock,
                side_effect=[today_rows, baseline_rows],
            ),
        ):
            from src.app.workers.eval_pipeline import run_daily_eval_pipeline

            await run_daily_eval_pipeline(ctx)

        reports = list((_expected_eval_root(tmp_path) / "reports").glob("*_summary.md"))
        report_text = reports[0].read_text(encoding="utf-8")
        # Agent appears in the table
        assert "research" in report_text
        # But the regression section should be absent / benign
        assert "Regressions" not in report_text
        assert "All agents within budget" in report_text
