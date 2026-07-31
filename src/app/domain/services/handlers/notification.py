"""Notification handler — notification preferences and fatigue management."""

from __future__ import annotations

import contextlib
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.specialists.notification import FatigueManager
from src.app.config import get_settings
from src.app.core.exceptions import ConfigError
from src.app.core.redis import get_redis_client
from src.app.domain.constants import NotificationCategory
from src.app.domain.models import ChatResponse, Intent, MessageInput
from src.app.domain.services.handlers._common import enqueue_entity_extraction
from src.app.persistence.repositories.scheduled_actions import create_scheduled_action

logger = structlog.get_logger()

# Module-level FatigueManager for notification handling in the API context.
_api_fatigue_manager: FatigueManager | None = None


def _get_or_create_fatigue_manager() -> FatigueManager:
    """Get or create the module-level Redis-backed FatigueManager for API use."""
    global _api_fatigue_manager
    if _api_fatigue_manager is None:
        settings = get_settings()
        redis_url = settings.redis_url.get_secret_value()
        if not redis_url:
            raise ConfigError("Redis is required for notification fatigue management.")
        _api_fatigue_manager = FatigueManager(
            dnd_start=time(settings.notification_dnd_start_hour, 0),
            dnd_end=time(settings.notification_dnd_end_hour, 0),
            redis=get_redis_client(redis_url),
        )
    return _api_fatigue_manager


async def handle_notification(
    message: MessageInput,
    _client: AsyncAnthropic,
    session: AsyncSession,
    _intent: Intent,
) -> ChatResponse:
    """Handle notification preferences, focus mode, status queries, and reminders."""
    response = await _process_notification(message, session=session)

    try:
        await enqueue_entity_extraction(
            episode_id=str(uuid.uuid4()),
            text_content=response.content,
        )
    except Exception as exc:
        logger.warning(
            "notification_entity_extraction_degraded",
            error=str(exc),
            exc_info=True,
        )

    return response


async def _process_notification(
    message: MessageInput,
    *,
    session: AsyncSession,
) -> ChatResponse:
    """Internal notification processing — separated to allow entity extraction on response."""
    # Extract just the current message — strip conversation history wrapper if present
    raw = message.content
    if "Current message:" in raw:
        raw = raw.split("Current message:")[-1].strip()
    content_lower = raw.lower()

    fatigue = _get_or_create_fatigue_manager()

    # Reminder/scheduling: route BEFORE status/focus heuristics so "remind me to
    # send the weekly status..." doesn't accidentally hit the status branch on
    # the word "status". Bug 3 regression.
    if _is_reminder_request(content_lower):
        scheduled = await _try_schedule_reminder(
            message=message,
            session=session,
            current_content=raw,
        )
        if scheduled is not None:
            return scheduled

    # Focus mode toggle
    focus_keywords = ("focus mode", "focus on", "do not disturb")
    if any(kw in content_lower for kw in focus_keywords):
        if any(w in content_lower for w in ("enable", "start", "on", "activate")):
            fatigue.set_focus_mode(True)
            logger.info("notification_routed", path="focus_mode_enable", focus_mode=True)
            return ChatResponse(
                content=(
                    "Focus mode on. Only critical notifications will get through "
                    "— everything else batches until you're done."
                ),
                agent="notification",
                metadata={"focus_mode": True},
            )
        if any(w in content_lower for w in ("disable", "stop", "off", "deactivate")):
            fatigue.set_focus_mode(False)
            logger.info("notification_routed", path="focus_mode_disable", focus_mode=False)
            return ChatResponse(
                content="Focus mode off. Normal delivery resumed.",
                agent="notification",
                metadata={"focus_mode": False},
            )

    # Notification status query
    if any(w in content_lower for w in ("status", "pending", "how many", "queue")):
        pending = fatigue.pending_count
        logger.info(
            "notification_routed",
            path="status_query",
            pending_count=pending,
            focus_mode=fatigue.focus_mode,
        )
        pending_str = f"{pending} pending" if pending else "nothing queued"
        focus_str = "focus mode on" if fatigue.focus_mode else "focus mode off"
        return ChatResponse(
            content=(
                f"{pending_str.capitalize()}. DND "
                f"{fatigue.dnd_start.strftime('%H:%M')}-{fatigue.dnd_end.strftime('%H:%M')} UTC, "
                f"{focus_str}."
            ),
            agent="notification",
            metadata={"pending_count": pending, "focus_mode": fatigue.focus_mode},
        )

    # Dismiss category
    if "dismiss" in content_lower or "suppress" in content_lower or "mute" in content_lower:
        # Try to extract category from message
        categories = [cat.value for cat in NotificationCategory]
        dismissed_category = None
        for cat in categories:
            if cat in content_lower:
                dismissed_category = cat
                break

        if dismissed_category:
            await fatigue.record_dismissal(dismissed_category)
            suppressed = await fatigue.is_category_suppressed(dismissed_category)
            logger.info(
                "notification_routed",
                path="dismiss_category",
                dismissed_category=dismissed_category,
                suppressed=suppressed,
            )
            suppressed_note = (
                f" That's 3+ dismissals — {dismissed_category} notifications are now suppressed."
                if suppressed
                else ""
            )
            return ChatResponse(
                content=f"Noted the {dismissed_category} dismissal.{suppressed_note}",
                agent="notification",
                metadata={
                    "dismissed_category": dismissed_category,
                    "suppressed": suppressed,
                },
            )

    # Default: explain notification system
    logger.info("notification_routed", path="help_text")
    return ChatResponse(
        content=(
            "Notifications run on 4 priority levels. Critical ones come through immediately. "
            "Important ones are held during your DND window. Normal and low-priority get "
            "batched into morning and evening digests.\n\n"
            "You can say 'focus mode on/off', 'notification status', or "
            "'dismiss [deadline/commitment/relationship/system] notifications'."
        ),
        agent="notification",
        metadata={},
    )


# ----------------------------------------------------------------------------
# Reminder scheduling (Bug 3 fix)
# ----------------------------------------------------------------------------

_REMIND_PATTERNS = (
    "remind me",
    "reminder to",
    "reminder:",
    "set a reminder",
    "schedule a reminder",
)


def _is_reminder_request(content_lower: str) -> bool:
    """Detect 'remind me to ...' style requests before other heuristics fire."""
    return any(pattern in content_lower for pattern in _REMIND_PATTERNS)


_TIME_RE = re.compile(
    r"(?:at\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?",
    flags=re.IGNORECASE,
)


def parse_reminder_time(
    text: str,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """Parse 'tomorrow at 9am' / 'today at 17:30' / 'at 9:00' style strings.

    Returns a timezone-aware UTC datetime or None when we can't extract a time
    with reasonable confidence. Deliberately simple — no dateparser dependency.
    """
    current = now or datetime.now(UTC)
    lowered = text.lower()

    # Pick the target date.
    target_date: date = current.date()
    if "tomorrow" in lowered:
        target_date = target_date + timedelta(days=1)
    elif "today" in lowered or "tonight" in lowered:
        target_date = current.date()
    elif "in an hour" in lowered or "in 1 hour" in lowered:
        return current + timedelta(hours=1)
    elif "in 2 hours" in lowered:
        return current + timedelta(hours=2)
    elif "next monday" in lowered:
        target_date = _next_weekday(current.date(), 0)
    elif "next tuesday" in lowered:
        target_date = _next_weekday(current.date(), 1)
    elif "next wednesday" in lowered:
        target_date = _next_weekday(current.date(), 2)
    elif "next thursday" in lowered:
        target_date = _next_weekday(current.date(), 3)
    elif "next friday" in lowered:
        target_date = _next_weekday(current.date(), 4)
    elif "next saturday" in lowered:
        target_date = _next_weekday(current.date(), 5)
    elif "next sunday" in lowered:
        target_date = _next_weekday(current.date(), 6)

    match = _TIME_RE.search(lowered)
    if match is None:
        return None

    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    ampm = (match.group("ampm") or "").lower()

    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None

    result = datetime.combine(target_date, time(hour, minute), tzinfo=UTC)
    # If still in the past (e.g. "at 9am" when it's 10am today), push to tomorrow.
    if result <= current and "tomorrow" not in lowered and "next" not in lowered:
        result = result + timedelta(days=1)
    return result


def _next_weekday(from_date: date, target_weekday: int) -> date:
    """Return the next date (strictly future) that falls on target_weekday."""
    days_ahead = (target_weekday - from_date.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return from_date + timedelta(days=days_ahead)


_REMIND_CAPTURE_RE = re.compile(
    r"remind\s+me\s+(?:to\s+)?(?P<payload>.+?)(?=(?:\s+at\s+|\s+on\s+|\s+tomorrow|$))",
    flags=re.IGNORECASE,
)


def _extract_reminder_payload(text: str) -> str:
    """Pull the body of the reminder (what to do) out of the full request."""
    match = _REMIND_CAPTURE_RE.search(text)
    if match:
        payload = match.group("payload").strip(" \t\n.,:;")
        if payload:
            return payload
    # Fallback: strip known scheduling preludes and return the rest.
    stripped = re.sub(
        r"^\s*(?:tomorrow|today|tonight|next\s+\w+)(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?\s*,?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r"\s*(?:please\s+)?remind\s+me\s+(?:to\s+)?",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    return stripped.strip(" \t\n.,:;") or text.strip()


async def _try_schedule_reminder(
    *,
    message: MessageInput,
    session: AsyncSession,
    current_content: str,
) -> ChatResponse | None:
    """Parse the reminder and persist it as a scheduled_actions row.

    Returns None when we can't extract a usable time — lets the caller fall
    through to status/help text. Returns a ChatResponse otherwise.
    """
    settings = get_settings()
    run_at = parse_reminder_time(current_content)
    payload = _extract_reminder_payload(current_content)

    if run_at is None:
        # No parsable time — bounce back clearly so the user knows why nothing
        # was scheduled, instead of the old silent "Nothing queued."
        logger.info(
            "notification_reminder_time_unparseable",
            content_length=len(current_content),
        )
        return ChatResponse(
            content=(
                "I can set that reminder, but I couldn't read the time. "
                "Say something like 'tomorrow at 9am' or 'today at 5:30pm'."
            ),
            agent="notification",
            metadata={
                "error": "reminder_time_unparseable",
                "reminder_payload": payload,
            },
        )

    timezone = getattr(settings, "user_timezone", None) or "UTC"
    title = f"Reminder: {payload}"[:200] or "Reminder"
    try:
        scheduled = await create_scheduled_action(
            session,
            user_id=message.user_id,
            title=title,
            prompt=payload or current_content,
            schedule_type="once",
            schedule_config={"run_at": run_at.isoformat()},
            timezone=timezone,
            delivery_channel="telegram" if message.source == "telegram" else "web",
            metadata={"source_message": current_content[:500]},
        )
        await session.commit()
    except Exception as exc:
        logger.exception("notification_scheduled_action_failed")
        with contextlib.suppress(Exception):
            await session.rollback()
        return ChatResponse(
            content=(
                "I tried to schedule that reminder but hit a storage error. "
                f"({type(exc).__name__}). Nothing was saved — please retry."
            ),
            agent="notification",
            metadata={
                "error": "scheduled_action_persistence_failed",
                "error_class": type(exc).__name__,
            },
        )

    logger.info(
        "notification_reminder_scheduled",
        scheduled_action_id=str(scheduled.id),
        run_at=run_at.isoformat(),
    )
    return ChatResponse(
        content=(
            f"Scheduled for {run_at.strftime('%H:%M')} UTC on "
            f"{run_at.strftime('%Y-%m-%d')}: {payload}."
        ),
        agent="notification",
        metadata={
            "scheduled_action_id": str(scheduled.id),
            "run_at": run_at.isoformat(),
            "reminder_payload": payload,
        },
    )
