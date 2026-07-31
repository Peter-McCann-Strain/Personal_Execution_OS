"""Tests for domain models — validation, serialization."""

import pytest
from pydantic import ValidationError

from src.app.domain.models import (
    ChatResponse,
    DiaryEntry,
    Intent,
    IntentType,
    MessageInput,
    Specialist,
)


def test_intent_valid():
    """Valid intent should construct without error."""
    intent = Intent(
        intent_type=IntentType.CAPTURE,
        confidence=0.9,
        specialist=Specialist.DIARY,
        reasoning="test",
    )
    assert intent.intent_type == IntentType.CAPTURE


def test_intent_confidence_bounds():
    """Confidence must be between 0 and 1."""
    with pytest.raises(ValidationError):
        Intent(
            intent_type=IntentType.CAPTURE,
            confidence=1.5,
            specialist=Specialist.DIARY,
            reasoning="test",
        )

    with pytest.raises(ValidationError):
        Intent(
            intent_type=IntentType.CAPTURE,
            confidence=-0.1,
            specialist=Specialist.DIARY,
            reasoning="test",
        )


def test_diary_entry_mood_bounds():
    """Mood score must be 0-10 or None."""
    entry = DiaryEntry(content="test", summary="test", mood_score=None)
    assert entry.mood_score is None

    entry = DiaryEntry(content="test", summary="test", mood_score=5.0)
    assert entry.mood_score == 5.0

    with pytest.raises(ValidationError):
        DiaryEntry(content="test", summary="test", mood_score=11.0)


def test_message_input_defaults():
    """MessageInput should have sane defaults."""
    msg = MessageInput(content="hello", source="cli", user_id="owner")
    assert msg.metadata == {}
    assert msg.timestamp is not None


def test_chat_response_serialization():
    """ChatResponse should serialize to dict cleanly."""
    resp = ChatResponse(content="hello", agent="diary", metadata={"key": "val"})
    data = resp.model_dump()
    assert data["content"] == "hello"
    assert data["agent"] == "diary"
    assert data["metadata"]["key"] == "val"
