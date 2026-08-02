"""Conversation context — multi-turn memory via Redis with rolling summaries.

Implements two tiers of conversation memory:

1. **Raw messages** — the last N verbatim messages (from config).
   High fidelity, short window.
2. **Rolling summary** — an LLM-generated compression of older messages that
   updates as conversation grows.  Preserves context that raw truncation
   would destroy.

Both tiers are stored in Redis with a sliding TTL (from config).
All errors propagate — Redis failures are real failures, not silent degradation.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

import structlog

from src.app.config import get_settings
from src.app.domain.models import (
    PendingConversationAction,
    PendingPlanningSession,
    PendingToolPlan,
    SessionStatePacket,
)

logger = structlog.get_logger()

_KEY_PREFIX = "conv:"
_SUMMARY_KEY_PREFIX = "conv_summary:"
_STATE_PACKET_KEY_PREFIX = "conv_state:"
_PENDING_TOOL_PLAN_KEY_PREFIX = "conv_pending_tools:"
_PENDING_PLANNING_SESSION_KEY_PREFIX = "conv_pending_planning:"
_PENDING_CONVERSATION_ACTION_KEY_PREFIX = "conv_pending_action:"


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


async def _await_redis_command(value: object, *, operation: str) -> None:
    """Require the async Redis contract instead of accepting a sync client silently."""
    if not isinstance(value, Awaitable):
        raise TypeError(f"Redis {operation} returned a non-awaitable result")
    await value


async def _await_redis_messages(value: object) -> list[str | bytes]:
    """Validate the asynchronous LRANGE result before JSON deserialization."""
    if not isinstance(value, Awaitable):
        raise TypeError("Redis LRANGE returned a non-awaitable result")
    raw_messages = await value
    if not isinstance(raw_messages, list):
        raise TypeError("Redis LRANGE returned a non-list result")

    messages: list[str | bytes] = []
    for raw_message in raw_messages:
        if not isinstance(raw_message, (str, bytes)):
            raise TypeError("Redis LRANGE returned a non-text message")
        messages.append(raw_message)
    return messages


@dataclass(slots=True)
class ConversationMessage:
    """A single message within a conversation session."""

    role: str
    content: str
    agent: str = ""
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> ConversationMessage:
        return cls(
            role=data["role"],
            content=data["content"],
            agent=data.get("agent", ""),
            timestamp=data.get("timestamp") or _now_iso(),
        )


class ConversationContext:
    """Redis-backed conversation context with rolling summary support.

    All configuration (TTL, max messages) comes from Settings.
    All errors propagate — no silent degradation.
    """

    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url

    # ------------------------------------------------------------------
    # Raw messages
    # ------------------------------------------------------------------

    async def add_message(
        self,
        user_id: str,
        role: str,
        content: str,
        agent: str = "",
    ) -> None:
        """Add a message to the conversation context.

        Raises on Redis failure.
        """
        from src.app.core.redis import redis_pool

        settings = get_settings()
        msg = ConversationMessage(role=role, content=content, agent=agent)
        key = f"{_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            await _await_redis_command(
                conn.rpush(key, json.dumps(msg.to_dict())),
                operation="RPUSH",
            )
            await _await_redis_command(
                conn.ltrim(key, -settings.max_context_messages, -1),
                operation="LTRIM",
            )
            await conn.expire(key, settings.session_ttl)

    async def get_context(self, user_id: str) -> list[ConversationMessage]:
        """Get the conversation context for a user.

        Raises on Redis failure.
        """
        from src.app.core.redis import redis_pool

        key = f"{_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            raw_messages = await _await_redis_messages(conn.lrange(key, 0, -1))
            return [ConversationMessage.from_dict(json.loads(m)) for m in raw_messages]

    # ------------------------------------------------------------------
    # Rolling summary
    # ------------------------------------------------------------------

    async def get_summary(self, user_id: str) -> str:
        """Get the rolling session summary for a user.

        Returns empty string if no summary exists. Raises on Redis failure.
        """
        from src.app.core.redis import redis_pool

        key = f"{_SUMMARY_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            summary = await conn.get(key)
            return summary or ""

    async def set_summary(self, user_id: str, summary: str) -> None:
        """Store or update the rolling session summary.

        Raises on Redis failure.
        """
        from src.app.core.redis import redis_pool

        settings = get_settings()
        key = f"{_SUMMARY_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            await conn.set(key, summary, ex=settings.session_ttl)

    # ------------------------------------------------------------------
    # Structured state packet
    # ------------------------------------------------------------------

    async def get_state_packet(self, user_id: str) -> SessionStatePacket | None:
        """Get the structured session state packet for a user."""
        from src.app.core.redis import redis_pool

        key = f"{_STATE_PACKET_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            raw_packet = await conn.get(key)
            if not raw_packet:
                return None
            return SessionStatePacket.model_validate_json(raw_packet)

    async def set_state_packet(
        self,
        user_id: str,
        packet: SessionStatePacket,
    ) -> None:
        """Store or update the structured session state packet."""
        from src.app.core.redis import redis_pool

        settings = get_settings()
        key = f"{_STATE_PACKET_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            await conn.set(key, packet.model_dump_json(), ex=settings.session_ttl)

    # ------------------------------------------------------------------
    # Pending tool confirmations
    # ------------------------------------------------------------------

    async def get_pending_tool_plan(self, user_id: str) -> PendingToolPlan | None:
        """Get the stored pending mutating-tool plan for a user."""
        from src.app.core.redis import redis_pool

        key = f"{_PENDING_TOOL_PLAN_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            raw_plan = await conn.get(key)
            if not raw_plan:
                return None
            return PendingToolPlan.model_validate_json(raw_plan)

    async def set_pending_tool_plan(
        self,
        user_id: str,
        plan: PendingToolPlan,
    ) -> None:
        """Store a pending mutating-tool plan for later confirmation."""
        from src.app.core.redis import redis_pool

        settings = get_settings()
        key = f"{_PENDING_TOOL_PLAN_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            await conn.set(key, plan.model_dump_json(), ex=settings.session_ttl)

    async def clear_pending_tool_plan(self, user_id: str) -> None:
        """Remove any stored pending mutating-tool plan for a user."""
        from src.app.core.redis import redis_pool

        key = f"{_PENDING_TOOL_PLAN_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            await conn.delete(key)

    # ------------------------------------------------------------------
    # Pending assistant-native conversation actions
    # ------------------------------------------------------------------

    async def get_pending_conversation_action(
        self,
        user_id: str,
    ) -> PendingConversationAction | None:
        """Get the stored retryable assistant-native action for a user."""
        from src.app.core.redis import redis_pool

        key = f"{_PENDING_CONVERSATION_ACTION_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            raw_action = await conn.get(key)
            if not raw_action:
                return None
            return PendingConversationAction.model_validate_json(raw_action)

    async def set_pending_conversation_action(
        self,
        user_id: str,
        action: PendingConversationAction,
    ) -> None:
        """Store a retryable assistant-native action for later continuity resolution."""
        from src.app.core.redis import redis_pool

        settings = get_settings()
        key = f"{_PENDING_CONVERSATION_ACTION_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            await conn.set(key, action.model_dump_json(), ex=settings.session_ttl)

    async def clear_pending_conversation_action(self, user_id: str) -> None:
        """Remove any stored retryable assistant-native action for a user."""
        from src.app.core.redis import redis_pool

        key = f"{_PENDING_CONVERSATION_ACTION_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            await conn.delete(key)

    # ------------------------------------------------------------------
    # Pending planning sessions
    # ------------------------------------------------------------------

    async def get_pending_planning_session(self, user_id: str) -> PendingPlanningSession | None:
        """Get the stored pending planning session for a user."""
        from src.app.core.redis import redis_pool

        key = f"{_PENDING_PLANNING_SESSION_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            raw_session = await conn.get(key)
            if not raw_session:
                return None
            return PendingPlanningSession.model_validate_json(raw_session)

    async def set_pending_planning_session(
        self,
        user_id: str,
        planning_session: PendingPlanningSession,
    ) -> None:
        """Store a pending planning session for later follow-up."""
        from src.app.core.redis import redis_pool

        settings = get_settings()
        key = f"{_PENDING_PLANNING_SESSION_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            await conn.set(key, planning_session.model_dump_json(), ex=settings.session_ttl)

    async def clear_pending_planning_session(self, user_id: str) -> None:
        """Remove any stored pending planning session for a user."""
        from src.app.core.redis import redis_pool

        key = f"{_PENDING_PLANNING_SESSION_KEY_PREFIX}{user_id}"

        async with redis_pool(self.redis_url) as conn:
            await conn.delete(key)

    # ------------------------------------------------------------------
    # Formatting (legacy — kept for backward compatibility)
    # ------------------------------------------------------------------

    def format_for_prompt(self, messages: list[ConversationMessage]) -> str:
        """Format conversation context as a string for specialist prompts.

        .. deprecated::
            Use :func:`~src.app.core.context_manager.assemble_context` instead
            for intelligent context assembly with summarization and relevance
            gating.  This method is retained for backward compatibility.
        """
        if not messages:
            return ""

        settings = get_settings()
        lines = ["<conversation_history>"]
        for msg in messages[-settings.working_memory_size :]:
            prefix = "User" if msg.role == "user" else f"Assistant ({msg.agent})"
            content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
            lines.append(f"{prefix}: {content}")
        lines.append("</conversation_history>")
        return "\n".join(lines)
