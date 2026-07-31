"""Tests for GTD processor."""

import json

import anthropic
import pytest

from src.app.core.exceptions import LLMError
from src.app.second_brain.gtd_processor import process_gtd
from tests.conftest import make_anthropic_response


@pytest.mark.asyncio
async def test_gtd_do_now(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(
            {
                "is_actionable": True,
                "gtd_type": "do_now",
                "next_action": "Reply to the email",
                "reasoning": "Quick task under 2 minutes",
            }
        )
    )
    result = await process_gtd("Reply to John's email", mock_anthropic_client)
    assert result.is_actionable is True
    assert result.gtd_type == "do_now"
    assert result.next_action == "Reply to the email"


@pytest.mark.asyncio
async def test_gtd_next_action(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(
            {
                "is_actionable": True,
                "gtd_type": "next_action",
                "next_action": "Schedule dentist appointment",
                "reasoning": "Single deferred action",
            }
        )
    )
    result = await process_gtd("Need to book a dentist appointment", mock_anthropic_client)
    assert result.gtd_type == "next_action"


@pytest.mark.asyncio
async def test_gtd_create_project(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(
            {
                "is_actionable": True,
                "gtd_type": "create_project",
                "next_action": "List requirements for the kitchen renovation",
                "reasoning": "Multi-step outcome",
            }
        )
    )
    result = await process_gtd("Renovate the kitchen", mock_anthropic_client)
    assert result.gtd_type == "create_project"


@pytest.mark.asyncio
async def test_gtd_reference(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(
            {
                "is_actionable": False,
                "gtd_type": "reference",
                "next_action": None,
                "reasoning": "Reference material",
            }
        )
    )
    result = await process_gtd("Python 3.13 release notes", mock_anthropic_client)
    assert result.is_actionable is False
    assert result.gtd_type == "reference"


@pytest.mark.asyncio
async def test_gtd_incubate(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(
            {
                "is_actionable": False,
                "gtd_type": "incubate",
                "next_action": None,
                "reasoning": "Personal reflection",
            }
        )
    )
    result = await process_gtd("Feeling good about progress today", mock_anthropic_client)
    assert result.gtd_type == "incubate"


@pytest.mark.asyncio
async def test_gtd_invalid_type_raises(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(
            {
                "is_actionable": True,
                "gtd_type": "invalid_type",
                "next_action": None,
                "reasoning": "bad",
            }
        )
    )
    with pytest.raises(LLMError, match="Failed to parse GTD response"):
        await process_gtd("test", mock_anthropic_client)


@pytest.mark.asyncio
async def test_gtd_api_failure_raises(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
    with pytest.raises(LLMError, match="GTD processing failed"):
        await process_gtd("test", mock_anthropic_client)
