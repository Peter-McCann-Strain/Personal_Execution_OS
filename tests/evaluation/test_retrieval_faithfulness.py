"""Tests for the Haiku faithfulness judge — no real API calls.

We mock the Anthropic client end-to-end so these tests run in CI without
credentials.  The same mocking pattern is used throughout the unit-test
suite for auto_judge and related LLM helpers.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.core.retrieval_faithfulness import (
    FaithfulnessReport,
    faithfulness_score,
)


def _mock_response(payload: dict) -> MagicMock:
    """Build an Anthropic-shaped response whose single text block is JSON."""
    content_block = MagicMock()
    content_block.type = "text"
    content_block.text = json.dumps(payload)

    usage = MagicMock()
    usage.input_tokens = 10
    usage.output_tokens = 20
    # cache fields default to falsy — llm_helpers tolerates that.

    response = MagicMock()
    response.content = [content_block]
    response.usage = usage
    return response


async def test_empty_answer_short_circuits() -> None:
    judge = AsyncMock()
    report = await faithfulness_score("   ", ["anything"], judge)
    assert report.score == 1.0
    assert report.total_claims == 0
    judge.messages.create.assert_not_called()


async def test_fully_supported_answer_scores_one() -> None:
    judge = AsyncMock()
    judge.messages.create.return_value = _mock_response(
        {
            "supported_claims": 3,
            "total_claims": 3,
            "score": 1.0,
            "reasoning": "All three claims match the contexts.",
        },
    )

    report = await faithfulness_score(
        "The meeting is on Friday. Alice will chair. The report is due Monday.",
        ["The meeting is on Friday and Alice will chair. Report due Monday."],
        judge,
    )

    assert isinstance(report, FaithfulnessReport)
    assert report.supported_claims == 3
    assert report.total_claims == 3
    assert report.score == pytest.approx(1.0)


async def test_partially_supported_recomputes_score() -> None:
    """The validator should recompute score from counts even if the judge drifts."""
    judge = AsyncMock()
    judge.messages.create.return_value = _mock_response(
        {
            "supported_claims": 1,
            "total_claims": 4,
            "score": 0.99,  # deliberately wrong — should be overwritten
            "reasoning": "Only one of four claims is grounded.",
        },
    )

    report = await faithfulness_score(
        "Claim A. Claim B. Claim C. Claim D.",
        ["Only claim A appears in the retrieved context."],
        judge,
    )
    assert report.score == pytest.approx(0.25)


async def test_supported_gt_total_rejected() -> None:
    """Invalid judge output (supported > total) must fail validation."""
    from src.app.core.exceptions import LLMError

    judge = AsyncMock()
    judge.messages.create.return_value = _mock_response(
        {
            "supported_claims": 5,
            "total_claims": 3,
            "score": 1.0,
            "reasoning": "bogus",
        },
    )

    with pytest.raises(LLMError):
        await faithfulness_score("answer", ["ctx"], judge)


async def test_zero_claims_returns_one() -> None:
    judge = AsyncMock()
    judge.messages.create.return_value = _mock_response(
        {
            "supported_claims": 0,
            "total_claims": 0,
            "score": 0.0,  # judge reports 0, validator must coerce to 1.0
            "reasoning": "No factual claims to evaluate.",
        },
    )

    report = await faithfulness_score(
        "Sure thing!",
        ["irrelevant context"],
        judge,
    )
    assert report.score == pytest.approx(1.0)
