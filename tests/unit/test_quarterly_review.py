"""Tests for quarterly review generation."""

import json

import anthropic
import pytest

from src.app.agents.specialists.review import QuarterlyReview, generate_quarterly_review
from src.app.core.exceptions import LLMError
from tests.conftest import make_anthropic_response


@pytest.mark.asyncio
async def test_quarterly_review_success(mock_anthropic_client):
    response_data = {
        "period": "Q1 2026",
        "goal_achievement": [
            {"goal": "Ship v1", "target": "Launch", "achieved": True, "notes": "On time"}
        ],
        "major_decisions": [
            {
                "decision": "Switched to FastAPI",
                "outcome": "Faster development",
                "rating": "good",
            }
        ],
        "relationship_health": [],
        "pattern_analysis": ["Consistent morning productivity"],
        "lessons_learned": ["Smaller PRs merge faster"],
        "next_quarter_priorities": ["Scale to 100 users"],
        "key_insight": "Consistency beats intensity",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    review = await generate_quarterly_review("Quarter data here", mock_anthropic_client)
    assert isinstance(review, QuarterlyReview)
    assert review.period == "Q1 2026"
    assert review.key_insight == "Consistency beats intensity"


@pytest.mark.asyncio
async def test_quarterly_review_api_failure(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
    with pytest.raises(LLMError, match="Quarterly review generation failed"):
        await generate_quarterly_review("test", mock_anthropic_client)
