"""Tests for the save handler — URL capture and note capture."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from src.app.core.exceptions import LLMError
from src.app.core.url_extractor import ExtractedContent
from src.app.domain.models import Intent, IntentType, MessageInput, Specialist
from src.app.domain.services.handlers.save import (
    NoteCaptureDecision,
    SaveSummary,
    handle_save,
)


def _make_message(content: str) -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _make_intent() -> Intent:
    return Intent(
        intent_type=IntentType.SAVE,
        confidence=0.95,
        specialist=Specialist.SAVE,
        reasoning="Save request",
    )


def _make_episode():
    return SimpleNamespace(id=uuid.uuid4())


def _make_note():
    return SimpleNamespace(id=uuid.uuid4())


class TestHandleSave:
    async def test_missing_url_match_returns_retry_boundary_response(self):
        """A corrupted persisted retry must not dereference a missing regex match."""
        from src.app.domain.services.handlers.save import _handle_url_save

        result = await _handle_url_save(
            client=AsyncMock(),
            session=AsyncMock(),
            url_match=None,
        )

        assert result.metadata["error"] == "missing_url"

    async def test_missing_save_target_requests_clarification(self):
        """Message without a URL or explicit note command should clarify."""
        message = _make_message("can you remember this for me")

        result = await handle_save(message, AsyncMock(), AsyncMock(), _make_intent())

        assert result.agent == "save"
        assert result.metadata.get("error") == "missing_save_target"
        assert result.metadata.get("clarification_requested") is True

    async def test_note_capture_without_content_requests_clarification(self):
        """Placeholder note-save command should ask for concrete note text."""
        message = _make_message("save this please")

        with patch(
            "src.app.domain.services.handlers.save.call_and_parse_with_retry",
            new_callable=AsyncMock,
        ) as mock_parse:
            result = await handle_save(message, AsyncMock(), AsyncMock(), _make_intent())

        assert result.agent == "save"
        assert result.metadata.get("error") == "missing_note_content"
        assert result.metadata.get("clarification_requested") is True
        mock_parse.assert_not_awaited()

    async def test_note_capture_success_stores_normalized_note(self):
        """Explicit add-to-notes command should store cleaned note content."""
        message = _make_message(
            "add this to notes teelgram parse mode still wrong and notifcation failed twice"
        )
        mock_client = AsyncMock()
        mock_session = AsyncMock()
        note = _make_note()

        decision = NoteCaptureDecision(
            should_save=True,
            confidence=0.96,
            title="Telegram delivery fixes",
            normalized_note=(
                "Telegram parse mode is still wrong, and notification delivery failed twice."
            ),
            tags=["telegram", "delivery"],
            para_category="project",
            note_type="fleeting",
            missing_details=[],
            clarification_question="",
            user_reply="Saved a cleaned note about Telegram delivery failures.",
        )

        with (
            patch(
                "src.app.domain.services.handlers.save.call_and_parse_with_retry",
                new_callable=AsyncMock,
                return_value=decision,
            ),
            patch(
                "src.app.domain.services.handlers.save.create_note",
                new_callable=AsyncMock,
                return_value=note,
            ) as mock_create_note,
        ):
            result = await handle_save(message, mock_client, mock_session, _make_intent())

        assert result.agent == "save"
        assert result.content.startswith('Saved note "Telegram delivery fixes"')
        assert result.metadata["title"] == "Telegram delivery fixes"
        assert result.metadata["note_type"] == "fleeting"
        assert result.metadata["normalized_note"] == decision.normalized_note
        assert result.metadata["receipt_text"].startswith('Saved note "Telegram delivery fixes"')
        assert result.metadata["pending_conversation_action_cleared"] is True
        mock_session.commit.assert_awaited_once()
        mock_create_note.assert_awaited_once()
        _, kwargs = mock_create_note.await_args
        assert kwargs["content"] == decision.normalized_note
        assert "add this to notes" not in kwargs["content"].lower()

    async def test_note_capture_low_confidence_requests_follow_up(self):
        """Uncertain note capture should ask for details and avoid persistence."""
        message = _make_message("add this to notes deployment thing from yesterday")
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        decision = NoteCaptureDecision(
            should_save=False,
            confidence=0.51,
            title="",
            normalized_note="",
            tags=[],
            para_category="resource",
            note_type="fleeting",
            missing_details=["project_name", "desired_outcome"],
            clarification_question="Which project was this, and what outcome should I record?",
            user_reply="",
        )

        with (
            patch(
                "src.app.domain.services.handlers.save.call_and_parse_with_retry",
                new_callable=AsyncMock,
                return_value=decision,
            ),
            patch(
                "src.app.domain.services.handlers.save.create_note",
                new_callable=AsyncMock,
            ) as mock_create_note,
        ):
            result = await handle_save(message, mock_client, mock_session, _make_intent())

        assert result.agent == "save"
        assert result.content == decision.clarification_question
        assert result.metadata["clarification_requested"] is True
        assert result.metadata["missing_details"] == ["project_name", "desired_outcome"]
        mock_create_note.assert_not_awaited()
        mock_session.commit.assert_not_called()

    async def test_note_capture_parse_failure_returns_clarification(self):
        """Structured parse errors should preserve the payload for retry."""
        message = _make_message("add this to notes parser still breaks on null fields")
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        with patch(
            "src.app.domain.services.handlers.save.call_and_parse_with_retry",
            new_callable=AsyncMock,
            side_effect=LLMError("Failed to parse save_note_capture"),
        ):
            result = await handle_save(message, mock_client, mock_session, _make_intent())

        assert result.agent == "save"
        assert "try again" in result.content.lower()
        assert result.metadata["error"] == "note_capture_parse_failed"
        assert "pending_conversation_action" in result.metadata
        mock_session.commit.assert_not_called()

    async def test_extraction_failure_returns_error(self):
        """HTTP errors during fetch should return a retryable user-friendly error."""
        message = _make_message("save https://example.com/broken")

        with patch(
            "src.app.domain.services.handlers.save.extract_url_content",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            result = await handle_save(message, AsyncMock(), AsyncMock(), _make_intent())

        assert result.agent == "save"
        assert "try again" in result.content.lower()
        assert result.metadata.get("error") == "extraction_failed"

    async def test_empty_content_returns_error(self):
        """Extracted page with no readable text should return an error."""
        message = _make_message("save https://example.com/empty")

        extracted = ExtractedContent(title="Empty", text="", url="https://example.com/empty")
        with patch(
            "src.app.domain.services.handlers.save.extract_url_content",
            new_callable=AsyncMock,
            return_value=extracted,
        ):
            result = await handle_save(message, AsyncMock(), AsyncMock(), _make_intent())

        assert "Couldn't extract" in result.content
        assert result.metadata.get("error") == "no_content"

    async def test_successful_save_with_llm_summary(self):
        """Full URL pipeline: extract -> summarise -> store -> respond."""
        message = _make_message("save https://example.com/article")
        mock_client = AsyncMock()
        mock_session = AsyncMock()
        episode = _make_episode()

        extracted = ExtractedContent(
            title="Great Article",
            text="This is a great article about testing.",
            url="https://example.com/article",
            word_count=7,
        )

        summary_data = {
            "title": "Great Article",
            "summary": "An article about testing practices.",
            "tags": ["testing", "development"],
            "para_category": "resource",
        }

        with (
            patch(
                "src.app.domain.services.handlers.save.extract_url_content",
                new_callable=AsyncMock,
                return_value=extracted,
            ),
            patch(
                "src.app.domain.services.handlers.save.call_and_parse_with_retry",
                new_callable=AsyncMock,
                return_value=SaveSummary(**summary_data),
            ),
            patch(
                "src.app.domain.services.handlers.save.create_episode",
                new_callable=AsyncMock,
                return_value=episode,
            ),
            patch(
                "src.app.domain.services.handlers.save.enqueue_entity_extraction",
                new_callable=AsyncMock,
            ) as mock_enqueue,
        ):
            result = await handle_save(message, mock_client, mock_session, _make_intent())

        assert result.agent == "save"
        assert result.content.startswith('Saved "Great Article".')
        assert result.metadata["url"] == "https://example.com/article"
        assert result.metadata["tags"] == ["testing", "development"]
        assert result.metadata["pending_conversation_action_cleared"] is True
        mock_session.commit.assert_awaited_once()
        mock_enqueue.assert_awaited_once()

    async def test_llm_summarise_failure_returns_retryable_response(self):
        """If URL summarisation fails, the handler should preserve the exact retry payload."""
        message = _make_message("save https://example.com/article")
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        extracted = ExtractedContent(
            title="Fallback Title",
            text="This is the raw extracted text from the page.",
            url="https://example.com/article",
            word_count=9,
        )

        with (
            patch(
                "src.app.domain.services.handlers.save.extract_url_content",
                new_callable=AsyncMock,
                return_value=extracted,
            ),
            patch(
                "src.app.domain.services.handlers.save.call_and_parse_with_retry",
                new_callable=AsyncMock,
                side_effect=LLMError("LLM down"),
            ),
            patch(
                "src.app.domain.services.handlers.save.create_episode",
                new_callable=AsyncMock,
                return_value=_make_episode(),
            ),
            patch(
                "src.app.domain.services.handlers.save.enqueue_entity_extraction",
                new_callable=AsyncMock,
            ),
        ):
            result = await handle_save(message, mock_client, mock_session, _make_intent())

        assert result.agent == "save"
        assert "try again" in result.content.lower()
        assert result.metadata["error"] == "save_summarise_failed"
        assert "pending_conversation_action" in result.metadata

    async def test_url_extraction_strips_trailing_punctuation(self):
        """URLs followed by punctuation should be cleaned up."""
        message = _make_message("save https://example.com/article.")
        mock_client = AsyncMock()
        mock_session = AsyncMock()
        episode = _make_episode()

        extracted = ExtractedContent(
            title="Article",
            text="Content here.",
            url="https://example.com/article",
            word_count=2,
        )

        with (
            patch(
                "src.app.domain.services.handlers.save.extract_url_content",
                new_callable=AsyncMock,
                return_value=extracted,
            ) as mock_extract,
            patch(
                "src.app.domain.services.handlers.save.call_and_parse_with_retry",
                new_callable=AsyncMock,
                return_value=SaveSummary(
                    title="Article",
                    summary="Summary.",
                    tags=[],
                    para_category="resource",
                ),
            ),
            patch(
                "src.app.domain.services.handlers.save.create_episode",
                new_callable=AsyncMock,
                return_value=episode,
            ),
            patch(
                "src.app.domain.services.handlers.save.enqueue_entity_extraction",
                new_callable=AsyncMock,
            ),
        ):
            await handle_save(message, mock_client, mock_session, _make_intent())

        mock_extract.assert_awaited_once_with("https://example.com/article")
