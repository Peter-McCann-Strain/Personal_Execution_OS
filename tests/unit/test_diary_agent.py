"""Tests for the diary agent."""

import json

import anthropic
import pytest

from src.app.agents.specialists.diary import process_diary_entry
from src.app.core.exceptions import LLMError
from tests.conftest import make_anthropic_response


@pytest.mark.asyncio
async def test_process_diary_entry_success(mock_anthropic_client):
    """Valid diary entry should return structured DiaryEntry."""
    response_data = {
        "content": "Had lunch with Sarah at the new Italian place",
        "summary": "Lunch with Sarah at Italian restaurant",
        "mood_score": 7.5,
        "energy_rating": 6.0,
        "tags": ["social", "food"],
        "people_mentioned": ["Sarah"],
        "para_category": "area",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    entry = await process_diary_entry(
        "Had lunch with Sarah at the new Italian place", mock_anthropic_client
    )

    assert entry.content == "Had lunch with Sarah at the new Italian place"
    assert entry.summary == "Lunch with Sarah at Italian restaurant"
    assert entry.mood_score == 7.5
    assert entry.people_mentioned == ["Sarah"]
    assert entry.para_category == "area"


@pytest.mark.asyncio
async def test_process_diary_entry_null_mood(mock_anthropic_client):
    """Diary entry with null mood/energy should be valid."""
    response_data = {
        "content": "Quick note: remember to buy milk",
        "summary": "Reminder to buy milk",
        "mood_score": None,
        "energy_rating": None,
        "tags": ["errands"],
        "people_mentioned": [],
        "para_category": "area",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    entry = await process_diary_entry("buy milk", mock_anthropic_client)

    assert entry.mood_score is None
    assert entry.energy_rating is None
    assert entry.tags == ["errands"]


@pytest.mark.asyncio
async def test_process_diary_entry_api_failure(mock_anthropic_client):
    """API failure should raise LLMError, not silently handle."""
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)

    with pytest.raises(LLMError, match="diary agent failed"):
        await process_diary_entry("test entry", mock_anthropic_client)


@pytest.mark.asyncio
async def test_process_diary_entry_bad_json(mock_anthropic_client):
    """Invalid JSON from LLM should raise LLMError after exhausting retries."""
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        "I'm sorry, I can't help with that"
    )

    with pytest.raises(LLMError, match="Failed to parse diary agent after"):
        await process_diary_entry("test entry", mock_anthropic_client)


@pytest.mark.asyncio
async def test_process_diary_entry_mood_validation(mock_anthropic_client):
    """Mood score outside 0-10 range should fail validation."""
    response_data = {
        "content": "entry",
        "summary": "summary",
        "mood_score": 15.0,  # Invalid — out of range
        "energy_rating": 5.0,
        "tags": [],
        "people_mentioned": [],
        "para_category": "area",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    with pytest.raises(LLMError):
        await process_diary_entry("test", mock_anthropic_client)


# ---------------------------------------------------------------------------
# Edge cases — empty content, long content, all PARA categories, null fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_diary_entry_empty_content(mock_anthropic_client):
    """Empty string content should still create an entry."""
    response_data = {
        "content": "",
        "summary": "Empty capture",
        "mood_score": None,
        "energy_rating": None,
        "tags": [],
        "people_mentioned": [],
        "para_category": "area",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    entry = await process_diary_entry("", mock_anthropic_client)

    assert entry.content == ""
    assert entry.summary == "Empty capture"


@pytest.mark.asyncio
async def test_process_diary_entry_very_long_content(mock_anthropic_client):
    """Very long content (5000+ chars) should be processed without truncation."""
    long_content = "Today was an incredible day. " * 250  # ~7000 chars
    response_data = {
        "content": long_content,
        "summary": "A very long diary entry about an incredible day.",
        "mood_score": 8.0,
        "energy_rating": 7.0,
        "tags": ["reflection"],
        "people_mentioned": [],
        "para_category": "area",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    entry = await process_diary_entry(long_content, mock_anthropic_client)

    assert len(entry.content) > 5000
    # Verify the full message was sent to the LLM
    call_args = mock_anthropic_client.messages.create.call_args
    sent_messages = call_args.kwargs["messages"]
    assert len(sent_messages[0]["content"]) == len(long_content)


@pytest.mark.asyncio
async def test_process_diary_entry_para_project(mock_anthropic_client):
    """Entries classified as 'project' should be valid."""
    response_data = {
        "content": "Finished the API routes for the health endpoint",
        "summary": "Completed health endpoint API routes",
        "mood_score": 6.5,
        "energy_rating": 5.0,
        "tags": ["coding", "personal-assistant"],
        "people_mentioned": [],
        "para_category": "project",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    entry = await process_diary_entry("finished health endpoint", mock_anthropic_client)
    assert entry.para_category == "project"


@pytest.mark.asyncio
async def test_process_diary_entry_para_resource(mock_anthropic_client):
    """Entries classified as 'resource' should be valid."""
    response_data = {
        "content": "Read an article about prompt engineering",
        "summary": "Read prompt engineering article",
        "mood_score": None,
        "energy_rating": None,
        "tags": ["learning", "ai"],
        "people_mentioned": [],
        "para_category": "resource",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    entry = await process_diary_entry("prompt engineering article", mock_anthropic_client)
    assert entry.para_category == "resource"


@pytest.mark.asyncio
async def test_process_diary_entry_para_archive(mock_anthropic_client):
    """Entries classified as 'archive' should be valid."""
    response_data = {
        "content": "The old project has been shut down completely",
        "summary": "Old project shutdown complete",
        "mood_score": 5.0,
        "energy_rating": 5.0,
        "tags": ["closure"],
        "people_mentioned": [],
        "para_category": "archive",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    entry = await process_diary_entry("old project shut down", mock_anthropic_client)
    assert entry.para_category == "archive"


@pytest.mark.asyncio
async def test_process_diary_entry_null_para_category(mock_anthropic_client):
    """Null PARA category should be accepted."""
    response_data = {
        "content": "Random thought about existence",
        "summary": "Philosophical musing",
        "mood_score": 5.0,
        "energy_rating": 5.0,
        "tags": ["philosophy"],
        "people_mentioned": [],
        "para_category": None,
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    entry = await process_diary_entry("random thought", mock_anthropic_client)
    assert entry.para_category is None


@pytest.mark.asyncio
async def test_process_diary_entry_both_null_mood_energy(mock_anthropic_client):
    """Both mood_score and energy_rating null should be valid."""
    response_data = {
        "content": "Note to self: check the schedule",
        "summary": "Schedule reminder",
        "mood_score": None,
        "energy_rating": None,
        "tags": ["admin"],
        "people_mentioned": [],
        "para_category": "area",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    entry = await process_diary_entry("check schedule", mock_anthropic_client)
    assert entry.mood_score is None
    assert entry.energy_rating is None


@pytest.mark.asyncio
async def test_process_diary_entry_energy_out_of_range(mock_anthropic_client):
    """Energy rating outside 0-10 range should fail validation."""
    response_data = {
        "content": "entry",
        "summary": "summary",
        "mood_score": 5.0,
        "energy_rating": -3.0,  # Invalid — negative
        "tags": [],
        "people_mentioned": [],
        "para_category": "area",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    with pytest.raises(LLMError):
        await process_diary_entry("test", mock_anthropic_client)


@pytest.mark.asyncio
async def test_process_diary_entry_multiple_people(mock_anthropic_client):
    """Multiple people mentioned should all be captured."""
    response_data = {
        "content": "Had a team meeting with Alice, Bob, and Charlie",
        "summary": "Team meeting with Alice, Bob, and Charlie",
        "mood_score": 6.0,
        "energy_rating": 5.0,
        "tags": ["team", "meeting"],
        "people_mentioned": ["Alice", "Bob", "Charlie"],
        "para_category": "area",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    entry = await process_diary_entry("team meeting", mock_anthropic_client)
    assert len(entry.people_mentioned) == 3
    assert "Alice" in entry.people_mentioned
    assert "Charlie" in entry.people_mentioned


@pytest.mark.asyncio
async def test_process_diary_entry_many_tags(mock_anthropic_client):
    """Entries can have multiple tags."""
    response_data = {
        "content": "Busy day",
        "summary": "Busy day across multiple areas",
        "mood_score": 5.0,
        "energy_rating": 4.0,
        "tags": ["work", "health", "side-project", "reading", "social"],
        "people_mentioned": [],
        "para_category": "area",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    entry = await process_diary_entry("busy day", mock_anthropic_client)
    assert len(entry.tags) == 5
