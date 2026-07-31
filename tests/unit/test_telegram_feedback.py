"""Tests for Telegram feedback inline keyboard and callback handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


class TestBuildFeedbackKeyboard:
    def test_returns_none_when_no_interaction_id(self):
        """Returns None when interaction_id is None."""
        from src.app.domain.services.telegram import _build_feedback_keyboard

        assert _build_feedback_keyboard(None) is None

    def test_returns_keyboard_with_valid_id(self):
        """Returns InlineKeyboardMarkup with thumbs up/down buttons."""
        interaction_id = str(uuid4())

        with patch("src.app.config.get_settings") as mock_settings:
            mock_settings.return_value.feedback_enabled = True
            from src.app.domain.services.telegram import _build_feedback_keyboard

            keyboard = _build_feedback_keyboard(interaction_id)

        assert keyboard is not None
        assert len(keyboard.inline_keyboard) == 1
        row = keyboard.inline_keyboard[0]
        assert len(row) == 2
        # Check callback data contains the interaction ID
        assert interaction_id in row[0].callback_data
        assert interaction_id in row[1].callback_data

    def test_returns_none_when_feedback_disabled(self):
        """Returns None when feedback_enabled is False."""
        with patch("src.app.config.get_settings") as mock_settings:
            mock_settings.return_value.feedback_enabled = False
            from src.app.domain.services.telegram import _build_feedback_keyboard

            keyboard = _build_feedback_keyboard(str(uuid4()))

        assert keyboard is None

    def test_callback_data_fits_telegram_limit(self):
        """Callback data is within Telegram's 64-byte limit."""
        interaction_id = str(uuid4())

        with patch("src.app.config.get_settings") as mock_settings:
            mock_settings.return_value.feedback_enabled = True
            from src.app.domain.services.telegram import _build_feedback_keyboard

            keyboard = _build_feedback_keyboard(interaction_id)

        for button in keyboard.inline_keyboard[0]:
            assert len(button.callback_data.encode("utf-8")) <= 64

    def test_up_button_uses_correct_prefix(self):
        """Thumbs up button uses the fb_up: prefix."""
        interaction_id = str(uuid4())

        with patch("src.app.config.get_settings") as mock_settings:
            mock_settings.return_value.feedback_enabled = True
            from src.app.domain.services.telegram import _build_feedback_keyboard

            keyboard = _build_feedback_keyboard(interaction_id)

        up_button = keyboard.inline_keyboard[0][0]
        assert up_button.callback_data.startswith("fb_up:")

    def test_down_button_uses_correct_prefix(self):
        """Thumbs down button uses the fb_dn: prefix."""
        interaction_id = str(uuid4())

        with patch("src.app.config.get_settings") as mock_settings:
            mock_settings.return_value.feedback_enabled = True
            from src.app.domain.services.telegram import _build_feedback_keyboard

            keyboard = _build_feedback_keyboard(interaction_id)

        down_button = keyboard.inline_keyboard[0][1]
        assert down_button.callback_data.startswith("fb_dn:")


class TestFeedbackCallbackHandler:
    """Tests for the _handle_feedback_callback method on TelegramService."""

    @pytest.mark.asyncio
    async def test_thumbs_up_saves_feedback(self):
        """Thumbs up callback saves positive feedback."""
        interaction_id = uuid4()
        callback = MagicMock()
        callback.data = f"fb_up:{interaction_id}"
        callback.answer = AsyncMock()
        callback.from_user = MagicMock()
        callback.from_user.id = 12345

        from contextlib import asynccontextmanager

        mock_session = AsyncMock()

        @asynccontextmanager
        async def mock_session_factory():
            yield mock_session

        with (
            patch(
                "src.app.persistence.repositories.interactions.get_interaction_by_id",
                new_callable=AsyncMock,
                return_value=MagicMock(channel_metrics={}),
            ),
            patch(
                "src.app.persistence.repositories.interactions.update_feedback",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_update,
            patch(
                "src.app.domain.services.telegram.update_channel_metrics",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            from src.app.domain.services.telegram import TelegramService

            service = TelegramService.__new__(TelegramService)
            service.session_factory = mock_session_factory
            await service._handle_feedback_callback(callback)

        mock_update.assert_awaited_once()
        update_kwargs = mock_update.call_args.kwargs
        assert update_kwargs["rating"] == "thumbs_up"
        callback.answer.assert_awaited()

    @pytest.mark.asyncio
    async def test_thumbs_down_saves_feedback(self):
        """Thumbs down callback saves negative feedback."""
        interaction_id = uuid4()
        callback = MagicMock()
        callback.data = f"fb_dn:{interaction_id}"
        callback.answer = AsyncMock()

        from contextlib import asynccontextmanager

        mock_session = AsyncMock()

        @asynccontextmanager
        async def mock_session_factory():
            yield mock_session

        with (
            patch(
                "src.app.persistence.repositories.interactions.get_interaction_by_id",
                new_callable=AsyncMock,
                return_value=MagicMock(channel_metrics={}),
            ),
            patch(
                "src.app.persistence.repositories.interactions.update_feedback",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_update,
            patch(
                "src.app.domain.services.telegram.update_channel_metrics",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            from src.app.domain.services.telegram import TelegramService

            service = TelegramService.__new__(TelegramService)
            service.session_factory = mock_session_factory
            await service._handle_feedback_callback(callback)

        update_kwargs = mock_update.call_args.kwargs
        assert update_kwargs["rating"] == "thumbs_down"

    @pytest.mark.asyncio
    async def test_invalid_uuid_handled(self):
        """Invalid UUID in callback data is handled gracefully."""
        callback = MagicMock()
        callback.data = "fb_up:not-a-valid-uuid"
        callback.answer = AsyncMock()

        from src.app.domain.services.telegram import TelegramService

        service = TelegramService.__new__(TelegramService)
        await service._handle_feedback_callback(callback)

        callback.answer.assert_awaited_once()
        assert "Invalid" in callback.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_none_callback_data(self):
        """Callback with None data is ignored."""
        callback = MagicMock()
        callback.data = None

        from src.app.domain.services.telegram import TelegramService

        service = TelegramService.__new__(TelegramService)
        await service._handle_feedback_callback(callback)
        # Should not raise or call anything

    @pytest.mark.asyncio
    async def test_not_found_interaction(self):
        """Shows appropriate message when interaction record not found."""
        interaction_id = uuid4()
        callback = MagicMock()
        callback.data = f"fb_up:{interaction_id}"
        callback.answer = AsyncMock()

        from contextlib import asynccontextmanager

        mock_session = AsyncMock()

        @asynccontextmanager
        async def mock_session_factory():
            yield mock_session

        with (
            patch(
                "src.app.persistence.repositories.interactions.get_interaction_by_id",
                new_callable=AsyncMock,
                return_value=MagicMock(channel_metrics={}),
            ),
            patch(
                "src.app.persistence.repositories.interactions.update_feedback",
                new_callable=AsyncMock,
                return_value=False,  # Not found
            ),
            patch(
                "src.app.domain.services.telegram.update_channel_metrics",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            from src.app.domain.services.telegram import TelegramService

            service = TelegramService.__new__(TelegramService)
            service.session_factory = mock_session_factory
            await service._handle_feedback_callback(callback)

        callback.answer.assert_awaited()
        assert "not found" in callback.answer.call_args[0][0]
