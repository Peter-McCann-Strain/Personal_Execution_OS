"""Tests for progressive summarisation."""

import json

import anthropic
import pytest

from src.app.core.exceptions import LLMError
from src.app.second_brain.progressive_summary import (
    ProgressiveSummaryResult,
    generate_progressive_summary,
)
from tests.conftest import make_anthropic_response


@pytest.mark.asyncio
async def test_progressive_summary_success(mock_anthropic_client):
    response_data = {
        "layer_2_passages": ["Key passage about project deadline"],
        "layer_3_highlights": ["Deadline is March 15th"],
        "layer_4_summary": "Project deadline approaching, need to prioritise.",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    result = await generate_progressive_summary("Long text here...", mock_anthropic_client)
    assert isinstance(result, ProgressiveSummaryResult)
    assert len(result.layer_2_passages) == 1
    assert result.layer_4_summary == "Project deadline approaching, need to prioritise."


@pytest.mark.asyncio
async def test_progressive_summary_api_failure(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
    with pytest.raises(LLMError, match="Progressive summary failed"):
        await generate_progressive_summary("test", mock_anthropic_client)


@pytest.mark.asyncio
async def test_progressive_summary_invalid_json(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response("not json")
    with pytest.raises(LLMError):
        await generate_progressive_summary("test", mock_anthropic_client)
