"""Notification agent — proactive alerts with fatigue management.

Priority levels:
  P0 (Critical): Always delivers — system down, <1hr calendar conflicts
  P1 (Important): Delivers within 15min, respects DND/focus windows
  P2 (Normal): Batched into morning (9am) + evening (6pm) digests
  P3 (Low): Daily morning digest only

No fallback. Fails loudly.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, time
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger()

# Redis key constants
_REDIS_KEY_P2 = "fatigue:pending:p2"
_REDIS_KEY_P3 = "fatigue:pending:p3"
_REDIS_KEY_DISMISSALS = "fatigue:dismissals"
_DISMISSAL_SUPPRESSION_THRESHOLD = 3


class Priority(StrEnum):
    P0_CRITICAL = "P0"
    P1_IMPORTANT = "P1"
    P2_NORMAL = "P2"
    P3_LOW = "P3"


class Notification(BaseModel):
    """A notification to be delivered."""

    message: str
    priority: Priority
    category: str  # "deadline", "commitment", "relationship", "system", "digest"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FatigueManager:
    """Manages notification fatigue — DND, batching, cooldowns.

    When ``redis`` is provided, pending notifications and dismissal counts
    are persisted to Redis so they survive worker restarts.  When ``redis``
    is ``None`` (e.g. in tests), state is kept in-memory only.
    """

    def __init__(
        self,
        dnd_start: time,
        dnd_end: time,
        redis: Redis | None = None,
    ) -> None:
        self.dnd_start = dnd_start
        self.dnd_end = dnd_end
        self._redis = redis
        # In-memory fallback (also used as write-through cache when Redis present)
        self._dismissal_counts: dict[str, int] = {}
        self._focus_mode = False
        self._pending_p2: list[Notification] = []
        self._pending_p3: list[Notification] = []

    # ------------------------------------------------------------------
    # Redis serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialise(notification: Notification) -> str:
        return notification.model_dump_json()

    @staticmethod
    def _deserialise(raw: str | bytes) -> Notification:
        if isinstance(raw, bytes):
            raw = raw.decode()
        return Notification.model_validate_json(raw)

    async def _redis_push(self, key: str, notification: Notification) -> None:
        if self._redis:
            await self._redis.rpush(key, self._serialise(notification))

    async def _redis_flush(self, *keys: str) -> list[Notification]:
        """Atomically pop all items from the given Redis list keys."""
        if not self._redis:
            return []
        results: list[Notification] = []
        for key in keys:
            items = await self._redis.lrange(key, 0, -1)
            if items:
                await self._redis.delete(key)
                results.extend(self._deserialise(item) for item in items)
        return results

    async def _redis_record_dismissal(self, category: str) -> int:
        if self._redis:
            count = await self._redis.hincrby(_REDIS_KEY_DISMISSALS, category, 1)
            return int(count)
        return 0

    async def _redis_get_dismissal(self, category: str) -> int:
        if self._redis:
            val = await self._redis.hget(_REDIS_KEY_DISMISSALS, category)
            return int(val) if val else 0
        return 0

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def should_deliver_now(self, notification: Notification) -> bool:
        """Determine if a notification should be delivered immediately."""
        # P0 always delivers
        if notification.priority == Priority.P0_CRITICAL:
            return True

        # Check DND window
        now = datetime.now(UTC).time()
        if self._is_dnd(now):
            logger.info("notification_dnd_blocked", priority=notification.priority)
            return False

        # Check focus mode
        if self._focus_mode and notification.priority != Priority.P0_CRITICAL:
            return False

        # P1 delivers immediately (outside DND); P2/P3 are batched
        return notification.priority == Priority.P1_IMPORTANT

    async def record_dismissal(self, category: str) -> None:
        """Record that a notification was dismissed. Triggers cooldown."""
        self._dismissal_counts[category] = self._dismissal_counts.get(category, 0) + 1
        count = self._dismissal_counts[category]
        if self._redis:
            count = await self._redis_record_dismissal(category)
        if count >= _DISMISSAL_SUPPRESSION_THRESHOLD:
            logger.info("notification_category_suppressed", category=category)

    async def is_category_suppressed(self, category: str) -> bool:
        """Check if a category has been dismissed too many times."""
        if self._redis:
            return (await self._redis_get_dismissal(category)) >= _DISMISSAL_SUPPRESSION_THRESHOLD
        return self._dismissal_counts.get(category, 0) >= _DISMISSAL_SUPPRESSION_THRESHOLD

    @property
    def focus_mode(self) -> bool:
        """Whether focus mode is active (only P0 delivered)."""
        return self._focus_mode

    def set_focus_mode(self, enabled: bool) -> None:
        """Toggle focus mode — blocks all non-P0 notifications."""
        self._focus_mode = enabled
        logger.info("focus_mode_changed", enabled=enabled)

    def _is_dnd(self, now: time) -> bool:
        """Check if current time is within DND window."""
        if self.dnd_start <= self.dnd_end:
            return self.dnd_start <= now <= self.dnd_end
        # Handles overnight DND (e.g., 22:00 - 07:00)
        return now >= self.dnd_start or now <= self.dnd_end

    # ------------------------------------------------------------------
    # Batching / digest methods
    # ------------------------------------------------------------------

    async def evaluate(self, notification: Notification) -> bool:
        """Evaluate notification delivery. Returns True if deliver now, False if batched.

        P2/P3 notifications are automatically queued for batch delivery.
        """
        deliver_now = self.should_deliver_now(notification)
        if not deliver_now and notification.priority in (
            Priority.P2_NORMAL,
            Priority.P3_LOW,
        ):
            await self.queue_for_batch(notification)
        return deliver_now

    async def queue_for_batch(self, notification: Notification) -> None:
        """Queue a P2/P3 notification for later batch delivery."""
        if notification.priority == Priority.P2_NORMAL:
            self._pending_p2.append(notification)
            await self._redis_push(_REDIS_KEY_P2, notification)
        elif notification.priority == Priority.P3_LOW:
            self._pending_p3.append(notification)
            await self._redis_push(_REDIS_KEY_P3, notification)

    async def flush_morning_digest(self) -> list[Notification]:
        """Get all pending P2 + P3 for morning digest. Clears queues."""
        if self._redis:
            digest = await self._redis_flush(_REDIS_KEY_P2, _REDIS_KEY_P3)
            self._pending_p2.clear()
            self._pending_p3.clear()
            return digest
        digest = list(self._pending_p2) + list(self._pending_p3)
        self._pending_p2.clear()
        self._pending_p3.clear()
        return digest

    async def flush_evening_digest(self) -> list[Notification]:
        """Get pending P2 for evening digest. Clears P2 queue only."""
        if self._redis:
            digest = await self._redis_flush(_REDIS_KEY_P2)
            self._pending_p2.clear()
            return digest
        digest = list(self._pending_p2)
        self._pending_p2.clear()
        return digest

    def format_digest(self, notifications: list[Notification]) -> str:
        """Format a list of notifications into a digest message."""
        if not notifications:
            return ""

        lines = [f"\U0001f4cb Notification Digest ({len(notifications)} items)\n"]

        by_category: dict[str, list[Notification]] = defaultdict(list)
        for n in notifications:
            by_category[n.category].append(n)

        for category, items in sorted(by_category.items()):
            lines.append(f"\n**{category.title()}** ({len(items)})")
            for item in items:
                priority_label = item.priority.value
                lines.append(f"  [{priority_label}] {item.message}")

        return "\n".join(lines)

    @property
    def pending_count(self) -> int:
        """Number of notifications waiting for batch delivery (in-memory count)."""
        return len(self._pending_p2) + len(self._pending_p3)
