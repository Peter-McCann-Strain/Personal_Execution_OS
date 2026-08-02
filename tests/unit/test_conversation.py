"""Tests for src.app.core.conversation — multi-turn conversation context."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.conversation import ConversationContext, ConversationMessage
from src.app.domain.models import (
    PendingConversationAction,
    PendingToolCall,
    PendingToolPlan,
    SessionStatePacket,
)


def _mock_settings():
    """Create mock settings with conversation defaults."""
    settings = MagicMock()
    settings.max_context_messages = 50
    settings.session_ttl = 14_400
    settings.working_memory_size = 4
    return settings


@pytest.fixture(autouse=True)
def _patch_settings():
    """Patch get_settings for all tests in this module."""
    with patch(
        "src.app.core.conversation.get_settings",
        return_value=_mock_settings(),
    ):
        yield


class TestConversationMessage:
    def test_to_dict(self):
        msg = ConversationMessage(
            role="user",
            content="Hello",
            agent="",
            timestamp="2026-03-16T12:00:00+00:00",
        )
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hello"
        assert d["agent"] == ""
        assert d["timestamp"] == "2026-03-16T12:00:00+00:00"

    def test_from_dict(self):
        data = {
            "role": "assistant",
            "content": "Hi there",
            "agent": "diary",
            "timestamp": "2026-03-16T12:00:00+00:00",
        }
        msg = ConversationMessage.from_dict(data)
        assert msg.role == "assistant"
        assert msg.content == "Hi there"
        assert msg.agent == "diary"

    def test_from_dict_missing_optional_fields(self):
        data = {"role": "user", "content": "Hello"}
        msg = ConversationMessage.from_dict(data)
        assert msg.agent == ""
        # Missing timestamp defaults to current time via __init__
        assert msg.timestamp != ""
        assert "T" in msg.timestamp

    def test_default_timestamp_generated(self):
        msg = ConversationMessage(role="user", content="Hi")
        assert msg.timestamp != ""
        assert "T" in msg.timestamp  # ISO format

    def test_roundtrip(self):
        msg = ConversationMessage(
            role="assistant",
            content="Response text",
            agent="memory",
            timestamp="2026-03-16T10:00:00+00:00",
        )
        restored = ConversationMessage.from_dict(msg.to_dict())
        assert restored.role == msg.role
        assert restored.content == msg.content
        assert restored.agent == msg.agent
        assert restored.timestamp == msg.timestamp


def _mock_redis_pool(mock_conn):
    """Create a mock async context manager that yields mock_conn."""

    @asynccontextmanager
    async def _pool(redis_url: str, **kwargs) -> AsyncIterator:
        yield mock_conn

    return _pool


def _failing_redis_pool():
    """Create a mock async context manager that raises on entry."""

    @asynccontextmanager
    async def _pool(redis_url: str, **kwargs) -> AsyncIterator:
        raise ConnectionError("Redis down")
        yield  # pragma: no cover — unreachable, needed for generator syntax

    return _pool


class TestConversationContext:
    def _make_mock_redis(self):
        """Create a mock Redis connection."""
        mock_conn = AsyncMock()
        mock_conn.rpush = AsyncMock()
        mock_conn.ltrim = AsyncMock()
        mock_conn.expire = AsyncMock()
        mock_conn.lrange = AsyncMock(return_value=[])
        return mock_conn

    async def test_add_message_stores_in_redis(self):
        mock_conn = self._make_mock_redis()
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            await ctx.add_message("user-1", "user", "Hello world")

        mock_conn.rpush.assert_awaited_once()
        call_args = mock_conn.rpush.call_args
        assert call_args[0][0] == "conv:user-1"
        payload = json.loads(call_args[0][1])
        assert payload["role"] == "user"
        assert payload["content"] == "Hello world"

    async def test_add_message_trims_and_sets_ttl(self):
        mock_conn = self._make_mock_redis()
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            await ctx.add_message("user-1", "user", "Hi")

        mock_conn.ltrim.assert_awaited_once_with("conv:user-1", -50, -1)
        mock_conn.expire.assert_awaited_once_with("conv:user-1", 14_400)

    async def test_get_context_returns_messages(self):
        mock_conn = self._make_mock_redis()
        stored = [
            json.dumps({"role": "user", "content": "Hello", "agent": "", "timestamp": "t1"}),
            json.dumps({"role": "assistant", "content": "Hi", "agent": "diary", "timestamp": "t2"}),
        ]
        mock_conn.lrange = AsyncMock(return_value=stored)
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            messages = await ctx.get_context("user-1")

        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"
        assert messages[1].agent == "diary"

    async def test_get_context_rejects_non_text_redis_entries(self):
        """Corrupted Redis list entries should fail before JSON deserialization."""
        mock_conn = self._make_mock_redis()
        mock_conn.lrange = AsyncMock(return_value=[{"role": "user", "content": "unsafe"}])
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with (
            patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)),
            pytest.raises(TypeError, match="non-text message"),
        ):
            await ctx.get_context("user-1")

    async def test_get_context_raises_on_redis_failure(self):
        """Redis failure propagates — no silent degradation."""
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with (
            patch("src.app.core.redis.redis_pool", _failing_redis_pool()),
            pytest.raises(ConnectionError, match="Redis down"),
        ):
            await ctx.get_context("user-1")

    async def test_add_message_raises_on_redis_error(self):
        """Redis failure propagates — no silent degradation."""
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with (
            patch("src.app.core.redis.redis_pool", _failing_redis_pool()),
            pytest.raises(ConnectionError, match="Redis down"),
        ):
            await ctx.add_message("user-1", "user", "Hello")

    async def test_add_message_includes_agent(self):
        mock_conn = self._make_mock_redis()
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            await ctx.add_message("user-1", "assistant", "Response", agent="diary")

        call_args = mock_conn.rpush.call_args
        payload = json.loads(call_args[0][1])
        assert payload["agent"] == "diary"


class TestRollingSummary:
    """Tests for get_summary / set_summary."""

    def _make_mock_redis(self):
        mock_conn = AsyncMock()
        mock_conn.get = AsyncMock(return_value=None)
        mock_conn.set = AsyncMock()
        return mock_conn

    async def test_get_summary_returns_stored_value(self):
        mock_conn = self._make_mock_redis()
        mock_conn.get = AsyncMock(return_value="Previously discussed goals.")
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            summary = await ctx.get_summary("user-1")

        assert summary == "Previously discussed goals."
        mock_conn.get.assert_awaited_once_with("conv_summary:user-1")

    async def test_get_summary_returns_empty_when_none(self):
        mock_conn = self._make_mock_redis()
        mock_conn.get = AsyncMock(return_value=None)
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            summary = await ctx.get_summary("user-1")

        assert summary == ""

    async def test_get_summary_raises_on_redis_failure(self):
        """Redis failure propagates — no silent degradation."""
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with (
            patch("src.app.core.redis.redis_pool", _failing_redis_pool()),
            pytest.raises(ConnectionError, match="Redis down"),
        ):
            await ctx.get_summary("user-1")

    async def test_set_summary_stores_with_ttl(self):
        mock_conn = self._make_mock_redis()
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            await ctx.set_summary("user-1", "Summary of conversation.")

        mock_conn.set.assert_awaited_once_with(
            "conv_summary:user-1",
            "Summary of conversation.",
            ex=14_400,
        )

    async def test_set_summary_raises_on_redis_error(self):
        """Redis failure propagates — no silent degradation."""
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with (
            patch("src.app.core.redis.redis_pool", _failing_redis_pool()),
            pytest.raises(ConnectionError, match="Redis down"),
        ):
            await ctx.set_summary("user-1", "Summary")


class TestStatePacketStorage:
    """Tests for get_state_packet / set_state_packet."""

    def _make_mock_redis(self):
        mock_conn = AsyncMock()
        mock_conn.get = AsyncMock(return_value=None)
        mock_conn.set = AsyncMock()
        return mock_conn

    async def test_get_state_packet_returns_packet(self):
        mock_conn = self._make_mock_redis()
        packet = SessionStatePacket(
            preferences=[],
            conversation_summary="Keep replies concise.",
        )
        mock_conn.get = AsyncMock(return_value=packet.model_dump_json())
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            restored = await ctx.get_state_packet("user-1")

        assert restored is not None
        assert restored.conversation_summary == "Keep replies concise."
        mock_conn.get.assert_awaited_once_with("conv_state:user-1")

    async def test_get_state_packet_returns_none_when_missing(self):
        mock_conn = self._make_mock_redis()
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            restored = await ctx.get_state_packet("user-1")

        assert restored is None

    async def test_set_state_packet_stores_json_with_ttl(self):
        mock_conn = self._make_mock_redis()
        ctx = ConversationContext(redis_url="redis://localhost:6379")
        packet = SessionStatePacket(
            open_loops=[],
            facts=[],
            preferences=[],
            active_entities=[],
            recent_artifacts=[],
            commitments=[],
            decisions=[],
            conversation_summary="Remember the travel planning context.",
        )

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            await ctx.set_state_packet("user-1", packet)

        key, payload = mock_conn.set.call_args.args[:2]
        assert key == "conv_state:user-1"
        assert "travel planning context" in payload
        assert mock_conn.set.call_args.kwargs["ex"] == 14_400

    async def test_set_state_packet_raises_on_redis_error(self):
        ctx = ConversationContext(redis_url="redis://localhost:6379")
        packet = SessionStatePacket()

        with (
            patch("src.app.core.redis.redis_pool", _failing_redis_pool()),
            pytest.raises(ConnectionError, match="Redis down"),
        ):
            await ctx.set_state_packet("user-1", packet)


class TestPendingToolPlanStorage:
    """Tests for pending mutating-tool confirmation plans."""

    def _make_mock_redis(self):
        mock_conn = AsyncMock()
        mock_conn.get = AsyncMock(return_value=None)
        mock_conn.set = AsyncMock()
        mock_conn.delete = AsyncMock()
        return mock_conn

    async def test_get_pending_tool_plan_returns_plan(self):
        mock_conn = self._make_mock_redis()
        plan = PendingToolPlan(
            plan_id="plan-1",
            original_user_message="Schedule lunch tomorrow",
            trust_label="trusted_user",
            tool_calls=[
                PendingToolCall(
                    tool_use_id="tool-1",
                    name="google-calendar__create_event",
                    input={"title": "Lunch"},
                    idempotency_key="idem-1",
                )
            ],
        )
        mock_conn.get = AsyncMock(return_value=plan.model_dump_json())
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            restored = await ctx.get_pending_tool_plan("user-1")

        assert restored is not None
        assert restored.plan_id == "plan-1"
        assert restored.tool_calls[0].name == "google-calendar__create_event"
        mock_conn.get.assert_awaited_once_with("conv_pending_tools:user-1")

    async def test_set_pending_tool_plan_stores_json_with_ttl(self):
        mock_conn = self._make_mock_redis()
        ctx = ConversationContext(redis_url="redis://localhost:6379")
        plan = PendingToolPlan(
            plan_id="plan-1",
            original_user_message="Schedule lunch tomorrow",
            trust_label="trusted_user",
            tool_calls=[
                PendingToolCall(
                    tool_use_id="tool-1",
                    name="google-calendar__create_event",
                    input={"title": "Lunch"},
                    idempotency_key="idem-1",
                )
            ],
        )

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            await ctx.set_pending_tool_plan("user-1", plan)

        key, payload = mock_conn.set.call_args.args[:2]
        assert key == "conv_pending_tools:user-1"
        assert "Schedule lunch tomorrow" in payload
        assert mock_conn.set.call_args.kwargs["ex"] == 14_400

    async def test_clear_pending_tool_plan_deletes_key(self):
        mock_conn = self._make_mock_redis()
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            await ctx.clear_pending_tool_plan("user-1")

        mock_conn.delete.assert_awaited_once_with("conv_pending_tools:user-1")


class TestPendingConversationActionStorage:
    def _make_mock_redis(self):
        mock_conn = AsyncMock()
        mock_conn.get = AsyncMock(return_value=None)
        mock_conn.set = AsyncMock()
        mock_conn.delete = AsyncMock()
        return mock_conn

    async def test_get_pending_conversation_action_returns_action(self):
        mock_conn = self._make_mock_redis()
        action = PendingConversationAction(
            action_id="action-1",
            action_type="save_note",
            status="failed",
            human_summary="Retry note save",
            normalized_payload={"note_payload": "hello"},
            idempotency_key="idem-1",
            retryable=True,
        )
        mock_conn.get = AsyncMock(return_value=action.model_dump_json())
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            restored = await ctx.get_pending_conversation_action("user-1")

        assert restored is not None
        assert restored.action_id == "action-1"
        assert restored.action_type == "save_note"
        mock_conn.get.assert_awaited_once_with("conv_pending_action:user-1")

    async def test_set_pending_conversation_action_stores_json_with_ttl(self):
        mock_conn = self._make_mock_redis()
        ctx = ConversationContext(redis_url="redis://localhost:6379")
        action = PendingConversationAction(
            action_id="action-1",
            action_type="save_note",
            status="failed",
            human_summary="Retry note save",
            normalized_payload={"note_payload": "hello"},
            idempotency_key="idem-1",
            retryable=True,
        )

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            await ctx.set_pending_conversation_action("user-1", action)

        key, payload = mock_conn.set.call_args.args[:2]
        assert key == "conv_pending_action:user-1"
        assert "Retry note save" in payload
        assert mock_conn.set.call_args.kwargs["ex"] == 14_400

    async def test_clear_pending_conversation_action_deletes_key(self):
        mock_conn = self._make_mock_redis()
        ctx = ConversationContext(redis_url="redis://localhost:6379")

        with patch("src.app.core.redis.redis_pool", _mock_redis_pool(mock_conn)):
            await ctx.clear_pending_conversation_action("user-1")

        mock_conn.delete.assert_awaited_once_with("conv_pending_action:user-1")


class TestFormatForPrompt:
    def test_empty_messages_returns_empty_string(self):
        ctx = ConversationContext(redis_url="redis://localhost:6379")
        assert ctx.format_for_prompt([]) == ""

    def test_formats_user_and_assistant_messages(self):
        ctx = ConversationContext(redis_url="redis://localhost:6379")
        messages = [
            ConversationMessage(role="user", content="What day is it?"),
            ConversationMessage(role="assistant", content="It's Monday", agent="diary"),
        ]
        result = ctx.format_for_prompt(messages)
        assert "<conversation_history>" in result
        assert "</conversation_history>" in result
        assert "User: What day is it?" in result
        assert "Assistant (diary): It's Monday" in result

    def test_truncates_long_messages(self):
        ctx = ConversationContext(redis_url="redis://localhost:6379")
        long_content = "x" * 600
        messages = [
            ConversationMessage(role="user", content=long_content),
        ]
        result = ctx.format_for_prompt(messages)
        assert "..." in result
        assert len(long_content) > 500

    def test_limits_to_last_working_memory_size_messages(self):
        ctx = ConversationContext(redis_url="redis://localhost:6379")
        messages = [ConversationMessage(role="user", content=f"Message {i}") for i in range(10)]
        result = ctx.format_for_prompt(messages)
        # working_memory_size=4 in mock settings, so last 4 messages (6-9)
        assert "Message 6" in result
        assert "Message 9" in result
        assert "Message 5" not in result

    def test_assistant_without_agent(self):
        ctx = ConversationContext(redis_url="redis://localhost:6379")
        messages = [
            ConversationMessage(role="assistant", content="Hello", agent=""),
        ]
        result = ctx.format_for_prompt(messages)
        assert "Assistant (): Hello" in result
