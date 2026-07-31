"""Tests for project agent — WSJF and AI breakdown."""

import json

import anthropic
import pytest

from src.app.agents.specialists.project import (
    ai_breakdown_project,
    calculate_wsjf,
)
from src.app.core.exceptions import LLMError
from tests.conftest import make_anthropic_response


def test_wsjf_calculation():
    """WSJF = (business_value + time_criticality + risk_reduction) / job_size."""
    score = calculate_wsjf(
        business_value=8,
        time_criticality=6,
        risk_reduction=4,
        job_size=3,
    )
    assert score == 6.0  # (8+6+4)/3 = 6.0


def test_wsjf_zero_job_size_raises():
    """Zero job size should raise ValueError (out of 1-10 range)."""
    with pytest.raises(ValueError, match="job_size must be between 1 and 10"):
        calculate_wsjf(8, 6, 4, 0)


def test_wsjf_small_values():
    score = calculate_wsjf(1, 1, 1, 10)
    assert score == 0.3


@pytest.mark.asyncio
async def test_ai_breakdown_success(mock_anthropic_client):
    response_data = {
        "milestones": [
            {
                "title": "Design Phase",
                "success_criteria": ["Wireframes approved", "Tech stack chosen"],
                "tasks": [
                    {
                        "title": "Create wireframes",
                        "description": "Design main screens",
                        "estimate_hours": 4.0,
                        "complexity": "medium",
                        "context_tags": ["@deep-work"],
                        "depends_on": [],
                    }
                ],
            }
        ]
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    result = await ai_breakdown_project("Build a website", mock_anthropic_client)
    assert len(result.milestones) == 1
    assert result.milestones[0].title == "Design Phase"
    assert len(result.milestones[0].tasks) == 1
    assert result.milestones[0].tasks[0].estimate_hours == 4.0


@pytest.mark.asyncio
async def test_ai_breakdown_api_failure(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
    with pytest.raises(LLMError, match="Project breakdown failed"):
        await ai_breakdown_project("test", mock_anthropic_client)
