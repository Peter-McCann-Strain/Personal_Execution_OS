"""Tests for notification handler — preferences, focus mode, dismissals."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.app.domain.models import (
    ChatResponse,
    Intent,
    IntentType,
    MessageInput,
    Specialist,
)


def _make_message(content: str = "notification status") -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _make_intent() -> Intent:
    return Intent(
        intent_type=IntentType.COMMAND,
        confidence=0.9,
        specialist=Specialist.NOTIFICATION,
        reasoning="notification management",
    )


@pytest.fixture(autouse=True)
def _reset_fatigue_manager():
    """Reset the module-level fatigue manager between tests."""
    import src.app.domain.services.handlers.notification as notif_mod

    notif_mod._api_fatigue_manager = None
    yield
    notif_mod._api_fatigue_manager = None


@pytest.fixture(autouse=True)
def _mock_notification_runtime():
    """Provide Redis-backed notification settings for API handler tests."""
    dismissal_counts: dict[str, int] = {}

    redis = AsyncMock()
    redis.rpush = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])
    redis.delete = AsyncMock()

    async def _hincrby(_key: str, category: str, increment: int) -> int:
        dismissal_counts[category] = dismissal_counts.get(category, 0) + increment
        return dismissal_counts[category]

    async def _hget(_key: str, category: str):
        count = dismissal_counts.get(category)
        return None if count is None else str(count)

    redis.hincrby.side_effect = _hincrby
    redis.hget.side_effect = _hget

    settings = SimpleNamespace(
        notification_dnd_start_hour=22,
        notification_dnd_end_hour=7,
        redis_url=SimpleNamespace(get_secret_value=lambda: "redis://localhost:6379"),
    )

    with (
        patch("src.app.domain.services.handlers.notification.get_settings", return_value=settings),
        patch("src.app.domain.services.handlers.notification.get_redis_client", return_value=redis),
    ):
        yield


@pytest.mark.asyncio
async def test_handle_notification_enable_focus_mode():
    """handle_notification enables focus mode when requested."""
    message = _make_message("Enable focus mode please")
    intent = _make_intent()

    from src.app.domain.services.handlers.notification import handle_notification

    result = await handle_notification(message, AsyncMock(), AsyncMock(), intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "notification"
    assert "focus mode on" in result.content.lower()
    assert result.metadata["focus_mode"] is True


@pytest.mark.asyncio
async def test_handle_notification_disable_focus_mode():
    """handle_notification disables focus mode when requested."""
    # First enable, then disable
    enable_msg = _make_message("Enable focus mode")
    intent = _make_intent()

    from src.app.domain.services.handlers.notification import handle_notification

    await handle_notification(enable_msg, AsyncMock(), AsyncMock(), intent)

    disable_msg = _make_message("Disable focus mode")
    result = await handle_notification(disable_msg, AsyncMock(), AsyncMock(), intent)

    assert "focus mode off" in result.content.lower()
    assert result.metadata["focus_mode"] is False


@pytest.mark.asyncio
async def test_handle_notification_status_query():
    """handle_notification returns status information on status query."""
    message = _make_message("What is my notification status?")
    intent = _make_intent()

    from src.app.domain.services.handlers.notification import handle_notification

    result = await handle_notification(message, AsyncMock(), AsyncMock(), intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "notification"
    assert "Nothing queued." in result.content
    assert "DND 22:00-07:00 UTC" in result.content
    assert "pending_count" in result.metadata


@pytest.mark.asyncio
async def test_handle_notification_dismiss_category():
    """handle_notification records a category dismissal."""
    message = _make_message("Dismiss deadline notifications")
    intent = _make_intent()

    from src.app.domain.services.handlers.notification import handle_notification

    result = await handle_notification(message, AsyncMock(), AsyncMock(), intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "notification"
    assert "deadline" in result.content
    assert result.metadata["dismissed_category"] == "deadline"


@pytest.mark.asyncio
async def test_handle_notification_dismiss_category_suppressed():
    """handle_notification reports suppression after 3+ dismissals."""
    intent = _make_intent()

    from src.app.domain.services.handlers.notification import handle_notification

    # Dismiss 3 times to trigger suppression
    for _ in range(3):
        msg = _make_message("Dismiss deadline notifications")
        result = await handle_notification(msg, AsyncMock(), AsyncMock(), intent)

    assert "suppressed" in result.content.lower()
    assert result.metadata["suppressed"] is True


@pytest.mark.asyncio
async def test_handle_notification_dismiss_unknown_category():
    """handle_notification falls through to default when category not found."""
    message = _make_message("Dismiss something unknown")
    intent = _make_intent()

    from src.app.domain.services.handlers.notification import handle_notification

    result = await handle_notification(message, AsyncMock(), AsyncMock(), intent)

    # "dismiss" is in the message but no recognized category, so falls through
    # to the default explanation since dismissed_category is None
    assert result.agent == "notification"
    assert "Notifications run on 4 priority levels" in result.content


@pytest.mark.asyncio
async def test_handle_notification_default_explanation():
    """handle_notification returns explanation when no specific command matches."""
    message = _make_message("Tell me about notifications")
    intent = _make_intent()

    from src.app.domain.services.handlers.notification import handle_notification

    result = await handle_notification(message, AsyncMock(), AsyncMock(), intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "notification"
    assert "Notifications run on 4 priority levels" in result.content
    assert "Critical ones come through immediately" in result.content
    assert "focus mode on/off" in result.content


@pytest.mark.asyncio
async def test_handle_notification_pending_query():
    """handle_notification shows pending count via 'how many' keyword."""
    message = _make_message("How many notifications are pending?")
    intent = _make_intent()

    from src.app.domain.services.handlers.notification import handle_notification

    result = await handle_notification(message, AsyncMock(), AsyncMock(), intent)

    assert "Nothing queued." in result.content
    assert result.metadata["pending_count"] == 0


@pytest.mark.asyncio
async def test_handle_notification_enqueue_failure_is_swallowed():
    """Entity extraction failures should not block the notification response."""
    message = _make_message("Tell me about notifications")
    intent = _make_intent()

    from src.app.domain.services.handlers import notification as notif_mod

    notif_mod._api_fatigue_manager = None

    with patch(
        "src.app.domain.services.handlers.notification.enqueue_entity_extraction",
        new_callable=AsyncMock,
        side_effect=RuntimeError("queue down"),
    ):
        from src.app.domain.services.handlers.notification import handle_notification

        result = await handle_notification(message, AsyncMock(), AsyncMock(), intent)

    assert result.agent == "notification"
    assert "Notifications run on 4 priority levels" in result.content


def test_get_or_create_fatigue_manager_reuses_existing_instance():
    """The module-level fatigue manager should be reused once created."""
    from src.app.domain.services.handlers.notification import _get_or_create_fatigue_manager

    first = _get_or_create_fatigue_manager()
    second = _get_or_create_fatigue_manager()

    assert first is second


# ------------------------------------------------------------------
# Bug 3 regression: reminder scheduling
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_notification_reminder_schedules_action():
    """Bug 3 regression: 'Tomorrow at 9am, remind me to send the weekly status
    to the team.' must create a scheduled_actions row (not silently fall
    through to the status/help text).
    """
    import uuid as _uuid

    from src.app.domain.services.handlers.notification import handle_notification

    message = _make_message("Tomorrow at 9am, remind me to send the weekly status to the team.")
    intent = _make_intent()
    mock_session = AsyncMock()
    scheduled = SimpleNamespace(id=_uuid.uuid4())

    with patch(
        "src.app.domain.services.handlers.notification.create_scheduled_action",
        new_callable=AsyncMock,
        return_value=scheduled,
    ) as mock_create:
        result = await handle_notification(message, AsyncMock(), mock_session, intent)

    assert result.agent == "notification"
    assert "scheduled for" in result.content.lower()
    assert result.metadata["scheduled_action_id"] == str(scheduled.id)
    assert "weekly status" in result.metadata["reminder_payload"].lower()
    mock_create.assert_awaited_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["schedule_type"] == "once"
    assert "run_at" in call_kwargs["schedule_config"]
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_notification_reminder_unparseable_time_returns_clarification():
    """If we can't read the time, the handler must ask for clarification —
    NOT silently return 'Nothing queued.'"""
    from src.app.domain.services.handlers.notification import handle_notification

    message = _make_message("Remind me to call my mum sometime soon")
    intent = _make_intent()
    mock_session = AsyncMock()

    with patch(
        "src.app.domain.services.handlers.notification.create_scheduled_action",
        new_callable=AsyncMock,
    ) as mock_create:
        result = await handle_notification(message, AsyncMock(), mock_session, intent)

    assert result.agent == "notification"
    assert result.metadata.get("error") == "reminder_time_unparseable"
    # Must NOT be the old "nothing queued" status response
    assert "Nothing queued" not in result.content
    mock_create.assert_not_awaited()


def test_parse_reminder_time_handles_tomorrow_at_9am():
    """The time parser must turn 'tomorrow at 9am' into a UTC datetime."""
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from src.app.domain.services.handlers.notification import parse_reminder_time

    now = _dt(2026, 4, 18, 15, 0, tzinfo=_UTC)
    parsed = parse_reminder_time(
        "Tomorrow at 9am, remind me to send the weekly status.",
        now=now,
    )
    assert parsed is not None
    assert parsed.year == 2026
    assert parsed.month == 4
    assert parsed.day == 19
    assert parsed.hour == 9
    assert parsed.minute == 0


def test_parse_reminder_time_returns_none_when_no_time_phrase():
    """No time phrase -> None so the handler can ask for clarification."""
    from src.app.domain.services.handlers.notification import parse_reminder_time

    assert parse_reminder_time("remind me to call my mum sometime") is None


@pytest.mark.asyncio
async def test_handle_notification_weekly_status_keyword_does_not_trigger_status_branch():
    """Bug 3 regression: a reminder body that contains 'status' must still
    route to the reminder/scheduling branch, not the status-query branch.
    """
    from src.app.domain.services.handlers.notification import handle_notification

    message = _make_message("Tomorrow at 9am remind me to send the weekly status to the team.")
    intent = _make_intent()
    mock_session = AsyncMock()

    with patch(
        "src.app.domain.services.handlers.notification.create_scheduled_action",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(id="deadbeef"),
    ):
        result = await handle_notification(message, AsyncMock(), mock_session, intent)

    # If we had hit the status branch we'd see "Nothing queued. DND ...".
    assert "Nothing queued" not in result.content
    assert "scheduled" in result.content.lower()
