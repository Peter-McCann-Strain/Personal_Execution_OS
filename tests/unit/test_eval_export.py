"""Tests for evaluation data export worker."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_settings(tmp_path: Path) -> MagicMock:
    """Create mock settings with tmp_path as export dir."""
    settings = MagicMock()
    settings.eval_export_enabled = True
    settings.evaluation_export_dir = str(tmp_path / "exports")
    return settings


def _make_session_factory(session: AsyncMock):
    """Create a mock async session factory."""

    @asynccontextmanager
    async def factory():
        yield session

    return factory


def _make_record(
    *,
    specialist: str = "diary",
    user_message: str = "How am I feeling?",
    response_content: str = "You seem to be in good spirits today.",
    score_relevance: float | None = 0.85,
    score_actionability: float | None = 0.7,
    score_tone: float | None = 0.9,
    score_conciseness: float | None = 0.8,
    auto_judge_reasoning: str | None = "Good response.",
    feedback_rating: str | None = None,
    optimizer_triggered: bool = False,
    optimizer_issue: str | None = None,
    intent_type: str = "capture",
    routing_confidence: float = 0.95,
    duration_ms: int = 1500,
) -> MagicMock:
    """Create a mock InteractionRecord for export tests."""
    record = MagicMock()
    record.id = uuid4()
    record.specialist = specialist
    record.user_message = user_message
    record.response_content = response_content
    record.score_relevance = score_relevance
    record.score_actionability = score_actionability
    record.score_tone = score_tone
    record.score_conciseness = score_conciseness
    record.auto_judge_reasoning = auto_judge_reasoning
    record.feedback_rating = feedback_rating
    record.optimizer_triggered = optimizer_triggered
    record.optimizer_issue = optimizer_issue
    record.intent_type = intent_type
    record.routing_confidence = routing_confidence
    record.duration_ms = duration_ms
    record.created_at = datetime.now(UTC)
    return record


class TestRunEvalExport:
    @pytest.mark.asyncio
    async def test_creates_export_directory(self, tmp_path: Path):
        """Export creates the directory if it doesn't exist."""
        export_dir = tmp_path / "exports"
        assert not export_dir.exists()

        session = AsyncMock()

        ctx = {
            "settings": _make_settings(tmp_path),
            "session_factory": _make_session_factory(session),
        }

        with patch(
            "src.app.workers.eval_export.get_interactions_for_export",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from src.app.workers.eval_export import run_eval_export

            await run_eval_export(ctx)

        assert export_dir.exists()

    @pytest.mark.asyncio
    async def test_no_records_no_file(self, tmp_path: Path):
        """No file is created when there are no records to export."""
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(tmp_path),
            "session_factory": _make_session_factory(session),
        }

        with patch(
            "src.app.workers.eval_export.get_interactions_for_export",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from src.app.workers.eval_export import run_eval_export

            await run_eval_export(ctx)

        export_dir = tmp_path / "exports"
        md_files = list(export_dir.glob("*.md"))
        assert len(md_files) == 0

    @pytest.mark.asyncio
    async def test_exports_scored_records(self, tmp_path: Path):
        """Export writes a markdown file with scored record data."""
        record = _make_record()

        session = AsyncMock()

        ctx = {
            "settings": _make_settings(tmp_path),
            "session_factory": _make_session_factory(session),
        }

        with patch(
            "src.app.workers.eval_export.get_interactions_for_export",
            new_callable=AsyncMock,
            return_value=[record],
        ):
            from src.app.workers.eval_export import run_eval_export

            await run_eval_export(ctx)

        export_dir = tmp_path / "exports"
        md_files = list(export_dir.glob("interactions_*.md"))
        assert len(md_files) == 1

        content = md_files[0].read_text()
        assert "# Interaction Records" in content
        assert "Summary Scores" in content
        assert "diary" in content
        assert "0.85" in content  # relevance score

    @pytest.mark.asyncio
    async def test_exports_feedback_summary(self, tmp_path: Path):
        """Export includes user feedback summary when present."""
        record_up = _make_record(feedback_rating="thumbs_up")
        record_down = _make_record(feedback_rating="thumbs_down")

        session = AsyncMock()

        ctx = {
            "settings": _make_settings(tmp_path),
            "session_factory": _make_session_factory(session),
        }

        with patch(
            "src.app.workers.eval_export.get_interactions_for_export",
            new_callable=AsyncMock,
            return_value=[record_up, record_down],
        ):
            from src.app.workers.eval_export import run_eval_export

            await run_eval_export(ctx)

        export_dir = tmp_path / "exports"
        md_files = list(export_dir.glob("interactions_*.md"))
        content = md_files[0].read_text()
        assert "User Feedback" in content
        assert "Thumbs up: 1" in content
        assert "Thumbs down: 1" in content

    @pytest.mark.asyncio
    async def test_exports_unscored_records(self, tmp_path: Path):
        """Unscored records show 'not scored' in export."""
        record = _make_record(
            score_relevance=None,
            score_actionability=None,
            score_tone=None,
            score_conciseness=None,
        )

        session = AsyncMock()

        ctx = {
            "settings": _make_settings(tmp_path),
            "session_factory": _make_session_factory(session),
        }

        with patch(
            "src.app.workers.eval_export.get_interactions_for_export",
            new_callable=AsyncMock,
            return_value=[record],
        ):
            from src.app.workers.eval_export import run_eval_export

            await run_eval_export(ctx)

        export_dir = tmp_path / "exports"
        md_files = list(export_dir.glob("interactions_*.md"))
        content = md_files[0].read_text()
        assert "not scored" in content

    @pytest.mark.asyncio
    async def test_partially_scored_record_is_exported_as_unscored(self, tmp_path: Path):
        """A partial judge write must not break score averaging or record formatting."""
        record = _make_record(
            score_relevance=0.85,
            score_actionability=None,
            score_tone=0.9,
            score_conciseness=0.8,
        )
        session = AsyncMock()
        ctx = {
            "settings": _make_settings(tmp_path),
            "session_factory": _make_session_factory(session),
        }

        with patch(
            "src.app.workers.eval_export.get_interactions_for_export",
            new_callable=AsyncMock,
            return_value=[record],
        ):
            from src.app.workers.eval_export import run_eval_export

            await run_eval_export(ctx)

        content = next((tmp_path / "exports").glob("interactions_*.md")).read_text()
        assert "Summary Scores" not in content
        assert '"scores": "not scored"' in content

    @pytest.mark.asyncio
    async def test_exports_optimizer_triggered(self, tmp_path: Path):
        """Export records show optimizer trigger status."""
        record = _make_record(
            optimizer_triggered=True,
            optimizer_issue="Response was off-topic",
        )

        session = AsyncMock()

        ctx = {
            "settings": _make_settings(tmp_path),
            "session_factory": _make_session_factory(session),
        }

        with patch(
            "src.app.workers.eval_export.get_interactions_for_export",
            new_callable=AsyncMock,
            return_value=[record],
        ):
            from src.app.workers.eval_export import run_eval_export

            await run_eval_export(ctx)

        export_dir = tmp_path / "exports"
        md_files = list(export_dir.glob("interactions_*.md"))
        content = md_files[0].read_text()
        assert "off-topic" in content
