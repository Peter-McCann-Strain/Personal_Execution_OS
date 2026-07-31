"""Tests for auto-judge scoring module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.app.core.auto_judge import AutoJudgeScores, score_interaction
from src.app.core.exceptions import EvaluationError
from tests.conftest import make_anthropic_response


@pytest.fixture
def mock_client() -> AsyncMock:
    """Mock Anthropic client."""
    return AsyncMock()


class TestAutoJudgeScores:
    def test_valid_scores(self):
        """AutoJudgeScores accepts valid 0-1 float values."""
        scores = AutoJudgeScores(
            relevance=0.85,
            actionability=0.7,
            tone=0.9,
            conciseness=0.8,
            reasoning="Good response overall.",
        )
        assert scores.relevance == 0.85
        assert scores.actionability == 0.7
        assert scores.tone == 0.9
        assert scores.conciseness == 0.8
        assert scores.reasoning == "Good response overall."

    def test_boundary_values(self):
        """AutoJudgeScores accepts boundary values 0.0 and 1.0."""
        scores = AutoJudgeScores(
            relevance=0.0,
            actionability=1.0,
            tone=0.0,
            conciseness=1.0,
            reasoning="Edge case.",
        )
        assert scores.relevance == 0.0
        assert scores.conciseness == 1.0

    def test_rejects_out_of_range(self):
        """AutoJudgeScores rejects values outside 0-1."""
        with pytest.raises(ValueError, match="less than or equal to"):
            AutoJudgeScores(
                relevance=1.5,
                actionability=0.5,
                tone=0.5,
                conciseness=0.5,
                reasoning="Bad value.",
            )

    def test_rejects_negative(self):
        """AutoJudgeScores rejects negative values."""
        with pytest.raises(ValueError, match="greater than or equal to"):
            AutoJudgeScores(
                relevance=-0.1,
                actionability=0.5,
                tone=0.5,
                conciseness=0.5,
                reasoning="Negative value.",
            )


class TestScoreInteraction:
    @pytest.mark.asyncio
    async def test_successful_scoring(self, mock_client: AsyncMock):
        """score_interaction returns valid scores from LLM response."""
        scores_data = {
            "relevance": 0.85,
            "actionability": 0.7,
            "tone": 0.9,
            "conciseness": 0.8,
            "reasoning": "Response directly addresses the query.",
        }
        mock_client.messages.create.return_value = make_anthropic_response(json.dumps(scores_data))

        result = await score_interaction(
            mock_client,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            user_message="What meetings do I have tomorrow?",
            response_content="You have a team standup at 9am and a 1:1 with your manager at 2pm.",
            specialist="tools",
        )

        assert isinstance(result, AutoJudgeScores)
        assert result.relevance == 0.85
        assert result.actionability == 0.7
        assert result.tone == 0.9
        assert result.conciseness == 0.8
        assert "addresses" in result.reasoning

    @pytest.mark.asyncio
    async def test_raises_evaluation_error_on_llm_failure(self, mock_client: AsyncMock):
        """score_interaction raises EvaluationError when LLM call fails."""
        mock_client.messages.create.side_effect = Exception("API timeout")

        with pytest.raises(EvaluationError, match="Auto-judge scoring failed"):
            await score_interaction(
                mock_client,
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                user_message="Test",
                response_content="Test response",
                specialist="diary",
            )

    @pytest.mark.asyncio
    async def test_raises_evaluation_error_on_parse_failure(self, mock_client: AsyncMock):
        """score_interaction raises EvaluationError when response is not valid JSON."""
        mock_client.messages.create.return_value = make_anthropic_response("This is not JSON")

        with pytest.raises(EvaluationError, match="Auto-judge scoring failed"):
            await score_interaction(
                mock_client,
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                user_message="Test",
                response_content="Test response",
                specialist="memory",
            )

    @pytest.mark.asyncio
    async def test_raises_evaluation_error_on_validation_failure(self, mock_client: AsyncMock):
        """score_interaction raises EvaluationError when scores are out of range."""
        bad_data = {
            "relevance": 2.0,  # Out of range
            "actionability": 0.5,
            "tone": 0.5,
            "conciseness": 0.5,
            "reasoning": "Bad scores.",
        }
        mock_client.messages.create.return_value = make_anthropic_response(json.dumps(bad_data))

        with pytest.raises(EvaluationError, match="Auto-judge scoring failed"):
            await score_interaction(
                mock_client,
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                user_message="Test",
                response_content="Test response",
                specialist="research",
            )

    @pytest.mark.asyncio
    async def test_does_not_inject_personality(self, mock_client: AsyncMock):
        """Auto-judge should not inject personality into scoring prompts."""
        scores_data = {
            "relevance": 0.8,
            "actionability": 0.8,
            "tone": 0.8,
            "conciseness": 0.8,
            "reasoning": "Fine.",
        }
        mock_client.messages.create.return_value = make_anthropic_response(json.dumps(scores_data))

        await score_interaction(
            mock_client,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            user_message="Hello",
            response_content="Hi there!",
            specialist="diary",
        )

        # Check inject_personality was effectively False: no personality prefix in system
        call_args = mock_client.messages.create.call_args
        system_arg = call_args.kwargs.get("system", "")
        system_text = system_arg[0].get("text", "") if isinstance(system_arg, list) else system_arg
        assert "<personality>" not in system_text

    @pytest.mark.asyncio
    async def test_truncates_long_inputs(self, mock_client: AsyncMock):
        """Long user messages and responses are truncated in the scoring prompt."""
        scores_data = {
            "relevance": 0.8,
            "actionability": 0.8,
            "tone": 0.8,
            "conciseness": 0.8,
            "reasoning": "Truncated content scored.",
        }
        mock_client.messages.create.return_value = make_anthropic_response(json.dumps(scores_data))

        long_message = "x" * 5000
        long_response = "y" * 10000

        await score_interaction(
            mock_client,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            user_message=long_message,
            response_content=long_response,
            specialist="research",
        )

        # Verify the call was made with truncated content
        call_args = mock_client.messages.create.call_args
        user_content = call_args.kwargs["messages"][0]["content"]
        # User message truncated to 1000 chars in the prompt
        assert "x" * 1001 not in user_content
        # Response truncated to 2000 chars in the prompt
        assert "y" * 2001 not in user_content
