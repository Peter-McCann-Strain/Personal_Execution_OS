"""Tests for PARA classification."""

import json

import anthropic
import pytest

from src.app.core.exceptions import LLMError
from src.app.second_brain.para_classifier import classify_para
from tests.conftest import make_anthropic_response


@pytest.mark.asyncio
async def test_classify_project(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps({"category": "project", "reasoning": "has a deadline"})
    )
    result = await classify_para("Finish the website redesign by Friday", mock_anthropic_client)
    assert result == "project"


@pytest.mark.asyncio
async def test_classify_area(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps({"category": "area", "reasoning": "ongoing wellbeing"})
    )
    result = await classify_para("Feeling stressed about work", mock_anthropic_client)
    assert result == "area"


@pytest.mark.asyncio
async def test_classify_resource(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps({"category": "resource", "reasoning": "reference material"})
    )
    result = await classify_para("Interesting article about AI agents", mock_anthropic_client)
    assert result == "resource"


@pytest.mark.asyncio
async def test_classify_archive(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps({"category": "archive", "reasoning": "completed"})
    )
    result = await classify_para("Old conference notes from 2023", mock_anthropic_client)
    assert result == "archive"


@pytest.mark.asyncio
async def test_classify_invalid_category_raises(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps({"category": "invalid", "reasoning": "bad"})
    )
    with pytest.raises(LLMError, match="Invalid PARA category"):
        await classify_para("test", mock_anthropic_client)


@pytest.mark.asyncio
async def test_classify_api_failure_raises(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
    with pytest.raises(LLMError, match="PARA classification failed"):
        await classify_para("test", mock_anthropic_client)


@pytest.mark.asyncio
async def test_classify_bad_json_raises(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response("not json")
    with pytest.raises(LLMError, match="Failed to parse"):
        await classify_para("test", mock_anthropic_client)
