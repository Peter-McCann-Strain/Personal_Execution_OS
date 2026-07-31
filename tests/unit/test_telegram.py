"""Tests for Telegram service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

from src.app.core.exceptions import LLMError
from src.app.domain.models import ChatResponse
from src.app.domain.services.telegram import (
    TelegramService,
    _build_rating_keyboard,
    escape_markdown_v2,
)

# ------------------------------------------------------------------ #
# Existing escape_markdown_v2 tests (kept intact)
# ------------------------------------------------------------------ #


def test_escape_markdown_v2_special_chars():
    """All MarkdownV2 special chars should be escaped."""
    assert escape_markdown_v2("hello_world") == r"hello\_world"
    assert escape_markdown_v2("*bold*") == r"\*bold\*"
    assert escape_markdown_v2("test.end") == r"test\.end"


def test_escape_markdown_v2_no_special_chars():
    """Plain text should pass through unchanged."""
    assert escape_markdown_v2("hello world") == "hello world"


def test_escape_markdown_v2_empty_string():
    assert escape_markdown_v2("") == ""


def test_escape_markdown_v2_multiple_specials():
    text = "Hello! How are you? (good) [link]"
    result = escape_markdown_v2(text)
    assert r"\!" in result
    assert r"\?" not in result  # ? is not a special char
    assert r"\(" in result
    assert r"\[" in result


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


def _make_message(*, user_id: int = 12345, text: str | None = None):
    """Build a mock aiogram Message."""
    msg = AsyncMock()
    msg.answer = AsyncMock()
    msg.answer_photo = AsyncMock()

    from_user = MagicMock()
    from_user.id = user_id
    msg.from_user = from_user

    chat = MagicMock()
    chat.id = 999
    msg.chat = chat

    msg.text = text
    msg.voice = None
    msg.audio = None
    return msg


def _make_callback(*, data: str | None, user_id: int = 12345, has_message: bool = True):
    """Build a mock aiogram CallbackQuery."""
    cb = AsyncMock()
    cb.data = data
    cb.answer = AsyncMock()

    from_user = MagicMock()
    from_user.id = user_id
    cb.from_user = from_user

    if has_message:
        cb.message = AsyncMock()
        cb.message.answer = AsyncMock()
    else:
        cb.message = None

    return cb


def _fake_session_factory():
    """Return a session factory that yields an AsyncMock session."""
    session = AsyncMock()

    @asynccontextmanager
    async def _factory():
        yield session

    _factory._inner_session = session  # for test access
    return _factory


@pytest.fixture
def service():
    """Build a TelegramService with fully mocked internals."""
    with (
        patch("src.app.domain.services.telegram.Bot") as mock_bot_cls,
        patch("src.app.domain.services.telegram.AsyncAnthropic") as mock_anthro_cls,
    ):
        mock_bot = MagicMock()
        mock_bot.session = MagicMock()
        mock_bot.session.close = AsyncMock()
        mock_bot.get_file = AsyncMock()
        mock_bot.download_file = AsyncMock()
        mock_bot_cls.return_value = mock_bot

        mock_client = AsyncMock()
        mock_anthro_cls.return_value = mock_client

        sf = _fake_session_factory()

        svc = TelegramService(
            bot_token="test-token",
            allowed_user_ids=[12345],
            anthropic_api_key="test-key",
            session_factory=sf,
        )
        # Expose internals for assertions
        svc._mock_bot = mock_bot
        svc._mock_client = mock_client
        svc._mock_session = sf._inner_session
        return svc


# ------------------------------------------------------------------ #
# _build_rating_keyboard
# ------------------------------------------------------------------ #


class TestBuildRatingKeyboard:
    def test_mood_keyboard_structure(self):
        kb = _build_rating_keyboard("mood")
        assert isinstance(kb, InlineKeyboardMarkup)
        assert len(kb.inline_keyboard) == 2
        # Row 1: buttons 1-5, Row 2: buttons 6-10
        assert len(kb.inline_keyboard[0]) == 5
        assert len(kb.inline_keyboard[1]) == 5

    def test_mood_callback_data_prefix(self):
        kb = _build_rating_keyboard("mood")
        first_btn = kb.inline_keyboard[0][0]
        assert first_btn.callback_data == "mood:1"
        last_btn = kb.inline_keyboard[1][-1]
        assert last_btn.callback_data == "mood:10"

    def test_energy_callback_data_prefix(self):
        kb = _build_rating_keyboard("energy")
        first_btn = kb.inline_keyboard[0][0]
        assert first_btn.callback_data == "energy:1"
        last_btn = kb.inline_keyboard[1][-1]
        assert last_btn.callback_data == "energy:10"

    def test_button_labels_are_numbers(self):
        kb = _build_rating_keyboard("mood")
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert labels == [str(i) for i in range(1, 11)]


# ------------------------------------------------------------------ #
# TelegramService.__init__ and _register_handlers
# ------------------------------------------------------------------ #


class TestInit:
    def test_attributes_set(self, service: TelegramService):
        assert service.allowed_user_ids == [12345]
        assert service.bot is service._mock_bot
        assert service.client is service._mock_client

    def test_dispatcher_created(self, service: TelegramService):
        """Dispatcher should exist and have handlers registered."""
        assert service.dp is not None


# ------------------------------------------------------------------ #
# _check_auth
# ------------------------------------------------------------------ #


class TestCheckAuth:
    def test_authorized_user(self, service: TelegramService):
        msg = _make_message(user_id=12345)
        assert service._check_auth(msg) is True

    def test_unauthorized_user(self, service: TelegramService):
        msg = _make_message(user_id=99999)
        assert service._check_auth(msg) is False

    def test_no_from_user(self, service: TelegramService):
        msg = _make_message()
        msg.from_user = None
        assert service._check_auth(msg) is False


# ------------------------------------------------------------------ #
# _handle_start
# ------------------------------------------------------------------ #


class TestHandleStart:
    async def test_authorized_start(self, service: TelegramService):
        msg = _make_message(user_id=12345)
        await service._handle_start(msg)
        msg.answer.assert_awaited_once_with(
            "Personal Execution OS is online. Send a note or request."
        )

    async def test_unauthorized_start(self, service: TelegramService):
        msg = _make_message(user_id=99999)
        await service._handle_start(msg)
        msg.answer.assert_not_awaited()


class TestAnswerWithBackoff:
    async def test_retries_without_reply_anchor_when_target_missing(
        self,
        service: TelegramService,
    ):
        msg = _make_message(user_id=12345)
        bad_request = TelegramBadRequest(
            method=MagicMock(),
            message="Bad Request: message to be replied not found",
        )
        msg.answer = AsyncMock(side_effect=[bad_request, None])

        from aiogram.types import ReplyParameters

        await service._answer_with_backoff(
            msg,
            "hello",
            reply_parameters=ReplyParameters(message_id=42),
        )

        assert msg.answer.await_count == 2
        first_call = msg.answer.await_args_list[0]
        second_call = msg.answer.await_args_list[1]
        assert first_call.kwargs["reply_parameters"].message_id == 42
        assert second_call.kwargs["reply_parameters"] is None


class TestSendTextChunks:
    async def test_delivery_metrics_mark_failed_when_send_errors(
        self,
        service: TelegramService,
    ):
        msg = _make_message(user_id=12345)
        msg.answer = AsyncMock(
            side_effect=TelegramBadRequest(
                method=MagicMock(),
                message="Bad Request: chat not found",
            )
        )

        metrics = await service._send_text_chunks(msg, "hello world")

        assert metrics["delivery_status"] == "failed"
        assert metrics["send_failure_count"] == 1
        assert metrics["chunks_sent"] == 0
        assert metrics["render_passed"] is False
        assert metrics["last_delivery_error"] is not None

    async def test_delivery_metrics_mark_partial_failure_when_later_chunk_fails(
        self,
        service: TelegramService,
    ):
        msg = _make_message(user_id=12345)
        msg.answer = AsyncMock(
            side_effect=[
                None,
                TelegramBadRequest(
                    method=MagicMock(),
                    message="Bad Request: chat not found",
                ),
            ]
        )
        long_text = ("chunk " * 900).strip()

        metrics = await service._send_text_chunks(msg, long_text)

        assert metrics["delivery_status"] == "partial_failure"
        assert metrics["send_failure_count"] == 1
        assert metrics["chunks_sent"] == 1
        assert metrics["chunk_count"] >= 2
        assert metrics["render_passed"] is False


# ------------------------------------------------------------------ #
# _handle_message
# ------------------------------------------------------------------ #


class TestHandleMessage:
    async def test_no_from_user(self, service: TelegramService):
        msg = _make_message()
        msg.from_user = None
        await service._handle_message(msg)
        msg.answer.assert_not_awaited()

    async def test_unauthorized(self, service: TelegramService):
        msg = _make_message(user_id=99999, text="hello")
        await service._handle_message(msg)
        msg.answer.assert_not_awaited()

    async def test_no_text_no_voice(self, service: TelegramService):
        """Message with no text and no voice should prompt the user."""
        msg = _make_message(user_id=12345)
        msg.text = None
        msg.voice = None
        msg.audio = None
        await service._handle_message(msg)
        msg.answer.assert_awaited_once_with("Send me text or voice messages.")

    @patch("src.app.domain.services.telegram.process_message")
    async def test_text_message(self, mock_pm, service: TelegramService):
        response = ChatResponse(content="Hi there", agent="diary")
        mock_pm.return_value = response

        msg = _make_message(user_id=12345, text="hello")
        await service._handle_message(msg)

        mock_pm.assert_awaited_once()
        call_args = mock_pm.call_args
        assert call_args[0][0].content == "hello"
        assert call_args[0][0].source == "telegram"
        assert call_args[0][0].user_id == "12345"

        msg.answer.assert_awaited_once()
        answer_text = msg.answer.call_args[0][0]
        assert "Hi there" in answer_text
        assert msg.answer.call_args.kwargs.get("parse_mode") == "HTML"

    @patch("src.app.domain.services.telegram.process_message")
    async def test_voice_message(self, mock_pm, service: TelegramService):
        """Voice messages should be transcribed then processed."""
        response = ChatResponse(content="Got it", agent="diary")
        mock_pm.return_value = response

        msg = _make_message(user_id=12345)
        msg.text = None
        voice = MagicMock()
        voice.file_id = "voice123"
        voice.duration = 5
        msg.voice = voice
        msg.audio = None

        # Patch _extract_text to return transcribed text
        with patch.object(service, "_extract_text", return_value="transcribed"):
            await service._handle_message(msg)

        mock_pm.assert_awaited_once()
        call_args = mock_pm.call_args
        assert call_args[0][0].content == "transcribed"

    @patch("src.app.domain.services.telegram.process_message")
    async def test_internal_app_errors_are_sanitized(self, mock_pm, service: TelegramService):
        """Telegram should not leak raw internal parsing failures to the user."""
        mock_pm.side_effect = LLMError(
            "Failed to parse diary agent response: raw model output here"
        )

        msg = _make_message(user_id=12345, text="What do you think my biggest bottleneck is?")
        await service._handle_message(msg)

        msg.answer.assert_awaited_once()
        answer_text = msg.answer.call_args[0][0]
        # Should show the specific LLMError message, not the raw internal error
        assert "Failed to parse diary agent response" not in answer_text
        # LLMError produces a specific message (not the old generic "Something went wrong")
        assert any(
            phrase in answer_text
            for phrase in [
                "AI service",
                "timed out",
                "Nothing was saved",
            ]
        )

    @patch("src.app.domain.services.telegram.process_message")
    async def test_specialist_dependency_failed_surfaces_specific_reason(
        self,
        mock_pm,
        service: TelegramService,
    ):
        """Bug 1 regression: a generic specialist crash must surface the
        specialist + underlying error class, not the old generic
        'Something went wrong on my side' string.
        """
        from src.app.core.exceptions import AppError

        mock_pm.side_effect = AppError("save_dependency_failed: UndefinedColumnError")

        msg = _make_message(user_id=12345, text="Save this: always defer on side-effects.")
        await service._handle_message(msg)

        msg.answer.assert_awaited_once()
        answer_text = msg.answer.call_args[0][0]
        assert "save_dependency_failed" in answer_text
        assert "UndefinedColumnError" in answer_text
        # Must NOT be the generic fallback
        assert "Something went wrong on my side" not in answer_text


# ------------------------------------------------------------------ #
# _handle_plan_day
# ------------------------------------------------------------------ #


class TestHandlePlanDay:
    async def test_unauthorized(self, service: TelegramService):
        msg = _make_message(user_id=99999)
        await service._handle_plan_day(msg)
        msg.answer.assert_not_awaited()

    @patch("src.app.domain.services.telegram.process_message")
    async def test_authorized_plan_day(self, mock_pm, service: TelegramService):
        response = ChatResponse(content="Your plan", agent="diary")
        mock_pm.return_value = response

        msg = _make_message(user_id=12345)
        await service._handle_plan_day(msg)

        mock_pm.assert_awaited_once()
        call_args = mock_pm.call_args
        assert call_args[0][0].content == "plan my day"
        msg.answer.assert_awaited_once()
        assert msg.answer.call_args.kwargs.get("parse_mode") == "HTML"

    @patch("src.app.domain.services.telegram.process_message")
    async def test_plan_day_no_from_user(self, mock_pm, service: TelegramService):
        """When from_user is None, user_id should default to '0'."""
        response = ChatResponse(content="Plan", agent="diary")
        mock_pm.return_value = response

        msg = _make_message(user_id=12345)
        # First pass auth, then set from_user to None for the user_id fallback
        with patch.object(service, "_check_auth", return_value=True):
            msg.from_user = None
            await service._handle_plan_day(msg)

        call_args = mock_pm.call_args
        assert call_args[0][0].user_id == "0"


# ------------------------------------------------------------------ #
# _handle_review_cmd
# ------------------------------------------------------------------ #


class TestHandleReviewCmd:
    async def test_unauthorized(self, service: TelegramService):
        msg = _make_message(user_id=99999)
        await service._handle_review_cmd(msg)
        msg.answer.assert_not_awaited()

    @patch("src.app.domain.services.telegram.process_message")
    async def test_authorized_review(self, mock_pm, service: TelegramService):
        response = ChatResponse(content="Week summary", agent="review")
        mock_pm.return_value = response

        msg = _make_message(user_id=12345)
        await service._handle_review_cmd(msg)

        mock_pm.assert_awaited_once()
        call_args = mock_pm.call_args
        assert call_args[0][0].content == "how was my week"

        # Should send review text + rating keyboard
        assert msg.answer.await_count == 2
        # Second call should have reply_markup
        second_call = msg.answer.call_args_list[1]
        assert "reply_markup" in second_call.kwargs
        kb = second_call.kwargs["reply_markup"]
        assert isinstance(kb, InlineKeyboardMarkup)

    @patch("src.app.domain.services.telegram.process_message")
    async def test_review_no_from_user(self, mock_pm, service: TelegramService):
        """When from_user is None, user_id should default to '0'."""
        response = ChatResponse(content="Review", agent="review")
        mock_pm.return_value = response

        msg = _make_message(user_id=12345)
        with patch.object(service, "_check_auth", return_value=True):
            msg.from_user = None
            await service._handle_review_cmd(msg)

        call_args = mock_pm.call_args
        assert call_args[0][0].user_id == "0"


# ------------------------------------------------------------------ #
# _handle_charts
# ------------------------------------------------------------------ #


class TestHandleCharts:
    async def test_unauthorized(self, service: TelegramService):
        msg = _make_message(user_id=99999)
        await service._handle_charts(msg)
        msg.answer.assert_not_awaited()

    @patch("src.app.domain.services.telegram.process_message")
    async def test_no_data_available(self, mock_pm, service: TelegramService):
        """When all queries return empty, should show 'No chart data' msg."""
        session = service._mock_session
        result_mock = MagicMock()
        mappings_mock = MagicMock()
        mappings_mock.all.return_value = []
        result_mock.mappings.return_value = mappings_mock
        session.execute = AsyncMock(return_value=result_mock)

        msg = _make_message(user_id=12345)
        await service._handle_charts(msg)

        # First call: "Generating charts...", second: "No chart data available yet."
        assert msg.answer.await_count == 2
        last_call_text = msg.answer.call_args_list[1][0][0]
        assert last_call_text == "No chart data available yet."

    @patch("src.app.core.charts.mood_energy_chart", return_value=b"PNG_DATA")
    @patch("src.app.domain.services.telegram.process_message")
    async def test_mood_chart_sent(self, mock_pm, mock_chart, service: TelegramService):
        """When episodes exist, mood chart should be sent."""
        session = service._mock_session
        episode_data = [
            {"created_at": "2026-01-01", "mood_score": 7, "energy_rating": 6},
        ]

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            mappings = MagicMock()
            # Only first query (mood/energy) returns data
            if call_count == 1:
                mappings.all.return_value = [MagicMock(__getitem__=lambda s, k: episode_data[0][k])]
                # Make dict() conversion work
                row_mock = MagicMock()
                row_mock.__iter__ = MagicMock(return_value=iter(episode_data[0].items()))
                mappings.all.return_value = episode_data
            else:
                mappings.all.return_value = []
            result.mappings.return_value = mappings
            return result

        session.execute = AsyncMock(side_effect=mock_execute)

        msg = _make_message(user_id=12345)
        await service._handle_charts(msg)

        msg.answer_photo.assert_awaited_once()
        # Should NOT say "No chart data"
        answer_texts = [call[0][0] for call in msg.answer.call_args_list if call[0]]
        assert "No chart data available yet." not in answer_texts

    @patch("src.app.domain.services.telegram.process_message")
    async def test_charts_exception_handling(self, mock_pm, service: TelegramService):
        """Exceptions in chart generation should be caught, not crash."""
        session = service._mock_session
        session.execute = AsyncMock(side_effect=Exception("DB error"))

        msg = _make_message(user_id=12345)
        await service._handle_charts(msg)

        # Should still get "Generating charts..." and "No chart data"
        assert msg.answer.await_count == 2
        last_call_text = msg.answer.call_args_list[1][0][0]
        assert last_call_text == "No chart data available yet."

    @patch("src.app.core.charts.goal_progress_chart", return_value=b"GOAL_PNG")
    @patch("src.app.core.charts.habit_streak_chart", return_value=b"HABIT_PNG")
    @patch("src.app.core.charts.mood_energy_chart", return_value=b"MOOD_PNG")
    @patch("src.app.domain.services.telegram.process_message")
    async def test_all_charts_sent(
        self,
        mock_pm,
        mock_mood,
        mock_habit,
        mock_goal,
        service: TelegramService,
    ):
        """When all three chart types have data, three charts are sent."""
        session = service._mock_session

        async def mock_execute(query):
            result = MagicMock()
            mappings = MagicMock()
            mappings.all.return_value = [{"some": "data"}]
            result.mappings.return_value = mappings
            return result

        session.execute = AsyncMock(side_effect=mock_execute)

        msg = _make_message(user_id=12345)
        await service._handle_charts(msg)

        assert msg.answer_photo.await_count == 3
        # No "No chart data" message
        answer_texts = [call[0][0] for call in msg.answer.call_args_list if call[0]]
        assert "No chart data available yet." not in answer_texts

    @patch("src.app.core.charts.mood_energy_chart", return_value=None)
    @patch("src.app.domain.services.telegram.process_message")
    async def test_chart_returns_none(
        self,
        mock_pm,
        mock_chart,
        service: TelegramService,
    ):
        """When chart function returns None, chart is not sent."""
        session = service._mock_session

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            mappings = MagicMock()
            if call_count == 1:
                mappings.all.return_value = [{"some": "data"}]
            else:
                mappings.all.return_value = []
            result.mappings.return_value = mappings
            return result

        session.execute = AsyncMock(side_effect=mock_execute)

        msg = _make_message(user_id=12345)
        await service._handle_charts(msg)

        # chart returned None so answer_photo should not be called
        msg.answer_photo.assert_not_awaited()

    @patch("src.app.core.charts.goal_progress_chart", return_value=None)
    @patch("src.app.core.charts.habit_streak_chart", return_value=None)
    @patch("src.app.core.charts.mood_energy_chart", return_value=b"MOOD_PNG")
    @patch("src.app.domain.services.telegram.process_message")
    async def test_habit_and_goal_charts_return_none(
        self,
        mock_pm,
        mock_mood,
        mock_habit,
        mock_goal,
        service: TelegramService,
    ):
        """Habit/goal branches should tolerate chart builders returning None."""
        session = service._mock_session

        async def mock_execute(query):
            result = MagicMock()
            mappings = MagicMock()
            mappings.all.return_value = [{"some": "data"}]
            result.mappings.return_value = mappings
            return result

        session.execute = AsyncMock(side_effect=mock_execute)

        msg = _make_message(user_id=12345)
        await service._handle_charts(msg)

        # Mood chart sent, habit/goal chart builders returned None
        assert msg.answer_photo.await_count == 1
        sent_names = [call.args[0].filename for call in msg.answer_photo.call_args_list]
        assert sent_names == ["mood_energy.png"]

    @patch("src.app.core.charts.mood_energy_chart", return_value=b"PNG")
    @patch("src.app.core.charts.habit_streak_chart", side_effect=Exception("fail"))
    @patch("src.app.domain.services.telegram.process_message")
    async def test_partial_chart_failure(
        self,
        mock_pm,
        mock_habit,
        mock_mood,
        service: TelegramService,
    ):
        """If one chart fails, others should still be sent."""
        session = service._mock_session

        async def mock_execute(query):
            result = MagicMock()
            mappings = MagicMock()
            mappings.all.return_value = [{"some": "data"}]
            result.mappings.return_value = mappings
            return result

        session.execute = AsyncMock(side_effect=mock_execute)

        msg = _make_message(user_id=12345)
        await service._handle_charts(msg)

        # mood succeeds, habit fails, goal may succeed or fail
        assert msg.answer_photo.await_count >= 1


# ------------------------------------------------------------------ #
# _send_chart
# ------------------------------------------------------------------ #


class TestSendChart:
    async def test_send_chart(self, service: TelegramService):
        msg = _make_message()
        await service._send_chart(msg, b"fake_png", "test.png")
        msg.answer_photo.assert_awaited_once()


# ------------------------------------------------------------------ #
# _handle_mood_callback
# ------------------------------------------------------------------ #


class TestHandleMoodCallback:
    async def test_no_callback_data(self, service: TelegramService):
        cb = _make_callback(data=None)
        await service._handle_mood_callback(cb)
        cb.answer.assert_not_awaited()

    @patch("src.app.domain.services.telegram.process_message")
    async def test_mood_recorded(self, mock_pm, service: TelegramService):
        response = ChatResponse(content="Logged", agent="diary")
        mock_pm.return_value = response

        cb = _make_callback(data="mood:7")
        await service._handle_mood_callback(cb)

        cb.answer.assert_awaited_once_with("Mood recorded: 7/10")
        mock_pm.assert_awaited_once()
        call_args = mock_pm.call_args
        assert call_args[0][0].content == "Mood rating: 7/10"

        # Should follow up with energy keyboard
        cb.message.answer.assert_awaited_once()
        kb_call = cb.message.answer.call_args
        assert "reply_markup" in kb_call.kwargs

    @patch("src.app.domain.services.telegram.process_message")
    async def test_mood_no_message(self, mock_pm, service: TelegramService):
        """No message on callback — skip diary log and energy follow-up."""
        cb = _make_callback(data="mood:5", has_message=False)
        cb.from_user = None
        await service._handle_mood_callback(cb)

        cb.answer.assert_awaited_once_with("Mood recorded: 5/10")
        mock_pm.assert_not_awaited()

    @patch("src.app.domain.services.telegram.process_message")
    async def test_mood_no_from_user(self, mock_pm, service: TelegramService):
        """If from_user is None, diary log is skipped but energy follows."""
        cb = _make_callback(data="mood:8")
        cb.from_user = None
        await service._handle_mood_callback(cb)

        cb.answer.assert_awaited_once_with("Mood recorded: 8/10")
        mock_pm.assert_not_awaited()
        # Energy follow-up still sent because message exists
        cb.message.answer.assert_awaited_once()


# ------------------------------------------------------------------ #
# _handle_energy_callback
# ------------------------------------------------------------------ #


class TestHandleEnergyCallback:
    async def test_no_callback_data(self, service: TelegramService):
        cb = _make_callback(data=None)
        await service._handle_energy_callback(cb)
        cb.answer.assert_not_awaited()

    @patch("src.app.domain.services.telegram.process_message")
    async def test_energy_recorded(self, mock_pm, service: TelegramService):
        response = ChatResponse(content="Logged", agent="diary")
        mock_pm.return_value = response

        cb = _make_callback(data="energy:6")
        await service._handle_energy_callback(cb)

        cb.answer.assert_awaited_once_with("Energy recorded: 6/10")
        mock_pm.assert_awaited_once()
        call_args = mock_pm.call_args
        assert call_args[0][0].content == "Energy rating: 6/10"

        # Should follow up with reflect/priorities keyboard
        cb.message.answer.assert_awaited_once()
        kb_call = cb.message.answer.call_args
        assert "reply_markup" in kb_call.kwargs
        kb = kb_call.kwargs["reply_markup"]
        assert isinstance(kb, InlineKeyboardMarkup)
        # Two buttons in one row
        assert len(kb.inline_keyboard) == 1
        assert len(kb.inline_keyboard[0]) == 2

    @patch("src.app.domain.services.telegram.process_message")
    async def test_energy_no_message(self, mock_pm, service: TelegramService):
        cb = _make_callback(data="energy:3", has_message=False)
        cb.from_user = None
        await service._handle_energy_callback(cb)

        cb.answer.assert_awaited_once_with("Energy recorded: 3/10")
        mock_pm.assert_not_awaited()

    @patch("src.app.domain.services.telegram.process_message")
    async def test_energy_no_from_user(self, mock_pm, service: TelegramService):
        cb = _make_callback(data="energy:9")
        cb.from_user = None
        await service._handle_energy_callback(cb)

        cb.answer.assert_awaited_once_with("Energy recorded: 9/10")
        mock_pm.assert_not_awaited()
        # Follow-up still sent
        cb.message.answer.assert_awaited_once()


# ------------------------------------------------------------------ #
# _handle_review_reflect
# ------------------------------------------------------------------ #


class TestHandleReviewReflect:
    async def test_with_message(self, service: TelegramService):
        cb = _make_callback(data="review_reflect")
        await service._handle_review_reflect(cb)

        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()
        text = cb.message.answer.call_args[0][0]
        assert "reflection" in text.lower()

    async def test_no_message(self, service: TelegramService):
        cb = _make_callback(data="review_reflect", has_message=False)
        await service._handle_review_reflect(cb)

        cb.answer.assert_awaited_once()
        # No message to answer on


# ------------------------------------------------------------------ #
# _handle_review_priorities
# ------------------------------------------------------------------ #


class TestHandleReviewPriorities:
    async def test_with_message(self, service: TelegramService):
        cb = _make_callback(data="review_priorities")
        await service._handle_review_priorities(cb)

        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()
        text = cb.message.answer.call_args[0][0]
        assert "priorities" in text.lower()

    async def test_no_message(self, service: TelegramService):
        cb = _make_callback(data="review_priorities", has_message=False)
        await service._handle_review_priorities(cb)

        cb.answer.assert_awaited_once()


# ------------------------------------------------------------------ #
# _handle_feedback_callback
# ------------------------------------------------------------------ #


class TestHandleFeedbackCallback:
    async def test_no_callback_data(self, service: TelegramService):
        cb = _make_callback(data=None)
        await service._handle_feedback_callback(cb)
        cb.answer.assert_not_awaited()

    async def test_invalid_feedback_reference(self, service: TelegramService):
        cb = _make_callback(data="fb_up:not-a-uuid")

        await service._handle_feedback_callback(cb)

        cb.answer.assert_awaited_once_with("Invalid feedback reference.")

    async def test_feedback_save_failure(self, service: TelegramService):
        cb = _make_callback(data="fb_up:12345678123456781234567812345678")

        with patch(
            "src.app.persistence.repositories.interactions.update_feedback",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.side_effect = RuntimeError("db down")
            await service._handle_feedback_callback(cb)

        cb.answer.assert_awaited_once_with("Failed to save feedback.")

    async def test_feedback_recorded_up(self, service: TelegramService):
        cb = _make_callback(data="fb_up:12345678123456781234567812345678")
        cb.message = MagicMock()
        cb.message.answer = AsyncMock()

        with patch(
            "src.app.persistence.repositories.interactions.update_feedback",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_update:
            await service._handle_feedback_callback(cb)

        mock_update.assert_awaited_once()
        cb.answer.assert_awaited_once()
        assert "👍" in cb.answer.call_args.args[0]

    async def test_feedback_not_found_down(self, service: TelegramService):
        cb = _make_callback(data="fb_dn:12345678123456781234567812345678")
        cb.message = MagicMock()
        cb.message.answer = AsyncMock()

        with patch(
            "src.app.persistence.repositories.interactions.update_feedback",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await service._handle_feedback_callback(cb)

        cb.answer.assert_awaited_once_with("Response not found — may have expired.")


# ------------------------------------------------------------------ #
# _build_feedback_keyboard
# ------------------------------------------------------------------ #


class TestBuildFeedbackKeyboard:
    def test_returns_none_when_interaction_id_missing(self):
        from src.app.domain.services.telegram import _build_feedback_keyboard

        assert _build_feedback_keyboard(None) is None

    def test_returns_none_when_feedback_disabled(self):
        from src.app.domain.services.telegram import _build_feedback_keyboard

        settings = MagicMock()
        settings.feedback_enabled = False

        with patch("src.app.config.get_settings", return_value=settings):
            assert _build_feedback_keyboard("12345678123456781234567812345678") is None

    def test_returns_none_when_settings_lookup_fails(self):
        from src.app.domain.services.telegram import _build_feedback_keyboard

        with patch("src.app.config.get_settings", side_effect=RuntimeError("boom")):
            assert _build_feedback_keyboard("12345678123456781234567812345678") is None

    def test_returns_keyboard_when_enabled(self):
        from src.app.domain.services.telegram import _build_feedback_keyboard

        settings = MagicMock()
        settings.feedback_enabled = True

        with patch("src.app.config.get_settings", return_value=settings):
            kb = _build_feedback_keyboard("12345678123456781234567812345678")

        assert kb is not None
        assert len(kb.inline_keyboard) == 1
        assert len(kb.inline_keyboard[0]) == 2


# ------------------------------------------------------------------ #
# _extract_text
# ------------------------------------------------------------------ #


class TestExtractText:
    async def test_text_message(self, service: TelegramService):
        msg = _make_message(text="hello")
        result = await service._extract_text(msg)
        assert result == "hello"

    async def test_voice_message_is_unsupported(self, service: TelegramService):
        msg = _make_message()
        msg.text = None
        msg.voice = MagicMock()
        result = await service._extract_text(msg)
        assert result is None

    async def test_audio_message_is_unsupported(self, service: TelegramService):
        msg = _make_message()
        msg.text = None
        msg.voice = None
        msg.audio = MagicMock()
        result = await service._extract_text(msg)
        assert result is None

    async def test_no_text_no_voice(self, service: TelegramService):
        msg = _make_message()
        msg.text = None
        msg.voice = None
        msg.audio = None
        result = await service._extract_text(msg)
        assert result is None


# ------------------------------------------------------------------ #
# start_polling and shutdown
# ------------------------------------------------------------------ #


class TestLifecycle:
    async def test_start_polling(self, service: TelegramService):
        service.dp = MagicMock()
        service.dp.start_polling = AsyncMock()

        await service.start_polling()
        service.dp.start_polling.assert_awaited_once_with(service.bot)

    async def test_shutdown(self, service: TelegramService):
        service.bot.session.close = AsyncMock()
        service.client.close = AsyncMock()
        await service.shutdown()
        service.client.close.assert_awaited_once()
        service.bot.session.close.assert_awaited_once()
