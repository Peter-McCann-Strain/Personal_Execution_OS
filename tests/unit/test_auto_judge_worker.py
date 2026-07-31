"""Tests for auto-judge ARQ worker."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.app.core.auto_judge import AutoJudgeScores


def _make_settings(*, enabled: bool = True) -> MagicMock:
    """Create mock settings for auto-judge worker."""
    settings = MagicMock()
    settings.auto_judge_enabled = enabled
    settings.auto_judge_model = "claude-haiku-4-5-20251001"
    settings.auto_judge_max_tokens = 512
    settings.auto_judge_batch_size = 50
    settings.anthropic_api_key.get_secret_value.return_value = "test-key"
    return settings


def _make_session_factory(session: AsyncMock):
    """Create a mock async session factory compatible with `async with factory() as s:`."""

    @asynccontextmanager
    async def factory():
        yield session

    return factory


def _make_record(
    *,
    specialist: str = "diary",
    user_message: str = "Hello",
    response_content: str = "Hi there!",
    trace_id: str | None = None,
) -> MagicMock:
    """Create a mock InteractionRecord."""
    record = MagicMock()
    record.id = uuid4()
    record.specialist = specialist
    record.user_message = user_message
    record.response_content = response_content
    record.trace_id = trace_id
    return record


def _make_scores(**overrides) -> AutoJudgeScores:
    """Create AutoJudgeScores with defaults."""
    defaults = {
        "relevance": 0.85,
        "actionability": 0.7,
        "tone": 0.9,
        "conciseness": 0.8,
        "reasoning": "Good response.",
    }
    defaults.update(overrides)
    return AutoJudgeScores(**defaults)


class TestRunAutoJudge:
    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        """Worker exits early when auto_judge_enabled is False."""
        ctx = {
            "settings": _make_settings(enabled=False),
            "session_factory": AsyncMock(),
        }

        from src.app.workers.auto_judge import run_auto_judge

        await run_auto_judge(ctx)
        # Should not touch session_factory at all
        ctx["session_factory"].assert_not_called()

    @pytest.mark.asyncio
    async def test_no_pending_records(self):
        """Worker exits gracefully when no pending records exist."""
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(),
            "session_factory": _make_session_factory(session),
        }

        with patch(
            "src.app.workers.auto_judge.get_pending_interactions",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from src.app.workers.auto_judge import run_auto_judge

            await run_auto_judge(ctx)

    @pytest.mark.asyncio
    async def test_scores_pending_records(self):
        """Worker scores pending records and updates them."""
        record = _make_record()
        scores = _make_scores()
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(),
            "session_factory": _make_session_factory(session),
        }

        with (
            patch(
                "src.app.workers.auto_judge.get_pending_interactions",
                new_callable=AsyncMock,
                return_value=[record],
            ),
            patch(
                "src.app.workers.auto_judge.score_interaction",
                new_callable=AsyncMock,
                return_value=scores,
            ) as mock_score,
            patch(
                "src.app.workers.auto_judge.update_auto_judge_scores",
                new_callable=AsyncMock,
            ) as mock_update,
        ):
            from src.app.workers.auto_judge import run_auto_judge

            await run_auto_judge(ctx)

        mock_score.assert_awaited_once()
        mock_update.assert_awaited_once()
        # Verify correct scores were passed
        update_kwargs = mock_update.call_args.kwargs
        assert update_kwargs["score_relevance"] == 0.85
        assert update_kwargs["score_actionability"] == 0.7
        assert update_kwargs["score_tone"] == 0.9
        assert update_kwargs["score_conciseness"] == 0.8
        assert "Good response." in update_kwargs["reasoning"]

    @pytest.mark.asyncio
    async def test_individual_record_failure_does_not_block_batch(self):
        """If one record fails to score, others in the batch still succeed."""
        record1 = _make_record(specialist="diary")
        record2 = _make_record(specialist="memory")
        scores = _make_scores()
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(),
            "session_factory": _make_session_factory(session),
        }

        call_count = 0

        async def mock_score_fn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("API error for first record")
            return scores

        with (
            patch(
                "src.app.workers.auto_judge.get_pending_interactions",
                new_callable=AsyncMock,
                return_value=[record1, record2],
            ),
            patch(
                "src.app.workers.auto_judge.score_interaction",
                side_effect=mock_score_fn,
            ),
            patch(
                "src.app.workers.auto_judge.update_auto_judge_scores",
                new_callable=AsyncMock,
            ) as mock_update,
        ):
            from src.app.workers.auto_judge import run_auto_judge

            # Should not raise despite first record failing
            await run_auto_judge(ctx)

        # Only the second record should have been updated
        assert mock_update.await_count == 1

    @pytest.mark.asyncio
    async def test_commits_after_batch(self):
        """Worker commits the session after processing the batch."""
        record = _make_record()
        scores = _make_scores()
        session = AsyncMock()

        ctx = {
            "settings": _make_settings(),
            "session_factory": _make_session_factory(session),
        }

        with (
            patch(
                "src.app.workers.auto_judge.get_pending_interactions",
                new_callable=AsyncMock,
                return_value=[record],
            ),
            patch(
                "src.app.workers.auto_judge.score_interaction",
                new_callable=AsyncMock,
                return_value=scores,
            ),
            patch(
                "src.app.workers.auto_judge.update_auto_judge_scores",
                new_callable=AsyncMock,
            ),
        ):
            from src.app.workers.auto_judge import run_auto_judge

            await run_auto_judge(ctx)

        session.commit.assert_awaited_once()
