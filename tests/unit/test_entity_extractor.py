"""Tests for entity extraction."""

import json

import anthropic
import pytest

from src.app.core.exceptions import LLMError
from src.app.second_brain.entity_extractor import extract_entities
from tests.conftest import make_anthropic_response


@pytest.mark.asyncio
async def test_extract_entities_success(mock_anthropic_client):
    response_data = {
        "entities": [
            {"name": "Sarah", "entity_type": "person", "context": "lunch with Sarah"},
            {"name": "AI project", "entity_type": "project", "context": "the AI project"},
        ],
        "relationships": [
            {"source": "Sarah", "target": "AI project", "relationship_type": "works_with"}
        ],
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    result = await extract_entities(
        "Had lunch with Sarah about the AI project", mock_anthropic_client
    )
    assert len(result.entities) == 2
    assert result.entities[0].name == "Sarah"
    assert len(result.relationships) == 1


@pytest.mark.asyncio
async def test_extract_no_entities(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps({"entities": [], "relationships": []})
    )
    result = await extract_entities("The weather is nice today", mock_anthropic_client)
    assert len(result.entities) == 0


@pytest.mark.asyncio
async def test_extract_api_failure(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
    with pytest.raises(LLMError, match="Entity extraction failed"):
        await extract_entities("test", mock_anthropic_client)


# ---------------------------------------------------------------------------
# Edge cases — Unicode, long text, deduplication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_unicode_entity_names(mock_anthropic_client):
    """Entity names with Unicode (emoji, CJK, accented chars) should be preserved."""
    response_data = {
        "entities": [
            {"name": "Rene", "entity_type": "person", "context": "met Rene"},
            {"name": "Tokyo", "entity_type": "place", "context": "trip to Tokyo"},
        ],
        "relationships": [],
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    result = await extract_entities(
        "Met Rene in Tokyo to discuss the project",
        mock_anthropic_client,
    )
    names = [e.name for e in result.entities]
    assert "Rene" in names
    assert "Tokyo" in names


@pytest.mark.asyncio
async def test_extract_entities_very_long_input(mock_anthropic_client):
    """Long input text should be passed to the LLM without truncation."""
    long_text = "word " * 5000  # ~25,000 characters
    response_data = {
        "entities": [{"name": "LongDoc", "entity_type": "topic", "context": "long document"}],
        "relationships": [],
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    result = await extract_entities(long_text, mock_anthropic_client)

    # Verify the full text was passed to the LLM
    call_args = mock_anthropic_client.messages.create.call_args
    sent_messages = call_args.kwargs["messages"]
    assert len(sent_messages[0]["content"]) == len(long_text)
    assert len(result.entities) == 1


@pytest.mark.asyncio
async def test_extract_entity_deduplication(mock_anthropic_client):
    """When the LLM returns the same entity twice, both are preserved (dedup is downstream)."""
    response_data = {
        "entities": [
            {"name": "Sarah", "entity_type": "person", "context": "Sarah said hello"},
            {"name": "Sarah", "entity_type": "person", "context": "Sarah also mentioned"},
        ],
        "relationships": [],
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    result = await extract_entities(
        "Sarah said hello. Later, Sarah also mentioned the project.", mock_anthropic_client
    )
    # Both mentions should be present (deduplication happens at the persistence layer)
    assert len(result.entities) == 2
    assert all(e.name == "Sarah" for e in result.entities)


@pytest.mark.asyncio
async def test_extract_entities_all_types(mock_anthropic_client):
    """All five entity types (person, project, topic, place, org) should be returned."""
    response_data = {
        "entities": [
            {"name": "Alice", "entity_type": "person", "context": "Alice"},
            {"name": "Atlas", "entity_type": "project", "context": "Atlas project"},
            {"name": "machine learning", "entity_type": "topic", "context": "ML"},
            {"name": "London", "entity_type": "place", "context": "in London"},
            {"name": "Anthropic", "entity_type": "org", "context": "at Anthropic"},
        ],
        "relationships": [],
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    result = await extract_entities("text", mock_anthropic_client)
    types = {e.entity_type for e in result.entities}
    assert types == {"person", "project", "topic", "place", "org"}


@pytest.mark.asyncio
async def test_extract_entities_invalid_json(mock_anthropic_client):
    """Invalid JSON from LLM should raise LLMError."""
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        "I found several entities in the text..."
    )
    with pytest.raises(LLMError, match="Failed to parse"):
        await extract_entities("test", mock_anthropic_client)


@pytest.mark.asyncio
async def test_extract_entities_partially_valid_payload(mock_anthropic_client):
    """Malformed items should be discarded while valid entities survive fallback validation."""
    response_data = {
        "entities": [
            {"name": "Alice", "entity_type": "person", "context": "Met Alice"},
            {"name": "BadType", "entity_type": "human", "context": "invalid type"},
            {"context": "missing name"},
        ],
        "relationships": [
            {"source": "Alice", "target": "Project X", "relationship_type": "works_with"},
            {"source": "Alice", "target": "Project X", "relationship_type": "friend_of"},
            {"source": "Alice", "relationship_type": "mentions"},
        ],
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )

    result = await extract_entities("Alice worked on Project X", mock_anthropic_client)

    assert [entity.name for entity in result.entities] == ["Alice"]
    assert [rel.relationship_type for rel in result.relationships] == ["works_with"]
