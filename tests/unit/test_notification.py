"""Tests for notification fatigue management."""

from datetime import UTC, datetime, time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.specialists.notification import (
    FatigueManager,
    Notification,
    Priority,
)


def _make_manager() -> FatigueManager:
    return FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))


def _make_notification(priority: Priority, category: str = "test") -> Notification:
    return Notification(message="test", priority=priority, category=category)


def test_p0_always_delivers():
    """P0 Critical should always deliver, even in DND."""
    mgr = _make_manager()
    n = _make_notification(Priority.P0_CRITICAL)
    assert mgr.should_deliver_now(n) is True


def test_p1_delivers_outside_dnd():
    """P1 Important should deliver outside DND."""
    mgr = _make_manager()
    n = _make_notification(Priority.P1_IMPORTANT)
    # Mock to daytime so this test works regardless of when it runs
    fake_now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
    with patch("src.app.agents.specialists.notification.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        assert mgr.should_deliver_now(n) is True


def test_p2_is_batched():
    """P2 Normal should NOT deliver immediately (batched)."""
    mgr = _make_manager()
    n = _make_notification(Priority.P2_NORMAL)
    assert mgr.should_deliver_now(n) is False


def test_p3_is_batched():
    """P3 Low should NOT deliver immediately."""
    mgr = _make_manager()
    n = _make_notification(Priority.P3_LOW)
    assert mgr.should_deliver_now(n) is False


def test_focus_mode_blocks_non_p0():
    """Focus mode should block everything except P0."""
    mgr = _make_manager()
    mgr.set_focus_mode(True)

    assert mgr.should_deliver_now(_make_notification(Priority.P0_CRITICAL)) is True
    assert mgr.should_deliver_now(_make_notification(Priority.P1_IMPORTANT)) is False
    assert mgr.should_deliver_now(_make_notification(Priority.P2_NORMAL)) is False


@pytest.mark.asyncio
async def test_dismissal_cooldown():
    """3 dismissals should suppress a category."""
    mgr = _make_manager()
    assert await mgr.is_category_suppressed("digest") is False

    await mgr.record_dismissal("digest")
    await mgr.record_dismissal("digest")
    assert await mgr.is_category_suppressed("digest") is False

    await mgr.record_dismissal("digest")
    assert await mgr.is_category_suppressed("digest") is True


@pytest.mark.asyncio
async def test_dismissal_per_category():
    """Dismissal counts should be per-category."""
    mgr = _make_manager()
    await mgr.record_dismissal("deadline")
    await mgr.record_dismissal("deadline")
    await mgr.record_dismissal("deadline")

    assert await mgr.is_category_suppressed("deadline") is True
    assert await mgr.is_category_suppressed("relationship") is False


# ------------------------------------------------------------------
# Batching / digest tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2_queued_for_batch():
    """P2 notification not delivered immediately, but added to pending queue."""
    mgr = _make_manager()
    n = _make_notification(Priority.P2_NORMAL)
    await mgr.queue_for_batch(n)

    assert mgr.pending_count == 1
    assert mgr._pending_p2 == [n]
    assert mgr._pending_p3 == []


@pytest.mark.asyncio
async def test_p3_queued_for_batch():
    """P3 notification not delivered immediately, but added to pending queue."""
    mgr = _make_manager()
    n = _make_notification(Priority.P3_LOW)
    await mgr.queue_for_batch(n)

    assert mgr.pending_count == 1
    assert mgr._pending_p3 == [n]
    assert mgr._pending_p2 == []


@pytest.mark.asyncio
async def test_morning_digest_flushes_all():
    """Morning digest returns P2 + P3, clears both queues."""
    mgr = _make_manager()
    p2 = _make_notification(Priority.P2_NORMAL, category="deadline")
    p3 = _make_notification(Priority.P3_LOW, category="digest")
    await mgr.queue_for_batch(p2)
    await mgr.queue_for_batch(p3)

    digest = await mgr.flush_morning_digest()

    assert len(digest) == 2
    assert p2 in digest
    assert p3 in digest
    assert mgr.pending_count == 0


@pytest.mark.asyncio
async def test_evening_digest_flushes_p2_only():
    """Evening digest returns only P2; P3 remains in queue."""
    mgr = _make_manager()
    p2 = _make_notification(Priority.P2_NORMAL, category="deadline")
    p3 = _make_notification(Priority.P3_LOW, category="digest")
    await mgr.queue_for_batch(p2)
    await mgr.queue_for_batch(p3)

    digest = await mgr.flush_evening_digest()

    assert digest == [p2]
    # P3 still pending for morning digest
    assert mgr.pending_count == 1
    assert mgr._pending_p3 == [p3]


def test_format_digest_groups_by_category():
    """Digest formatted with category groupings."""
    mgr = _make_manager()
    notifications = [
        Notification(message="deadline A", priority=Priority.P2_NORMAL, category="deadline"),
        Notification(message="deadline B", priority=Priority.P2_NORMAL, category="deadline"),
        Notification(message="system update", priority=Priority.P3_LOW, category="system"),
    ]

    result = mgr.format_digest(notifications)

    assert "Notification Digest (3 items)" in result
    assert "**Deadline** (2)" in result
    assert "**System** (1)" in result
    assert "[P2] deadline A" in result
    assert "[P2] deadline B" in result
    assert "[P3] system update" in result


def test_format_digest_empty():
    """Empty notification list produces empty string."""
    mgr = _make_manager()
    assert mgr.format_digest([]) == ""


@pytest.mark.asyncio
async def test_pending_count():
    """pending_count reflects total queued items across both lists."""
    mgr = _make_manager()
    assert mgr.pending_count == 0

    await mgr.queue_for_batch(_make_notification(Priority.P2_NORMAL))
    assert mgr.pending_count == 1

    await mgr.queue_for_batch(_make_notification(Priority.P3_LOW))
    assert mgr.pending_count == 2

    await mgr.queue_for_batch(_make_notification(Priority.P2_NORMAL))
    assert mgr.pending_count == 3


@pytest.mark.asyncio
async def test_evaluate_queues_p2():
    """evaluate() returns False for P2 and auto-queues it."""
    mgr = _make_manager()
    n = _make_notification(Priority.P2_NORMAL)

    result = await mgr.evaluate(n)

    assert result is False
    assert mgr.pending_count == 1
    assert mgr._pending_p2 == [n]


@pytest.mark.asyncio
async def test_evaluate_queues_p3():
    """evaluate() returns False for P3 and auto-queues it."""
    mgr = _make_manager()
    n = _make_notification(Priority.P3_LOW)

    result = await mgr.evaluate(n)

    assert result is False
    assert mgr.pending_count == 1
    assert mgr._pending_p3 == [n]


@pytest.mark.asyncio
async def test_evaluate_p0_not_queued():
    """evaluate() returns True for P0 and does not queue it."""
    mgr = _make_manager()
    n = _make_notification(Priority.P0_CRITICAL)

    result = await mgr.evaluate(n)

    assert result is True
    assert mgr.pending_count == 0


@pytest.mark.asyncio
async def test_evaluate_p1_not_queued():
    """evaluate() returns True for P1 (outside DND) and does not queue it."""
    mgr = _make_manager()
    n = _make_notification(Priority.P1_IMPORTANT)
    fake_now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
    with patch("src.app.agents.specialists.notification.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        result = await mgr.evaluate(n)

    assert result is True
    assert mgr.pending_count == 0


# ------------------------------------------------------------------
# DND window edge cases
# ------------------------------------------------------------------


def test_dnd_overnight_window_before_midnight():
    """Time before midnight should be within a 22:00-07:00 DND window."""
    mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))
    assert mgr._is_dnd(time(23, 30)) is True


def test_dnd_overnight_window_after_midnight():
    """Time after midnight should be within a 22:00-07:00 DND window."""
    mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))
    assert mgr._is_dnd(time(3, 0)) is True


def test_dnd_overnight_window_outside():
    """Time during the day should be outside a 22:00-07:00 DND window."""
    mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))
    assert mgr._is_dnd(time(14, 0)) is False


def test_dnd_daytime_window():
    """A daytime DND window (start < end) should also work."""
    mgr = FatigueManager(dnd_start=time(12, 0), dnd_end=time(13, 0))
    assert mgr._is_dnd(time(12, 30)) is True
    assert mgr._is_dnd(time(11, 0)) is False
    assert mgr._is_dnd(time(14, 0)) is False


def test_p1_blocked_during_dnd():
    """P1 Important should NOT deliver during DND."""
    mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))
    n = _make_notification(Priority.P1_IMPORTANT)
    fake_now = datetime(2026, 3, 10, 23, 30, 0, tzinfo=UTC)
    with patch("src.app.agents.specialists.notification.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        result = mgr.should_deliver_now(n)
    assert result is False


def test_p0_delivers_during_dnd():
    """P0 Critical should deliver even during DND."""
    mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))
    n = _make_notification(Priority.P0_CRITICAL)
    assert mgr.should_deliver_now(n) is True


# ------------------------------------------------------------------
# Focus mode edge cases
# ------------------------------------------------------------------


def test_focus_mode_toggle():
    """Focus mode can be toggled on and off."""
    mgr = _make_manager()
    assert mgr.focus_mode is False

    mgr.set_focus_mode(True)
    assert mgr.focus_mode is True

    mgr.set_focus_mode(False)
    assert mgr.focus_mode is False


def test_focus_mode_off_allows_p1():
    """After disabling focus mode, P1 should deliver again."""
    mgr = _make_manager()
    fake_now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
    with patch("src.app.agents.specialists.notification.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        mgr.set_focus_mode(True)
        assert mgr.should_deliver_now(_make_notification(Priority.P1_IMPORTANT)) is False

        mgr.set_focus_mode(False)
        assert mgr.should_deliver_now(_make_notification(Priority.P1_IMPORTANT)) is True


# ------------------------------------------------------------------
# Digest edge cases
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_morning_digest_when_empty():
    """Flushing an empty digest should return an empty list."""
    mgr = _make_manager()
    digest = await mgr.flush_morning_digest()
    assert digest == []
    assert mgr.pending_count == 0


@pytest.mark.asyncio
async def test_flush_evening_digest_when_empty():
    """Flushing an empty evening digest should return an empty list."""
    mgr = _make_manager()
    digest = await mgr.flush_evening_digest()
    assert digest == []


@pytest.mark.asyncio
async def test_double_flush_returns_empty():
    """Flushing twice should return items only on the first flush."""
    mgr = _make_manager()
    await mgr.queue_for_batch(_make_notification(Priority.P2_NORMAL))

    first = await mgr.flush_morning_digest()
    assert len(first) == 1

    second = await mgr.flush_morning_digest()
    assert second == []


@pytest.mark.asyncio
async def test_queue_p1_is_ignored():
    """P1 notifications should not be queued for batch (they deliver immediately)."""
    mgr = _make_manager()
    n = _make_notification(Priority.P1_IMPORTANT)
    await mgr.queue_for_batch(n)
    assert mgr.pending_count == 0


def test_format_digest_single_item():
    """Single-item digest should format correctly."""
    mgr = _make_manager()
    notifications = [
        Notification(
            message="Remember to call back",
            priority=Priority.P2_NORMAL,
            category="reminder",
        ),
    ]
    result = mgr.format_digest(notifications)
    assert "Notification Digest (1 items)" in result
    assert "**Reminder** (1)" in result
    assert "[P2] Remember to call back" in result


def test_notification_serialisation_roundtrip():
    """Notification should serialise and deserialise via JSON correctly."""
    n = Notification(
        message="Test message",
        priority=Priority.P2_NORMAL,
        category="test",
    )
    raw = FatigueManager._serialise(n)
    restored = FatigueManager._deserialise(raw)

    assert restored.message == n.message
    assert restored.priority == n.priority
    assert restored.category == n.category


def test_notification_deserialise_from_bytes():
    """Deserialisation should handle bytes (as Redis returns)."""
    n = Notification(
        message="Bytes test",
        priority=Priority.P3_LOW,
        category="system",
    )
    raw_bytes = FatigueManager._serialise(n).encode("utf-8")
    restored = FatigueManager._deserialise(raw_bytes)

    assert restored.message == "Bytes test"
    assert restored.priority == Priority.P3_LOW


# ------------------------------------------------------------------
# Redis-backed FatigueManager tests
# ------------------------------------------------------------------


def _make_mock_redis():
    """Create a mock Redis client for testing Redis-backed FatigueManager."""
    from unittest.mock import AsyncMock

    redis = AsyncMock()
    redis.rpush = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])
    redis.delete = AsyncMock()
    redis.hincrby = AsyncMock(return_value=1)
    redis.hget = AsyncMock(return_value=None)
    return redis


def _make_sync_mock_redis():
    """Model redis-py's declared sync-or-async response contract."""
    redis = MagicMock()
    redis.rpush.return_value = 1
    redis.lrange.return_value = []
    redis.delete.return_value = 1
    redis.hincrby.return_value = 3
    redis.hget.return_value = b"3"
    return redis


def _make_redis_manager():
    """Create a FatigueManager with a mock Redis client."""
    redis = _make_mock_redis()
    return FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0), redis=redis), redis


@pytest.mark.asyncio
async def test_redis_declared_sync_responses_are_normalised() -> None:
    """Redis annotations permit immediate values; the manager handles both forms."""
    redis = _make_sync_mock_redis()
    mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0), redis=redis)

    await mgr.queue_for_batch(_make_notification(Priority.P2_NORMAL))
    await mgr.record_dismissal("deadline")

    assert await mgr.is_category_suppressed("deadline") is True
    redis.rpush.assert_called_once()
    redis.hincrby.assert_called_once()


@pytest.mark.asyncio
async def test_redis_push_on_queue():
    """When Redis is present, queue_for_batch should rpush to Redis."""
    mgr, redis = _make_redis_manager()
    n = _make_notification(Priority.P2_NORMAL)

    await mgr.queue_for_batch(n)

    redis.rpush.assert_awaited_once()
    call_args = redis.rpush.call_args
    assert call_args[0][0] == "fatigue:pending:p2"


@pytest.mark.asyncio
async def test_redis_push_p3():
    """P3 notifications should be pushed to the P3 Redis key."""
    mgr, redis = _make_redis_manager()
    n = _make_notification(Priority.P3_LOW)

    await mgr.queue_for_batch(n)

    redis.rpush.assert_awaited_once()
    call_args = redis.rpush.call_args
    assert call_args[0][0] == "fatigue:pending:p3"


@pytest.mark.asyncio
async def test_redis_flush_morning_digest():
    """With Redis, flush_morning_digest should pop from Redis lists."""
    mgr, redis = _make_redis_manager()
    n1 = _make_notification(Priority.P2_NORMAL, category="deadline")
    n2 = _make_notification(Priority.P3_LOW, category="digest")

    # Simulate Redis having items
    serialised_n1 = FatigueManager._serialise(n1).encode()
    serialised_n2 = FatigueManager._serialise(n2).encode()

    redis.lrange = AsyncMock(
        side_effect=[
            [serialised_n1],  # P2 key
            [serialised_n2],  # P3 key
        ]
    )

    digest = await mgr.flush_morning_digest()

    assert len(digest) == 2
    assert digest[0].category == "deadline"
    assert digest[1].category == "digest"
    assert redis.delete.await_count == 2
    assert mgr.pending_count == 0


@pytest.mark.asyncio
async def test_redis_flush_evening_digest():
    """With Redis, flush_evening_digest should pop only P2 from Redis."""
    mgr, redis = _make_redis_manager()
    n1 = _make_notification(Priority.P2_NORMAL, category="deadline")

    serialised_n1 = FatigueManager._serialise(n1).encode()

    redis.lrange = AsyncMock(return_value=[serialised_n1])

    digest = await mgr.flush_evening_digest()

    assert len(digest) == 1
    assert digest[0].category == "deadline"
    redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_flush_empty():
    """With Redis but no items, flush should return empty."""
    mgr, redis = _make_redis_manager()

    redis.lrange = AsyncMock(return_value=[])

    digest = await mgr.flush_morning_digest()
    assert digest == []


@pytest.mark.asyncio
async def test_redis_record_dismissal():
    """record_dismissal with Redis should call hincrby."""
    mgr, redis = _make_redis_manager()
    redis.hincrby = AsyncMock(return_value=1)

    await mgr.record_dismissal("deadline")

    redis.hincrby.assert_awaited_once_with("fatigue:dismissals", "deadline", 1)
    assert mgr._dismissal_counts["deadline"] == 1


@pytest.mark.asyncio
async def test_redis_record_dismissal_triggers_suppression():
    """3 Redis dismissals should log suppression."""
    mgr, redis = _make_redis_manager()
    redis.hincrby = AsyncMock(return_value=3)

    await mgr.record_dismissal("digest")

    # In-memory count should be 1, but Redis count is 3
    assert mgr._dismissal_counts["digest"] == 1


@pytest.mark.asyncio
async def test_redis_is_category_suppressed():
    """is_category_suppressed with Redis should query hget."""
    mgr, redis = _make_redis_manager()

    # Not suppressed
    redis.hget = AsyncMock(return_value=None)
    assert await mgr.is_category_suppressed("deadline") is False

    # Suppressed (3+ dismissals)
    redis.hget = AsyncMock(return_value="3")
    assert await mgr.is_category_suppressed("deadline") is True

    redis.hget = AsyncMock(return_value="5")
    assert await mgr.is_category_suppressed("deadline") is True


@pytest.mark.asyncio
async def test_redis_get_dismissal_returns_zero_when_no_value():
    """_redis_get_dismissal should return 0 when Redis has no value."""
    mgr, redis = _make_redis_manager()
    redis.hget = AsyncMock(return_value=None)

    result = await mgr._redis_get_dismissal("nonexistent")
    assert result == 0


@pytest.mark.asyncio
async def test_redis_record_dismissal_returns_count():
    """_redis_record_dismissal should return the new count."""
    mgr, redis = _make_redis_manager()
    redis.hincrby = AsyncMock(return_value=2)

    count = await mgr._redis_record_dismissal("test_cat")
    assert count == 2


@pytest.mark.asyncio
async def test_no_redis_redis_push_is_noop():
    """_redis_push without Redis should be a no-op."""
    mgr = _make_manager()  # No Redis
    n = _make_notification(Priority.P2_NORMAL)
    # Should not raise
    await mgr._redis_push("some_key", n)


@pytest.mark.asyncio
async def test_no_redis_redis_flush_returns_empty():
    """_redis_flush without Redis should return empty list."""
    mgr = _make_manager()
    result = await mgr._redis_flush("key1", "key2")
    assert result == []


@pytest.mark.asyncio
async def test_no_redis_redis_record_dismissal_returns_zero():
    """_redis_record_dismissal without Redis should return 0."""
    mgr = _make_manager()
    result = await mgr._redis_record_dismissal("cat")
    assert result == 0


@pytest.mark.asyncio
async def test_no_redis_redis_get_dismissal_returns_zero():
    """_redis_get_dismissal without Redis should return 0."""
    mgr = _make_manager()
    result = await mgr._redis_get_dismissal("cat")
    assert result == 0


# ------------------------------------------------------------------
# Time-dependent tests with mocked datetime
# ------------------------------------------------------------------


def test_p1_delivers_during_daytime_mocked():
    """P1 should deliver when time is mocked to daytime (12:00 UTC)."""
    mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))
    n = _make_notification(Priority.P1_IMPORTANT)
    fake_now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
    with patch("src.app.agents.specialists.notification.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        result = mgr.should_deliver_now(n)
    assert result is True


def test_p2_batched_during_daytime_mocked():
    """P2 should be batched even during daytime."""
    mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))
    n = _make_notification(Priority.P2_NORMAL)
    fake_now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
    with patch("src.app.agents.specialists.notification.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        result = mgr.should_deliver_now(n)
    assert result is False


def test_focus_mode_blocks_p1_during_daytime_mocked():
    """Focus mode should block P1 even during daytime."""
    mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))
    mgr.set_focus_mode(True)
    n = _make_notification(Priority.P1_IMPORTANT)
    fake_now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
    with patch("src.app.agents.specialists.notification.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        result = mgr.should_deliver_now(n)
    assert result is False


@pytest.mark.asyncio
async def test_evaluate_during_dnd_queues_p2():
    """During DND, P2 should be queued not delivered."""
    mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))
    n = _make_notification(Priority.P2_NORMAL)
    fake_now = datetime(2026, 3, 10, 23, 0, 0, tzinfo=UTC)
    with patch("src.app.agents.specialists.notification.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        result = await mgr.evaluate(n)
    assert result is False
    assert mgr.pending_count == 1
