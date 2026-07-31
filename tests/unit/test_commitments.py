"""Tests for commitment extraction."""

import json

import anthropic
import pytest

from src.app.core.exceptions import LLMError
from src.app.domain.services.commitments import extract_commitments
from tests.conftest import make_anthropic_response


@pytest.mark.asyncio
async def test_extract_commitment(mock_anthropic_client):
    response_data = {
        "commitments": [
            {
                "verbatim_text": "I'll send the report by Friday",
                "normalized_action": "Send the report",
                "who_committed": "user",
                "who_to": "boss",
                "temporal_expression": "by Friday",
                "confidence": 0.95,
            }
        ]
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    result = await extract_commitments(
        "I told my boss I'll send the report by Friday", mock_anthropic_client
    )
    assert len(result) == 1
    assert result[0].normalized_action == "Send the report"
    assert result[0].confidence == 0.95


@pytest.mark.asyncio
async def test_extract_no_commitments(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps({"commitments": []})
    )
    result = await extract_commitments("The weather is nice", mock_anthropic_client)
    assert len(result) == 0


@pytest.mark.asyncio
async def test_extract_multiple_commitments(mock_anthropic_client):
    response_data = {
        "commitments": [
            {
                "verbatim_text": "I'll call Sarah",
                "normalized_action": "Call Sarah",
                "who_committed": "user",
                "who_to": "Sarah",
                "temporal_expression": None,
                "confidence": 0.8,
            },
            {
                "verbatim_text": "pick up groceries tomorrow",
                "normalized_action": "Pick up groceries",
                "who_committed": "user",
                "who_to": None,
                "temporal_expression": "tomorrow",
                "confidence": 0.9,
            },
        ]
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    result = await extract_commitments("test", mock_anthropic_client)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_extract_api_failure(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
    with pytest.raises(LLMError, match="Commitment extraction failed"):
        await extract_commitments("test", mock_anthropic_client)
