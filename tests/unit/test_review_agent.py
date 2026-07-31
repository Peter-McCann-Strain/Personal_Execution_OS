"""Tests for review agent."""

import json

import anthropic
import pytest

from src.app.agents.specialists.review import generate_weekly_review
from src.app.core.exceptions import LLMError
from tests.conftest import make_anthropic_response


@pytest.mark.asyncio
async def test_weekly_review_success(mock_anthropic_client):
    response_data = {
        "period": "week of 2026-03-03",
        "accomplishments": ["Completed project plan", "Had 3 productive meetings"],
        "mood_summary": "Generally positive with a dip on Wednesday",
        "average_mood": 7.2,
        "goal_progress": [{"goal": "Ship v1", "progress_pct": 40, "change": "+10%"}],
        "open_commitments": [{"what": "Send report to boss", "status": "on_track"}],
        "relationship_alerts": ["Reconnect with Sarah — 2 weeks since last chat"],
        "patterns_noticed": [
            {
                "pattern": "Energy drops after lunch consistently",
                "evidence": "",
                "category": "energy",
                "actionable": True,
            }
        ],
        "recommendations": [
            {"action": "Schedule deep work before noon", "why": "", "priority": "high"}
        ],
        "key_insight": "Making good progress but need more rest days",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    review = await generate_weekly_review("Week data here...", mock_anthropic_client)
    assert review.period == "week of 2026-03-03"
    assert len(review.accomplishments) == 2
    assert review.average_mood == 7.2
    assert review.key_insight is not None


@pytest.mark.asyncio
async def test_weekly_review_api_failure(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
    with pytest.raises(LLMError, match="Weekly review generation failed"):
        await generate_weekly_review("test data", mock_anthropic_client)
