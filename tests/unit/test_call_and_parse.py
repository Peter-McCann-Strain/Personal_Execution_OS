"""Tests for call_and_parse() and call_and_extract_text() in llm_helpers."""

import json
from unittest.mock import MagicMock

import anthropic
import pytest
from pydantic import BaseModel, Field

from src.app.core.exceptions import LLMError
from src.app.core.llm_helpers import call_and_extract_text, call_and_parse
from tests.conftest import make_anthropic_response

# ---------------------------------------------------------------------------
# Test Pydantic model for call_and_parse
# ---------------------------------------------------------------------------


class SampleOutput(BaseModel):
    """A simple model for testing parse behaviour."""

    name: str
    score: float = Field(ge=0.0, le=10.0)
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# call_and_parse
# ---------------------------------------------------------------------------


async def test_call_and_parse_success(mock_anthropic_client):
    """Valid JSON matching the Pydantic model should return the parsed model."""
    response_data = {"name": "test item", "score": 7.5, "tags": ["alpha", "beta"]}
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    result = await call_and_parse(
        mock_anthropic_client,
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system="You are a test helper.",
        messages=[{"role": "user", "content": "test"}],
        response_model=SampleOutput,
        error_context="test agent",
    )

    assert isinstance(result, SampleOutput)
    assert result.name == "test item"
    assert result.score == 7.5
    assert result.tags == ["alpha", "beta"]


async def test_call_and_parse_with_defaults(mock_anthropic_client):
    """Missing optional fields should use Pydantic defaults."""
    response_data = {"name": "minimal", "score": 5.0}
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    result = await call_and_parse(
        mock_anthropic_client,
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system="test",
        messages=[{"role": "user", "content": "test"}],
        response_model=SampleOutput,
        error_context="test agent",
    )

    assert result.tags == []


async def test_call_and_parse_llm_call_failure(mock_anthropic_client):
    """LLM API call failure should raise LLMError with the error context."""
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)

    with pytest.raises(LLMError, match="test agent failed"):
        await call_and_parse(
            mock_anthropic_client,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system="test",
            messages=[{"role": "user", "content": "test"}],
            response_model=SampleOutput,
            error_context="test agent",
        )


async def test_call_and_parse_invalid_json(mock_anthropic_client):
    """Invalid JSON from LLM should raise LLMError."""
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        "I'm a helpful assistant! Here's what I think..."
    )

    with pytest.raises(LLMError, match="Failed to parse test agent"):
        await call_and_parse(
            mock_anthropic_client,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system="test",
            messages=[{"role": "user", "content": "test"}],
            response_model=SampleOutput,
            error_context="test agent",
        )


async def test_call_and_parse_validation_error(mock_anthropic_client):
    """JSON that doesn't match the Pydantic schema should raise LLMError."""
    # score=15 violates the ge=0, le=10 constraint
    response_data = {"name": "bad", "score": 15.0}
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    with pytest.raises(LLMError, match="Failed to parse test agent"):
        await call_and_parse(
            mock_anthropic_client,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system="test",
            messages=[{"role": "user", "content": "test"}],
            response_model=SampleOutput,
            error_context="test agent",
        )


async def test_call_and_parse_missing_required_field(mock_anthropic_client):
    """JSON missing a required field should raise LLMError."""
    # Missing 'name' which is required
    response_data = {"score": 5.0}
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    with pytest.raises(LLMError, match="Failed to parse test agent"):
        await call_and_parse(
            mock_anthropic_client,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system="test",
            messages=[{"role": "user", "content": "test"}],
            response_model=SampleOutput,
            error_context="test agent",
        )


async def test_call_and_parse_empty_response(mock_anthropic_client):
    """Empty response content should raise LLMError."""
    response = MagicMock()
    response.content = []
    mock_anthropic_client.messages.create.return_value = response

    with pytest.raises(LLMError, match="empty response content"):
        await call_and_parse(
            mock_anthropic_client,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system="test",
            messages=[{"role": "user", "content": "test"}],
            response_model=SampleOutput,
            error_context="test agent",
        )


# ---------------------------------------------------------------------------
# call_and_extract_text
# ---------------------------------------------------------------------------


async def test_call_and_extract_text_success(mock_anthropic_client):
    """Successful LLM call should return the text content."""
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        "Here is a thoughtful summary of the research."
    )

    result = await call_and_extract_text(
        mock_anthropic_client,
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system="You are a research assistant.",
        messages=[{"role": "user", "content": "summarise this"}],
        error_context="research summary",
    )

    assert result == "Here is a thoughtful summary of the research."


async def test_call_and_extract_text_api_failure(mock_anthropic_client):
    """API failure should raise LLMError with context."""
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)

    with pytest.raises(LLMError, match="research summary failed"):
        await call_and_extract_text(
            mock_anthropic_client,
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system="test",
            messages=[{"role": "user", "content": "test"}],
            error_context="research summary",
        )


async def test_call_and_extract_text_empty_response(mock_anthropic_client):
    """Empty response should raise LLMError."""
    response = MagicMock()
    response.content = []
    mock_anthropic_client.messages.create.return_value = response

    with pytest.raises(LLMError):
        await call_and_extract_text(
            mock_anthropic_client,
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system="test",
            messages=[{"role": "user", "content": "test"}],
            error_context="test",
        )


async def test_call_and_extract_text_tool_use_response(mock_anthropic_client):
    """Non-text content block (tool_use) should raise LLMError."""
    response = MagicMock()
    block = MagicMock(spec=["type", "id", "name", "input"])
    block.type = "tool_use"
    del block.text
    response.content = [block]
    mock_anthropic_client.messages.create.return_value = response

    with pytest.raises(LLMError, match="non-text content block"):
        await call_and_extract_text(
            mock_anthropic_client,
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system="test",
            messages=[{"role": "user", "content": "test"}],
            error_context="test",
        )
