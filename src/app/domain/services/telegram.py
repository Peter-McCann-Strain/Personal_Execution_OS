"""Telegram bot service: message handling, formatting, and security."""

import asyncio
import uuid
from uuid import UUID

import structlog
from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyParameters,
)
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.app.core.exceptions import (
    AppError,
    DatabaseError,
    EvaluationError,
    LLMError,
    MCPError,
    RoutingError,
    SearchError,
)
from src.app.core.response_envelope import split_telegram_text
from src.app.core.security import verify_telegram_user
from src.app.domain.models import MessageInput
from src.app.domain.services.approval_callbacks import (
    get_registry as get_approval_registry,
)
from src.app.domain.services.approval_callbacks import (
    maybe_handle_edit_reply,
    register_approval_handlers,
)
from src.app.domain.services.chat import persist_recorded_trace, process_message
from src.app.persistence.repositories.interactions import update_channel_metrics

logger = structlog.get_logger()

router = Router()

# Callback data prefixes for inline keyboards
_CB_MOOD = "mood:"
_CB_ENERGY = "energy:"
_CB_REVIEW_REFLECT = "review_reflect"
_CB_REVIEW_PRIORITIES = "review_priorities"
_CB_FEEDBACK_UP = "fb_up:"
_CB_FEEDBACK_DOWN = "fb_dn:"


def _user_safe_error_message(exc: AppError) -> str:
    """Render a specific, actionable Telegram error message per failure type.

    Each error type gets a distinct message so the user knows exactly what
    failed and whether his data was saved. Never a generic wall of text.
    """
    if isinstance(exc, RoutingError):
        return (
            "❓ I couldn't determine what action to take from that.\n\n"
            "I handle:\n"
            "• 📝 Diary — capture thoughts, mood, daily events\n"
            "• 🔍 Memory — search everything you've captured\n"
            "• 🔬 Research — web research and synthesis\n"
            "• 📋 Projects — tasks, planning, prioritisation\n"
            "• 📅 Calendar / Email — schedule and communications\n"
            "• 🔔 Reminders — alerts and notifications\n"
            "• 📊 Review — weekly/quarterly review and patterns\n\n"
            "Rephrase as one of those, or say explicitly what you'd like saved."
        )

    if isinstance(exc, DatabaseError):
        return (
            "❌ <b>Save FAILED</b> — your data was NOT stored.\n\n"
            "There was a database error on my side. Please try again."
        )

    if isinstance(exc, LLMError):
        return (
            "⚠️ My AI service timed out or returned an error.\n\n"
            "<b>Nothing was saved or acted on.</b> Try again in a moment."
        )

    if isinstance(exc, MCPError):
        tool = getattr(exc, "tool_name", None) or "an external tool"
        return (
            f"❌ <b>{tool} failed</b> — the action was NOT completed.\n\n"
            "Try again, or rephrase if you think I misunderstood."
        )

    if isinstance(exc, SearchError):
        return (
            "⚠️ Memory search hit an error. Your message was received but "
            "I couldn't retrieve relevant context. Try again."
        )

    if isinstance(exc, EvaluationError):
        # Evaluation failures should not block the user — log only.
        logger.warning("evaluation_error_surfaced_to_user", exc_info=exc)
        return (
            "⚠️ There was an internal quality-check error. "
            "Your request may have been processed — check if any action occurred, "
            "then try again if needed."
        )

    # For bare AppError with a "<specialist>_dependency_failed: <ErrorClass>"
    # message produced in chat.py, surface both pieces so the user knows
    # which specialist failed and the underlying failure class.
    raw = str(exc).strip()
    if raw.endswith("_dependency_failed") or "_dependency_failed:" in raw:
        return f"⚠️ {raw}. <b>Nothing was saved or acted on.</b> Try again in a moment."
    return "⚠️ Something went wrong on my side. Try again in a moment."


class TelegramService:
    """Manages the Telegram bot lifecycle and message handling."""

    def __init__(
        self,
        bot_token: str,
        allowed_user_ids: list[int],
        anthropic_api_key: str,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.bot = Bot(token=bot_token)
        self.dp = Dispatcher()
        self.allowed_user_ids = allowed_user_ids
        self.client = AsyncAnthropic(api_key=anthropic_api_key)
        self.session_factory = session_factory
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register all message handlers."""
        self.dp.message.register(self._handle_start, CommandStart())
        self.dp.message.register(self._handle_plan_day, Command("planday"))
        self.dp.message.register(self._handle_review_cmd, Command("review"))
        self.dp.callback_query.register(
            self._handle_mood_callback,
            F.data.startswith(_CB_MOOD),
        )
        self.dp.callback_query.register(
            self._handle_energy_callback,
            F.data.startswith(_CB_ENERGY),
        )
        self.dp.callback_query.register(
            self._handle_review_reflect,
            F.data == _CB_REVIEW_REFLECT,
        )
        self.dp.callback_query.register(
            self._handle_review_priorities,
            F.data == _CB_REVIEW_PRIORITIES,
        )
        self.dp.callback_query.register(
            self._handle_feedback_callback,
            F.data.startswith(_CB_FEEDBACK_UP),
        )
        self.dp.callback_query.register(
            self._handle_feedback_callback,
            F.data.startswith(_CB_FEEDBACK_DOWN),
        )
        # HITL approval buttons for mutating tool calls.
        register_approval_handlers(self.dp)
        self.dp.message.register(self._handle_message)

    async def _handle_start(self, message: types.Message) -> None:
        """Handle /start command."""
        if not self._check_auth(message):
            return
        await message.answer("Personal Execution OS is online. Send a note or request.")

    async def _handle_message(self, message: types.Message) -> None:
        """Handle text and voice messages."""
        if message.from_user is None:
            logger.warning("telegram_message_no_from_user", chat_id=message.chat.id)
            return

        if not self._check_auth(message):
            return

        # Extract text from text messages or voice messages
        try:
            text = await self._extract_text(message)
            if text is None:
                await message.answer("Send me text or voice messages.")
                return
        except AppError as exc:
            logger.warning("telegram_input_processing_failed", error_type=type(exc).__name__)
            await message.answer(_user_safe_error_message(exc))
            return

        # HITL: if this chat is expecting an edit follow-up, route the text
        # into the approval registry instead of the normal agent pipeline.
        if get_approval_registry().has_edit_awaiting(message.chat.id):
            consumed = await maybe_handle_edit_reply(message.chat.id, text)
            if consumed:
                await message.answer("Edits received — re-evaluating the tool call.")
                return

        # Bind a trace ID for all downstream logs from this Telegram message
        request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            telegram_user_id=message.from_user.id,
        )

        logger.info(
            "telegram_message_received",
            user_id=message.from_user.id,
            text_length=len(text),
            source_type="voice" if message.voice else "text",
        )

        msg_input = MessageInput(
            content=text,
            source="telegram",
            user_id=str(message.from_user.id),
        )

        typing_task = asyncio.create_task(
            self._maybe_send_chat_action(message.chat.id),
            name="telegram_typing_hint",
        )
        try:
            async with self.session_factory() as session:
                try:
                    response = await process_message(msg_input, self.client, session)
                finally:
                    typing_task.cancel()
                    await _await_cancelled(typing_task)
                try:
                    await persist_recorded_trace(session, msg_input.metadata)
                except Exception:
                    logger.warning("telegram_trace_persist_failed", exc_info=True)
        except AppError as exc:
            logger.warning("telegram_message_processing_failed", error_type=type(exc).__name__)
            await message.answer(_user_safe_error_message(exc))
            return

        # Build reply with optional feedback buttons
        reply_markup = _build_feedback_keyboard(
            response.metadata.get("interaction_id"),
        )
        delivery_metrics = await self._send_text_chunks(
            message,
            response.content,
            reply_markup=reply_markup,
        )
        await self._persist_delivery_metrics(response, delivery_metrics)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _handle_plan_day(self, message: types.Message) -> None:
        """Handle /planday command — generate a daily plan."""
        if not self._check_auth(message):
            return
        msg_input = MessageInput(
            content="plan my day",
            source="telegram",
            user_id=str(message.from_user.id) if message.from_user else "0",
        )
        try:
            async with self.session_factory() as session:
                response = await process_message(msg_input, self.client, session)
                try:
                    await persist_recorded_trace(session, msg_input.metadata)
                except Exception:
                    logger.warning("telegram_trace_persist_failed", exc_info=True)
        except AppError as exc:
            logger.warning("telegram_plan_day_failed", error_type=type(exc).__name__)
            await message.answer(_user_safe_error_message(exc))
            return
        delivery_metrics = await self._send_text_chunks(message, response.content)
        await self._persist_delivery_metrics(response, delivery_metrics)

    async def _handle_review_cmd(self, message: types.Message) -> None:
        """Handle /review command — trigger weekly review with inline keyboard."""
        if not self._check_auth(message):
            return
        msg_input = MessageInput(
            content="how was my week",
            source="telegram",
            user_id=str(message.from_user.id) if message.from_user else "0",
        )
        try:
            async with self.session_factory() as session:
                response = await process_message(msg_input, self.client, session)
                try:
                    await persist_recorded_trace(session, msg_input.metadata)
                except Exception:
                    logger.warning("telegram_trace_persist_failed", exc_info=True)
        except AppError as exc:
            logger.warning("telegram_review_failed", error_type=type(exc).__name__)
            await message.answer(_user_safe_error_message(exc))
            return

        # Send the review text
        delivery_metrics = await self._send_text_chunks(message, response.content)
        await self._persist_delivery_metrics(response, delivery_metrics)

        # Follow up with interactive keyboard
        await message.answer(
            "How would you rate this week overall?",
            reply_markup=_build_rating_keyboard("mood"),
        )

    async def _maybe_send_chat_action(self, chat_id: int) -> None:
        """Send a typing indicator only if work takes long enough to be noticeable."""
        await asyncio.sleep(0.75)
        try:
            await self.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            logger.debug("telegram_chat_action_failed", exc_info=True)

    async def _send_text_chunks(
        self,
        message: types.Message,
        text: str,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> dict[str, int | bool | str | None]:
        """Send a plain-text Telegram reply, chunked and anchored to the source message."""
        reply_parameters = None
        if getattr(message, "message_id", None) is not None:
            reply_parameters = ReplyParameters(message_id=message.message_id)

        chunks = split_telegram_text(text)
        reply_anchor_requested = reply_parameters is not None
        reply_anchor_used = False
        reply_anchor_dropped = False
        retry_count = 0
        send_failure_count = 0
        chunks_sent = 0
        last_error: str | None = None

        for index, chunk in enumerate(chunks):
            try:
                send_result = await self._answer_with_backoff(
                    message,
                    chunk,
                    reply_markup=reply_markup if index == 0 else None,
                    reply_parameters=reply_parameters if index == 0 else None,
                )
            except Exception as exc:
                send_failure_count += 1
                last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
                logger.warning(
                    "telegram_chunk_send_failed",
                    chunk_index=index,
                    chunk_count=len(chunks),
                    error_type=type(exc).__name__,
                    exc_info=True,
                )
                # Continue delivering remaining chunks — don't abort on a single
                # chunk failure. Only mark fully failed if ALL chunks fail.
                continue

            retry_count += send_result["retry_count"]
            reply_anchor_used = reply_anchor_used or send_result["reply_anchor_used"]
            reply_anchor_dropped = reply_anchor_dropped or send_result["reply_anchor_dropped"]
            chunks_sent += 1

        delivery_status = "sent"
        if send_failure_count:
            delivery_status = "partial_failure" if chunks_sent > 0 else "failed"

        return {
            "renderer": "telegram",
            "preferred_format": "html",
            "parse_mode": "HTML",
            "render_passed": delivery_status == "sent",
            "delivery_status": delivery_status,
            "chunk_count": len(chunks),
            "chunks_sent": chunks_sent,
            "send_failure_count": send_failure_count,
            "feedback_keyboard_attached": bool(reply_markup),
            "reply_anchor_requested": reply_anchor_requested,
            "reply_anchor_used": reply_anchor_used,
            "reply_anchor_dropped": reply_anchor_dropped,
            "retry_count": retry_count,
            "last_delivery_error": last_error,
        }

    # ------------------------------------------------------------------
    # Inline keyboard callback handlers
    # ------------------------------------------------------------------

    async def _handle_mood_callback(self, callback: types.CallbackQuery) -> None:
        """Handle mood rating button press."""
        if callback.data is None:
            return
        score = callback.data.removeprefix(_CB_MOOD)
        await callback.answer(f"Mood recorded: {score}/10")

        # Log the mood as a diary entry
        if callback.message and callback.from_user:
            msg_input = MessageInput(
                content=f"Mood rating: {score}/10",
                source="telegram",
                user_id=str(callback.from_user.id),
            )
            async with self.session_factory() as session:
                await process_message(msg_input, self.client, session)

        # Follow up with energy rating
        if callback.message:
            await callback.message.answer(
                "And your energy level?",
                reply_markup=_build_rating_keyboard("energy"),
            )

    async def _handle_energy_callback(self, callback: types.CallbackQuery) -> None:
        """Handle energy rating button press."""
        if callback.data is None:
            return
        score = callback.data.removeprefix(_CB_ENERGY)
        await callback.answer(f"Energy recorded: {score}/10")

        # Log the energy as a diary entry
        if callback.message and callback.from_user:
            msg_input = MessageInput(
                content=f"Energy rating: {score}/10",
                source="telegram",
                user_id=str(callback.from_user.id),
            )
            async with self.session_factory() as session:
                await process_message(msg_input, self.client, session)

        # Offer reflection and priorities
        if callback.message:
            await callback.message.answer(
                "What would you like to do next?",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Write a reflection",
                                callback_data=_CB_REVIEW_REFLECT,
                            ),
                            InlineKeyboardButton(
                                text="Set priorities",
                                callback_data=_CB_REVIEW_PRIORITIES,
                            ),
                        ],
                    ]
                ),
            )

    async def _handle_review_reflect(self, callback: types.CallbackQuery) -> None:
        """Prompt user to write a reflection."""
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Write your reflection for this week. I'll capture it as a diary entry."
            )

    async def _handle_review_priorities(self, callback: types.CallbackQuery) -> None:
        """Prompt user to set next week's priorities."""
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "What are your top 3 priorities for next week? "
                "Send them as a message and I'll track them."
            )

    async def _handle_feedback_callback(self, callback: CallbackQuery) -> None:
        """Handle thumbs up/down feedback on a response."""
        if callback.data is None:
            return

        from datetime import UTC, datetime
        from uuid import UUID

        from src.app.domain.constants import FeedbackRating
        from src.app.persistence.repositories.interactions import (
            get_interaction_by_id,
            update_feedback,
        )

        is_up = callback.data.startswith(_CB_FEEDBACK_UP)
        prefix = _CB_FEEDBACK_UP if is_up else _CB_FEEDBACK_DOWN
        interaction_id_hex = callback.data.removeprefix(prefix)

        try:
            interaction_id = UUID(interaction_id_hex)
        except ValueError:
            logger.warning("invalid_feedback_id", raw=interaction_id_hex)
            await callback.answer("Invalid feedback reference.")
            return

        rating = FeedbackRating.THUMBS_UP if is_up else FeedbackRating.THUMBS_DOWN

        try:
            async with self.session_factory() as session:
                record = await get_interaction_by_id(session, interaction_id)
                if record is None:
                    await callback.answer("Response not found — may have expired.")
                    await session.rollback()
                    return

                updated = await update_feedback(
                    session,
                    interaction_id,
                    rating=rating,
                    feedback_at=datetime.now(UTC),
                )
                base_metrics = (
                    dict(record.channel_metrics) if isinstance(record.channel_metrics, dict) else {}
                )
                attempts = int(base_metrics.get("feedback_callback_attempts", 0)) + 1
                successes = int(base_metrics.get("feedback_callback_successes", 0))
                if updated:
                    successes += 1

                merged_metrics = {
                    **base_metrics,
                    "feedback_callback_attempts": attempts,
                    "feedback_callback_successes": successes,
                    "feedback_callback_status": "saved" if updated else "not_found",
                }
                try:
                    await update_channel_metrics(
                        session,
                        interaction_id,
                        channel_metrics=merged_metrics,
                    )
                except Exception:
                    # Keep feedback capture reliable even if metrics persistence is degraded.
                    logger.warning(
                        "feedback_channel_metrics_update_failed",
                        interaction_id=str(interaction_id),
                        exc_info=True,
                    )
                await session.commit()
        except Exception:
            logger.error("feedback_save_failed", exc_info=True)
            await callback.answer("Failed to save feedback.")
            return

        if updated:
            emoji = "\U0001f44d" if is_up else "\U0001f44e"
            await callback.answer(f"{emoji} Feedback recorded, thanks!")
        else:
            await callback.answer("Response not found — may have expired.")

    # ------------------------------------------------------------------
    # Text extraction
    # ------------------------------------------------------------------

    async def _extract_text(self, message: types.Message) -> str | None:
        """Extract supported text content.

        Audio is deliberately unsupported in the first public release. A
        future local speech-to-text adapter can be added behind an explicit
        consent, retention, and resource-limit boundary.
        """
        if message.text:
            return message.text

        return None

    def _check_auth(self, message: types.Message) -> bool:
        """Verify the user is allowed."""
        user_id = message.from_user.id if message.from_user else 0
        if not verify_telegram_user(user_id, self.allowed_user_ids):
            logger.warning("telegram_unauthorized", user_id=user_id)
            return False
        return True

    async def start_polling(self) -> None:
        """Start long-polling mode (for development)."""
        logger.info("telegram_polling_started")
        await self.dp.start_polling(self.bot)

    async def get_webhook_status(self) -> dict[str, int | str | None]:
        """Fetch current Telegram webhook status for monitoring surfaces."""
        info = await self.bot.get_webhook_info()
        last_error_date = info.last_error_date
        if hasattr(last_error_date, "timestamp"):
            last_error_date = int(last_error_date.timestamp())
        return {
            "url": info.url,
            "pending_update_count": info.pending_update_count,
            "last_error_date": last_error_date,
            "last_error_message": info.last_error_message,
            "max_connections": info.max_connections,
        }

    async def _answer_with_backoff(
        self,
        message: types.Message,
        text: str,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
        reply_parameters: ReplyParameters | None = None,
    ) -> dict[str, int | bool]:
        """Send one text chunk and respect Telegram flood-control backoff."""
        attempts = 0
        reply_anchor_dropped = False
        while True:
            try:
                await message.answer(
                    text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    reply_parameters=reply_parameters,
                )
                return {
                    "retry_count": attempts,
                    "reply_anchor_used": reply_parameters is not None,
                    "reply_anchor_dropped": reply_anchor_dropped,
                }
            except TelegramBadRequest as exc:
                if (
                    reply_parameters is not None
                    and "message to be replied not found" in str(exc).lower()
                ):
                    logger.warning(
                        "telegram_reply_anchor_missing",
                        message_id=reply_parameters.message_id,
                    )
                    reply_parameters = None
                    reply_anchor_dropped = True
                    continue
                raise
            except TelegramRetryAfter as exc:
                attempts += 1
                logger.warning(
                    "telegram_retry_after",
                    retry_after=exc.retry_after,
                    attempts=attempts,
                )
                await asyncio.sleep(float(exc.retry_after))
                if attempts >= 5:
                    raise

    async def _persist_delivery_metrics(
        self,
        response,
        delivery_metrics: dict[str, int | bool | str | None],
    ) -> None:
        """Update persisted channel metrics with actual Telegram delivery results."""
        interaction_id_raw = response.metadata.get("interaction_id")
        if not interaction_id_raw:
            return

        try:
            interaction_id = UUID(str(interaction_id_raw))
        except ValueError:
            logger.warning(
                "telegram_delivery_metrics_invalid_interaction_id",
                raw=interaction_id_raw,
            )
            return

        base_metrics = response.metadata.get("channel_metrics")
        merged_metrics = dict(base_metrics) if isinstance(base_metrics, dict) else {}
        merged_metrics.update(delivery_metrics)

        try:
            async with self.session_factory() as session:
                updated = await update_channel_metrics(
                    session,
                    interaction_id,
                    channel_metrics=merged_metrics,
                )
                if updated:
                    await session.commit()
                else:
                    await session.rollback()
        except Exception:
            logger.warning("telegram_delivery_metrics_persist_failed", exc_info=True)

    async def shutdown(self) -> None:
        """Clean up bot session."""
        await self.client.close()
        await self.bot.session.close()


def _build_rating_keyboard(category: str) -> InlineKeyboardMarkup:
    """Build a 1-10 inline keyboard for mood or energy rating."""
    prefix = _CB_MOOD if category == "mood" else _CB_ENERGY
    row1 = [InlineKeyboardButton(text=str(i), callback_data=f"{prefix}{i}") for i in range(1, 6)]
    row2 = [InlineKeyboardButton(text=str(i), callback_data=f"{prefix}{i}") for i in range(6, 11)]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


def _build_feedback_keyboard(interaction_id: str | None) -> InlineKeyboardMarkup | None:
    """Build a thumbs up/down inline keyboard for response feedback.

    Returns None if feedback is disabled or no interaction_id is available.
    The interaction UUID hex (32 chars) fits within Telegram's 64-byte callback limit.
    """
    if interaction_id is None:
        return None

    try:
        from src.app.config import get_settings

        settings = get_settings()
        if not settings.feedback_enabled:
            return None
    except Exception:
        logger.warning("feedback_keyboard_build_failed", exc_info=True)
        return None

    # UUID hex is 32 chars; prefix is 6 chars; total 38 chars — well within 64-byte limit
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="\U0001f44d",
                    callback_data=f"{_CB_FEEDBACK_UP}{interaction_id}",
                ),
                InlineKeyboardButton(
                    text="\U0001f44e",
                    callback_data=f"{_CB_FEEDBACK_DOWN}{interaction_id}",
                ),
            ],
        ]
    )


_MARKDOWN_V2_SPECIAL = frozenset(r"_*[]()~`>#+-=|{}.!")


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return "".join(f"\\{c}" if c in _MARKDOWN_V2_SPECIAL else c for c in text)


async def _await_cancelled(task: asyncio.Task[None]) -> None:
    """Await a cancelled background task without surfacing CancelledError."""
    try:
        await task
    except asyncio.CancelledError:
        return
