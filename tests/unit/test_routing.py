"""Tests for supervisor intent classification."""

import json

import anthropic
import pytest

from src.app.core.exceptions import RoutingError
from src.app.domain.models import IntentType, Specialist
from src.app.domain.services.orchestrator import classify_intent
from tests.conftest import make_anthropic_response


@pytest.mark.asyncio
async def test_classify_diary_intent(mock_anthropic_client):
    """Diary-like message should route to diary specialist."""
    response_data = {
        "intent_type": "capture",
        "confidence": 0.95,
        "specialist": "diary",
        "reasoning": "User is recording a personal thought",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    intent = await classify_intent("Had a great lunch with Sarah today", mock_anthropic_client)

    assert intent.intent_type == IntentType.CAPTURE
    assert intent.specialist == Specialist.DIARY
    assert intent.confidence == 0.95


@pytest.mark.asyncio
async def test_classify_query_intent(mock_anthropic_client):
    """Question about past info should route to memory specialist."""
    response_data = {
        "intent_type": "query",
        "confidence": 0.88,
        "specialist": "memory",
        "reasoning": "User is searching for past information",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    intent = await classify_intent("What did I write about last Monday?", mock_anthropic_client)

    assert intent.intent_type == IntentType.QUERY
    assert intent.specialist == Specialist.MEMORY


@pytest.mark.asyncio
async def test_classify_bottleneck_question_routes_to_review_without_llm(mock_anthropic_client):
    """High-signal review questions should short-circuit before model routing."""
    intent = await classify_intent(
        "What do you think my biggest current bottleneck is?",
        mock_anthropic_client,
    )

    assert intent.intent_type == IntentType.REVIEW
    assert intent.specialist == Specialist.REVIEW
    assert intent.confidence == 0.98
    mock_anthropic_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_classify_temporal_recall_routes_to_memory_without_llm(mock_anthropic_client):
    """High-signal temporal recall prompts should bypass model routing."""
    intent = await classify_intent("What was I working on yesterday?", mock_anthropic_client)

    assert intent.intent_type == IntentType.QUERY
    assert intent.specialist == Specialist.MEMORY
    assert intent.confidence == 0.97
    mock_anthropic_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_classify_meta_assistant_question_routes_to_memory_without_llm(mock_anthropic_client):
    """Assistant capability questions should route to memory directly."""
    intent = await classify_intent("Explain how you work?", mock_anthropic_client)

    assert intent.intent_type == IntentType.QUERY
    assert intent.specialist == Specialist.MEMORY
    assert intent.confidence == 0.97
    mock_anthropic_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_classify_save_note_routes_to_save_without_llm(mock_anthropic_client):
    """Explicit note-save commands should bypass model routing."""
    intent = await classify_intent(
        "Add this to notes fixed teelgram parse mode and retry handling",
        mock_anthropic_client,
    )

    assert intent.intent_type == IntentType.SAVE
    assert intent.specialist == Specialist.SAVE
    assert intent.confidence == 0.99
    mock_anthropic_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_classify_save_url_routes_to_save_without_llm(mock_anthropic_client):
    """Explicit URL save commands should route to save deterministically."""
    intent = await classify_intent(
        "save https://example.com/reliability-plan",
        mock_anthropic_client,
    )

    assert intent.intent_type == IntentType.SAVE
    assert intent.specialist == Specialist.SAVE
    assert intent.confidence == 0.99
    mock_anthropic_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_classify_raises_on_api_failure(mock_anthropic_client):
    """LLM API failure should surface as a RoutingError."""
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)

    with pytest.raises(RoutingError, match=r"Routing failed: routing failed: Connection error\."):
        await classify_intent("test message", mock_anthropic_client)


@pytest.mark.asyncio
async def test_classify_raises_on_invalid_json(mock_anthropic_client):
    """Invalid JSON from LLM should raise RoutingError."""
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        "this is not json at all"
    )

    with pytest.raises(RoutingError, match="Failed to parse"):
        await classify_intent("test message", mock_anthropic_client)


@pytest.mark.asyncio
async def test_classify_raises_on_invalid_intent(mock_anthropic_client):
    """Valid JSON but invalid intent values should raise RoutingError."""
    response_data = {
        "intent_type": "nonexistent_type",
        "confidence": 0.5,
        "specialist": "diary",
        "reasoning": "bad data",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    with pytest.raises(RoutingError):
        await classify_intent("test", mock_anthropic_client)


@pytest.mark.asyncio
async def test_classify_plan_tomorrow_short_circuits_to_plan_day(mock_anthropic_client):
    """Bug 4 regression: 'Plan tomorrow: ...' must route to plan_day, not diary.

    The Haiku classifier was defaulting long capture-style 'Plan tomorrow: ...'
    messages to diary. Heuristic short-circuit now guarantees plan_day.
    """
    intent = await classify_intent(
        "Plan tomorrow: 9-11 deep work on the SLO follow-ups, 11am team standup, "
        "12-1 lunch, 2-4 comms triage, 4-5 docs polish.",
        mock_anthropic_client,
    )

    assert intent.intent_type == IntentType.PLAN_DAY
    assert intent.specialist == Specialist.PLAN_DAY
    assert intent.confidence >= 0.95
    mock_anthropic_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_classify_plan_today_short_circuits_to_plan_day(mock_anthropic_client):
    """Bug 4 regression: 'Plan today: ...' also short-circuits to plan_day."""
    intent = await classify_intent(
        "Plan today: deep work on retrieval quality, then ship the weekly review.",
        mock_anthropic_client,
    )

    assert intent.specialist == Specialist.PLAN_DAY
    mock_anthropic_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_classify_add_a_task_short_circuits_to_project(mock_anthropic_client):
    """Bug 2 regression: 'Add a task: ...' must route to project deterministically."""
    intent = await classify_intent(
        "Add a task: write the deploy/rollback runbook before the next release.",
        mock_anthropic_client,
    )

    assert intent.intent_type == IntentType.PROJECT
    assert intent.specialist == Specialist.PROJECT
    mock_anthropic_client.messages.create.assert_not_called()
