"""Tests for response evaluator — evaluator-optimizer pattern."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.evaluator import (
    EvaluationResult,
    evaluate_response,
    evaluate_response_deterministic,
)
from src.app.core.exceptions import EvaluationError
from tests.conftest import make_anthropic_response


@pytest.fixture
def mock_client() -> AsyncMock:
    """Mock Anthropic client."""
    return AsyncMock()


class TestEvaluationResult:
    def test_passes_by_default(self):
        """Default EvaluationResult passes with no issues."""
        result = EvaluationResult(passes=True)
        assert result.passes is True
        assert result.issue == ""
        assert result.suggestion == ""

    def test_failing_result(self):
        """Failing result captures issue and suggestion."""
        result = EvaluationResult(
            passes=False,
            issue="Response discusses weather instead of diary entry",
            suggestion="Focus on capturing the user's mood and events",
        )
        assert result.passes is False
        assert "weather" in result.issue
        assert "mood" in result.suggestion

    def test_null_issue_and_suggestion_are_coerced_to_empty_strings(self):
        """Nullable rubric fields should not fail parsing."""
        result = EvaluationResult(
            passes=True,
            issue=None,
            suggestion=None,
        )
        assert result.issue == ""
        assert result.suggestion == ""


class TestEvaluateResponse:
    @pytest.mark.asyncio
    async def test_passing_evaluation(self, mock_client: AsyncMock):
        """When LLM says response passes, returns passing result."""
        eval_data = {"passes": True, "issue": "", "suggestion": ""}
        mock_client.messages.create.return_value = make_anthropic_response(json.dumps(eval_data))

        result = await evaluate_response(
            user_message="How am I feeling today?",
            response_content="Based on your diary entries, you seem to be in good spirits.",
            specialist="diary",
            client=mock_client,
        )

        assert result.passes is True
        assert result.issue == ""

    @pytest.mark.asyncio
    async def test_failing_evaluation(self, mock_client: AsyncMock):
        """When LLM says response fails, returns failing result with details."""
        eval_data = {
            "passes": False,
            "issue": "Response doesn't address the question",
            "suggestion": "Answer the specific question about mood",
        }
        mock_client.messages.create.return_value = make_anthropic_response(json.dumps(eval_data))

        result = await evaluate_response(
            user_message="What meetings do I have tomorrow?",
            response_content="Here's a nice recipe for pasta.",
            specialist="tools",
            client=mock_client,
        )

        assert result.passes is False
        assert "doesn't address" in result.issue
        assert "mood" in result.suggestion

    @pytest.mark.asyncio
    async def test_nullable_issue_and_suggestion_parse(self, mock_client: AsyncMock):
        """Evaluator responses with explicit nulls should still parse."""
        eval_data = {"passes": True, "issue": None, "suggestion": None}
        mock_client.messages.create.return_value = make_anthropic_response(json.dumps(eval_data))

        result = await evaluate_response(
            user_message="What do I have on today?",
            response_content="Calendar's clear for today.",
            specialist="tools",
            client=mock_client,
        )

        assert result.passes is True
        assert result.issue == ""
        assert result.suggestion == ""

    @pytest.mark.asyncio
    async def test_raises_on_llm_error(self, mock_client: AsyncMock):
        """When the evaluator LLM call fails, the error should propagate."""
        mock_client.messages.create.side_effect = Exception("API down")

        with pytest.raises(
            EvaluationError,
            match="Response evaluation failed with Exception: API down",
        ):
            await evaluate_response(
                user_message="Hello",
                response_content="Hi there!",
                specialist="diary",
                client=mock_client,
            )

    @pytest.mark.asyncio
    async def test_raises_on_parse_error(self, mock_client: AsyncMock):
        """When the evaluator response is invalid, the parse error should propagate."""
        mock_client.messages.create.return_value = make_anthropic_response("Not valid JSON at all")

        with pytest.raises(EvaluationError, match="Response evaluation failed with"):
            await evaluate_response(
                user_message="Test message",
                response_content="Test response",
                specialist="memory",
                client=mock_client,
            )

    @pytest.mark.asyncio
    async def test_truncates_long_inputs(self, mock_client: AsyncMock):
        """Long user messages and responses are truncated before sending to evaluator."""
        eval_data = {"passes": True, "issue": "", "suggestion": ""}
        mock_client.messages.create.return_value = make_anthropic_response(json.dumps(eval_data))

        long_message = "x" * 1000
        long_response = "y" * 2000

        result = await evaluate_response(
            user_message=long_message,
            response_content=long_response,
            specialist="research",
            client=mock_client,
        )

        assert result.passes is True
        # Verify the call was made — the truncation happens inside evaluate_response
        mock_client.messages.create.assert_awaited_once()
        call_args = mock_client.messages.create.call_args
        user_content = call_args.kwargs.get("messages", [{}])[0].get("content", "")
        # User message truncated to 500 chars
        assert "x" * 501 not in user_content
        # Response truncated to 1000 chars
        assert "y" * 1001 not in user_content

    @pytest.mark.asyncio
    async def test_uses_classifier_model(self, mock_client: AsyncMock):
        """Evaluator should use the classifier model (Haiku) for speed."""
        eval_data = {"passes": True, "issue": "", "suggestion": ""}
        mock_client.messages.create.return_value = make_anthropic_response(json.dumps(eval_data))

        await evaluate_response(
            user_message="Test",
            response_content="Response",
            specialist="diary",
            client=mock_client,
        )

        call_args = mock_client.messages.create.call_args
        assert call_args.kwargs.get("model") == "claude-haiku-4-5-20251001"

    @pytest.mark.asyncio
    async def test_no_personality_injected(self, mock_client: AsyncMock):
        """Evaluator calls should not inject personality (inject_personality=False)."""
        eval_data = {"passes": True, "issue": "", "suggestion": ""}
        mock_client.messages.create.return_value = make_anthropic_response(json.dumps(eval_data))

        with patch("src.app.core.llm_helpers.get_personality_prefix") as mock_prefix:
            mock_prefix.return_value = "<personality>\nSoul content\n</personality>\n\n"
            await evaluate_response(
                user_message="Test",
                response_content="Response",
                specialist="diary",
                client=mock_client,
            )

        # The system prompt sent to the API should NOT contain personality
        call_args = mock_client.messages.create.call_args
        system_arg = call_args.kwargs.get("system", "")
        system_text = system_arg[0].get("text", "") if isinstance(system_arg, list) else system_arg
        assert "<personality>" not in system_text


class TestEvaluateResponseDeterministic:
    def test_flags_internal_error_leak(self):
        """Deterministic evaluator should fail leaked internal errors."""
        result = evaluate_response_deterministic(
            user_message="What have I been focused on?",
            response_content="Failed to parse Memory retrieval response: {...}",
            specialist="memory",
            source="telegram",
        )

        assert result.passes is False
        assert "internal failure" in result.issue.lower()
        assert result.final_response_quality == 0.0

    def test_penalizes_schema_style_telegram_output(self):
        """Deterministic evaluator should lower channel style for schema-like Telegram copy."""
        result = evaluate_response_deterministic(
            user_message="Triage this email",
            response_content="Classification: urgent\n\nNext step: reply today.",
            specialist="communications",
            source="telegram",
        )

        assert result.passes is True
        assert result.channel_style == 0.45

    def test_assigns_grounding_when_context_exists(self):
        """Deterministic evaluator should mark grounding when retrieved evidence was used."""
        result = evaluate_response_deterministic(
            user_message="What did I work on yesterday?",
            response_content="Yesterday you shipped the deployment.",
            specialist="memory",
            source="telegram",
            context_inspection={"rag_chunks_included": 2},
            response_metadata={"source_count": 1},
        )

        assert result.grounding == 0.9
