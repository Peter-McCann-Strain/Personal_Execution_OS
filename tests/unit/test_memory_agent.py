"""Tests for memory agent — retrieval and entity summary."""

import json

import anthropic
import pytest

from src.app.agents.specialists.memory import (
    MemoryAnswer,
    answer_from_memory,
    summarise_entity_context,
)
from src.app.core.exceptions import LLMError
from tests.conftest import make_anthropic_response


@pytest.mark.asyncio
async def test_answer_from_memory_with_context(mock_anthropic_client):
    response_data = {
        "answer": "You had lunch with Sarah last Tuesday.",
        "confidence": 0.85,
        "sources": [
            {
                "content": "Lunch with Sarah",
                "relevance_score": 0.9,
                "source_type": "episode",
                "source_id": "ep-123",
            }
        ],
        "follow_up_suggestions": ["What did you discuss?"],
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    chunks = [
        {
            "content": "Had lunch with Sarah at the cafe",
            "score": 0.9,
            "source_type": "episode",
            "source_id": "ep-123",
        }
    ]
    answer = await answer_from_memory("When did I see Sarah?", chunks, mock_anthropic_client)
    assert isinstance(answer, MemoryAnswer)
    assert answer.confidence == 0.85
    assert len(answer.sources) == 1


@pytest.mark.asyncio
async def test_answer_from_memory_empty_context(mock_anthropic_client):
    answer = await answer_from_memory("anything", [], mock_anthropic_client)
    assert answer.confidence == 0.0
    assert "don't have" in answer.answer
    mock_anthropic_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_answer_from_memory_api_failure(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
    chunks = [{"content": "test", "score": 0.5, "source_type": "note", "source_id": "n-1"}]
    with pytest.raises(LLMError, match="Memory retrieval failed"):
        await answer_from_memory("test", chunks, mock_anthropic_client)


@pytest.mark.asyncio
async def test_answer_from_memory_falls_back_to_plain_text_when_json_parse_fails(
    mock_anthropic_client,
):
    chunks = [
        {
            "content": "You spent most of the day on the Telegram bot and deployment fixes.",
            "score": 0.82,
            "source_type": "interaction",
            "source_id": "ir-1",
        }
    ]
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        "You've mainly been focused on the Telegram bot, deployment fixes, and the surrounding memory work."
    )

    answer = await answer_from_memory(
        "What have I been focused on recently?",
        chunks,
        mock_anthropic_client,
    )

    assert answer.answer.startswith("You've mainly been focused")
    assert answer.confidence == 0.8
    assert len(answer.sources) == 1
    assert answer.sources[0].source_type == "interaction"


@pytest.mark.asyncio
async def test_answer_from_memory_uses_generic_fallback_for_broken_jsonish_output(
    mock_anthropic_client,
):
    chunks = [
        {
            "content": "Frontend deployment remained the open blocker.",
            "score": 0.61,
            "source_type": "interaction",
            "source_id": "ir-2",
        }
    ]
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        '{"answer": "partial'
    )

    answer = await answer_from_memory(
        "What's still blocking me?",
        chunks,
        mock_anthropic_client,
    )

    assert "I found relevant context" in answer.answer
    assert answer.confidence == 0.61


@pytest.mark.asyncio
async def test_answer_from_memory_fallback_strips_internal_prefixes(mock_anthropic_client):
    chunks = [
        {
            "content": "You shipped deployment and improved Telegram handling.",
            "score": 0.77,
            "source_type": "interaction",
            "source_id": "ir-3",
        }
    ]
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        "Failed to parse Memory retrieval response: You shipped deployment and improved Telegram handling."
    )

    answer = await answer_from_memory(
        "What was I doing?",
        chunks,
        mock_anthropic_client,
    )

    assert "Failed to parse" not in answer.answer
    assert "You shipped deployment" in answer.answer


@pytest.mark.asyncio
async def test_answer_from_memory_fallback_strips_embedded_parse_wrappers(mock_anthropic_client):
    chunks = [
        {
            "content": "You shipped deployment and improved Telegram handling.",
            "score": 0.77,
            "source_type": "interaction",
            "source_id": "ir-4",
        }
    ]
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        "Sources (2): • Item A • Item B Failed to parse diary agent response: You shipped deployment and improved Telegram handling."
    )

    answer = await answer_from_memory(
        "What was I doing?",
        chunks,
        mock_anthropic_client,
    )

    assert "Failed to parse" not in answer.answer
    assert "Sources (" not in answer.answer
    assert "You shipped deployment" in answer.answer


@pytest.mark.asyncio
async def test_summarise_entity_context(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        "Sarah is a colleague who works in marketing."
    )
    mentions = [
        {"date": "2026-03-01", "content": "Met Sarah from marketing"},
        {"date": "2026-03-05", "content": "Sarah shared the Q1 report"},
    ]
    summary = await summarise_entity_context("Sarah", mentions, mock_anthropic_client)
    assert "Sarah" in summary


@pytest.mark.asyncio
async def test_summarise_entity_no_mentions(mock_anthropic_client):
    summary = await summarise_entity_context("Unknown", [], mock_anthropic_client)
    assert "No information" in summary
    mock_anthropic_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_summarise_entity_api_failure(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
    with pytest.raises(LLMError, match="Entity summary failed"):
        await summarise_entity_context("Sarah", [{"content": "test"}], mock_anthropic_client)
