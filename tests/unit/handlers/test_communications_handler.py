"""Tests for communications handler — email triage and drafting."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.domain.models import (
    ChatResponse,
    Intent,
    IntentType,
    MessageInput,
    Specialist,
)


def _make_message(content: str = "Triage this email from Bob") -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _make_intent() -> Intent:
    return Intent(
        intent_type=IntentType.COMMAND,
        confidence=0.9,
        specialist=Specialist.COMMUNICATIONS,
        reasoning="email handling",
    )


def _make_email_classification():
    classification = MagicMock()
    classification.classification = "ACTION_REQUIRED"
    classification.sender = "bob@example.com"
    classification.subject_summary = "Project deadline extension"
    classification.urgency_reason = "Deadline tomorrow"
    classification.suggested_action = "Reply with new timeline"
    classification.response_deadline = "tomorrow"
    classification.user_reply = "Bob needs a timeline update on the project deadline."
    classification.safety_flags = ["untrusted_external_input", "untrusted_external_email"]
    return classification


def _make_email_draft():
    draft = MagicMock()
    draft.subject = "Re: Project deadline"
    draft.body = "Hi Bob,\n\nI can extend the deadline to Friday.\n\nBest regards"
    draft.tone = "professional"
    draft.user_reply = "Here's a clean draft you can send."
    draft.safety_flags = ["untrusted_external_input", "untrusted_external_email"]
    return draft


def _make_episode_mock():
    episode = MagicMock()
    episode.id = uuid.uuid4()
    return episode


@pytest.mark.asyncio
async def test_handle_communications_triage_happy_path():
    """handle_communications triages email when no draft keywords present."""
    message = _make_message("Triage this email from Bob about the project")
    intent = _make_intent()
    classification = _make_email_classification()

    with (
        patch(
            "src.app.domain.services.handlers.communications.triage_email",
            new_callable=AsyncMock,
            return_value=classification,
        ) as mock_triage,
        patch(
            "src.app.domain.services.handlers.communications.create_artifact_record",
            new_callable=AsyncMock,
        ) as mock_artifact,
    ):
        from src.app.domain.services.handlers.communications import (
            handle_communications,
        )

        result = await handle_communications(message, AsyncMock(), AsyncMock(), intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "communications"
    assert "Bob needs a timeline update on the project deadline." in result.content
    assert "Category: ACTION_REQUIRED." in result.content
    assert result.metadata["classification"] == "ACTION_REQUIRED"
    assert result.metadata["user_reply"] == classification.user_reply
    assert result.metadata["safety_flags"] == classification.safety_flags
    assert result.metadata["content_blocks"][0]["type"] == "text"
    assert result.metadata["content_blocks"][0]["text"] == classification.user_reply
    assert result.metadata["content_blocks"][1]["type"] == "bullet_list"
    mock_triage.assert_awaited_once()
    mock_artifact.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_communications_draft_happy_path():
    """handle_communications drafts email when draft keywords present."""
    message = _make_message("Draft a reply to Bob's email about the deadline")
    intent = _make_intent()
    draft = _make_email_draft()
    episode = _make_episode_mock()

    mock_session = AsyncMock()

    with (
        patch(
            "src.app.domain.services.handlers.communications.draft_reply",
            new_callable=AsyncMock,
            return_value=draft,
        ) as mock_draft,
        patch(
            "src.app.domain.services.handlers.communications.create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch(
            "src.app.domain.services.handlers.communications.create_artifact_record",
            new_callable=AsyncMock,
        ) as mock_artifact,
    ):
        from src.app.domain.services.handlers.communications import (
            handle_communications,
        )

        result = await handle_communications(message, AsyncMock(), mock_session, intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "communications"
    assert "Here's a clean draft you can send." in result.content
    assert "Re: Project deadline" in result.content
    assert "extend the deadline" in result.content
    assert result.metadata["episode_id"] == str(episode.id)
    assert result.metadata["tone"] == "professional"
    assert result.metadata["safety_flags"] == draft.safety_flags
    assert result.metadata["content_blocks"][0]["text"] == draft.user_reply
    assert result.metadata["content_blocks"][1] == {
        "type": "field",
        "title": "Subject",
        "text": "Re: Project deadline",
    }
    mock_draft.assert_awaited_once()
    assert mock_session.commit.await_count == 2
    mock_artifact.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_communications_draft_keywords_detection():
    """handle_communications detects all draft keywords correctly."""
    draft_messages = [
        "Draft an email about the meeting",
        "Reply to this message from Alice",
        "Respond to the client inquiry",
        "Write back to the team lead",
        "Compose a message to HR",
    ]

    draft = _make_email_draft()
    episode = _make_episode_mock()
    intent = _make_intent()

    for msg_content in draft_messages:
        message = _make_message(msg_content)

        with (
            patch(
                "src.app.domain.services.handlers.communications.draft_reply",
                new_callable=AsyncMock,
                return_value=draft,
            ) as mock_draft,
            patch(
                "src.app.domain.services.handlers.communications.create_episode",
                new_callable=AsyncMock,
                return_value=episode,
            ),
            patch(
                "src.app.domain.services.handlers.communications.create_artifact_record",
                new_callable=AsyncMock,
            ),
        ):
            from src.app.domain.services.handlers.communications import (
                handle_communications,
            )

            result = await handle_communications(message, AsyncMock(), AsyncMock(), intent)

        mock_draft.assert_awaited_once(), f"'{msg_content}' should trigger draft"
        assert result.agent == "communications"


@pytest.mark.asyncio
async def test_handle_communications_triage_no_urgency():
    """handle_communications triage handles missing urgency/action gracefully."""
    message = _make_message("Classify this email")
    intent = _make_intent()

    classification = MagicMock()
    classification.classification = "FYI"
    classification.sender = "newsletter@example.com"
    classification.subject_summary = "Weekly digest"
    classification.user_reply = ""
    classification.urgency_reason = None
    classification.suggested_action = None
    classification.response_deadline = None

    with (
        patch(
            "src.app.domain.services.handlers.communications.triage_email",
            new_callable=AsyncMock,
            return_value=classification,
        ),
        patch(
            "src.app.domain.services.handlers.communications.create_artifact_record",
            new_callable=AsyncMock,
        ),
    ):
        from src.app.domain.services.handlers.communications import (
            handle_communications,
        )

        result = await handle_communications(message, AsyncMock(), AsyncMock(), intent)

    assert result.content == (
        "newsletter@example.com is asking about Weekly digest.\n\nCategory: FYI."
    )


@pytest.mark.asyncio
async def test_handle_communications_triage_can_include_labels_when_requested():
    """Explicit triage requests can include a short labeled breakdown."""
    message = _make_message("Triage and classify this email")
    intent = _make_intent()
    classification = _make_email_classification()

    with (
        patch(
            "src.app.domain.services.handlers.communications.triage_email",
            new_callable=AsyncMock,
            return_value=classification,
        ),
        patch(
            "src.app.domain.services.handlers.communications.create_artifact_record",
            new_callable=AsyncMock,
        ),
    ):
        from src.app.domain.services.handlers.communications import handle_communications

        result = await handle_communications(message, AsyncMock(), AsyncMock(), intent)

    assert "Category: ACTION_REQUIRED." in result.content
    assert "Next step: Reply with new timeline." in result.content
    assert result.metadata["content_blocks"][1]["items"] == [
        "Category: ACTION_REQUIRED",
        "Next step: Reply with new timeline",
        "Deadline: tomorrow",
    ]


@pytest.mark.asyncio
async def test_handle_communications_triage_entity_extraction_failure_is_swallowed():
    """Triage should still return a reply if entity extraction enqueue fails."""
    message = _make_message("Classify this email")
    intent = _make_intent()
    classification = _make_email_classification()

    with (
        patch(
            "src.app.domain.services.handlers.communications.triage_email",
            new_callable=AsyncMock,
            return_value=classification,
        ),
        patch(
            "src.app.domain.services.handlers.communications.create_artifact_record",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.communications.enqueue_entity_extraction",
            new_callable=AsyncMock,
            side_effect=RuntimeError("queue unavailable"),
        ),
    ):
        from src.app.domain.services.handlers.communications import (
            handle_communications,
        )

        result = await handle_communications(message, AsyncMock(), AsyncMock(), intent)

    assert result.agent == "communications"
    assert "timeline update" in result.content.lower()


@pytest.mark.asyncio
async def test_handle_communications_draft_entity_extraction_failure_is_swallowed():
    """Drafting should still return the draft if entity extraction enqueue fails."""
    message = _make_message("Draft a reply to Bob's email about the deadline")
    intent = _make_intent()
    draft = _make_email_draft()
    episode = _make_episode_mock()

    mock_session = AsyncMock()

    with (
        patch(
            "src.app.domain.services.handlers.communications.draft_reply",
            new_callable=AsyncMock,
            return_value=draft,
        ),
        patch(
            "src.app.domain.services.handlers.communications.create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch(
            "src.app.domain.services.handlers.communications.create_artifact_record",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.communications.enqueue_entity_extraction",
            new_callable=AsyncMock,
            side_effect=RuntimeError("queue unavailable"),
        ),
    ):
        from src.app.domain.services.handlers.communications import (
            handle_communications,
        )

        result = await handle_communications(message, AsyncMock(), mock_session, intent)

    assert result.agent == "communications"
    assert "subject: re: project deadline" in result.content.lower()


@pytest.mark.asyncio
async def test_handle_communications_triage_llm_failure():
    """handle_communications propagates LLM failures from triage."""
    message = _make_message("Triage this")
    intent = _make_intent()

    with (
        patch(
            "src.app.domain.services.handlers.communications.triage_email",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM unavailable"),
        ),
        patch(
            "src.app.domain.services.handlers.communications.create_artifact_record",
            new_callable=AsyncMock,
        ),
        pytest.raises(RuntimeError, match="LLM unavailable"),
    ):
        from src.app.domain.services.handlers.communications import (
            handle_communications,
        )

        await handle_communications(message, AsyncMock(), AsyncMock(), intent)
