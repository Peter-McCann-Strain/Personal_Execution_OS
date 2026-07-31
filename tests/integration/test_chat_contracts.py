"""Integration tests for streaming chat and context inspection contracts."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

from src.app.domain.models import ChatResponse


def _parse_sse_events(body: str) -> list[tuple[str, dict]]:
    """Parse a small SSE body into ordered (event, data) pairs."""
    parsed: list[tuple[str, dict]] = []

    for chunk in body.split("\n\n"):
        if not chunk.strip():
            continue

        event_name = "message"
        data_parts: list[str] = []

        for line in chunk.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_parts.append(line.split(":", 1)[1].strip())

        if not data_parts:
            continue

        parsed.append((event_name, json.loads("\n".join(data_parts))))

    return parsed


@dataclass(slots=True)
class _FakeConversationMessage:
    role: str
    content: str
    agent: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {"role": self.role, "content": self.content}
        if self.agent:
            payload["agent"] = self.agent
        return payload


class TestChatStreamingContract:
    """Exercise the streaming and context-inspection routes via the full app."""

    async def test_chat_returns_json_contract_with_metadata(
        self,
        integration_client,
    ):
        """Synchronous chat endpoint returns the expected JSON response contract."""
        client, _mock_session, _mock_anthropic = integration_client

        mock_response = ChatResponse(
            content="Got it.",
            agent="diary",
            metadata={
                "tool_calls": [{"name": "diary.save"}],
                "tool_count": 1,
                "errors": 0,
                "tokens_used": 12,
            },
        )

        with patch(
            "src.app.api.routes.chat.process_message",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await client.post(
                "/api/chat",
                json={"content": "Capture this note", "source": "api"},
            )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")

        data = response.json()
        assert data["content"] == "Got it."
        assert data["agent"] == "diary"
        assert "metadata" in data

        metadata = data["metadata"]
        assert metadata["agent_used"] == "diary"
        assert metadata["tokens_used"] == 12
        assert metadata["latency_ms"] >= 0
        assert isinstance(metadata["request_id"], str)
        uuid.UUID(metadata["request_id"])
        assert metadata["details"]["tool_calls"] == [{"name": "diary.save"}]
        assert metadata["details"]["tool_count"] == 1
        assert metadata["details"]["errors"] == 0

    async def test_chat_stream_includes_tool_status_and_final_metadata(
        self,
        integration_client,
    ):
        """Streaming endpoint emits agent, tool, token, and final events in order."""
        client, _mock_session, _mock_anthropic = integration_client

        mock_response = ChatResponse(
            content="Tool run complete.",
            agent="tools",
            metadata={
                "tool_calls": [{"name": "calendar.lookup"}],
                "tool_events": [
                    {
                        "name": "calendar.lookup",
                        "status": "executed",
                        "details": {"result_preview": "Meeting at 3pm"},
                    }
                ],
                "tool_count": 1,
                "errors": 0,
                "tokens_used": 42,
            },
        )

        with patch(
            "src.app.api.routes.chat.process_message",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await client.post(
                "/api/chat/stream",
                json={"content": "Check my calendar", "source": "api"},
            )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        events = _parse_sse_events(response.text)
        event_names = [name for name, _payload in events]

        assert event_names[0] == "message_start"
        assert event_names[1] == "agent"
        assert "tool_status" in event_names
        assert event_names[-1] == "message_end"

        tool_event = next(payload for name, payload in events if name == "tool_status")
        assert tool_event["tool_count"] == 1
        assert tool_event["tool_calls"] == [{"name": "calendar.lookup"}]
        assert tool_event["tool_events"][0]["status"] == "executed"

        final_payload = events[-1][1]
        assert final_payload["agent"] == "tools"
        assert final_payload["content"] == "Tool run complete."
        assert final_payload["metadata"]["agent_used"] == "tools"
        assert final_payload["metadata"]["tokens_used"] == 42
        assert (
            final_payload["metadata"]["tool_events"][0]["details"]["result_preview"]
            == "Meeting at 3pm"
        )

    async def test_chat_stream_surfaces_error_event_when_processing_fails(
        self,
        integration_client,
    ):
        """Streaming endpoint keeps the protocol intact even when the handler fails."""
        client, _mock_session, _mock_anthropic = integration_client

        with patch(
            "src.app.api.routes.chat.process_message",
            new_callable=AsyncMock,
            side_effect=RuntimeError("model unavailable"),
        ):
            response = await client.post(
                "/api/chat/stream",
                json={"content": "Hello", "source": "api"},
            )

        assert response.status_code == 200

        events = _parse_sse_events(response.text)
        assert [name for name, _payload in events] == ["message_start", "error"]
        assert (
            events[1][1]["error"] == "Internal error while generating the response (RuntimeError)."
        )

    async def test_context_inspect_uses_conversation_state_and_engine_output(
        self,
        integration_client,
    ):
        """Context inspection route assembles from stored history without running a specialist."""
        client, _mock_session, _mock_anthropic = integration_client

        fake_context = AsyncMock()
        fake_context.get_context.return_value = [
            _FakeConversationMessage(
                role="assistant",
                content="Previous tool output",
                agent="tools",
            ),
        ]
        fake_context.get_summary.return_value = "Rolling summary"

        mock_engine = AsyncMock()
        mock_engine.assemble.return_value.inspection = {
            "engine": "hierarchical",
            "history_summarized": True,
            "pruned_messages": 1,
            "pruned_characters": 2400,
            "durable_memory_candidates": [
                {
                    "category": "decision",
                    "excerpt": "We chose the image-based deploy path.",
                    "source_role": "assistant",
                },
            ],
            "rag_chunks_included": 0,
            "rag_chunks_filtered": 0,
            "total_tokens_estimate": 128,
            "sections": [
                {
                    "name": "conversation",
                    "tokens": 64,
                    "item_count": 1,
                    "present": True,
                },
            ],
        }

        with (
            patch(
                "src.app.api.routes.chat._get_conversation_context",
                return_value=fake_context,
            ),
            patch(
                "src.app.api.routes.chat._retrieve_supporting_context",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.api.routes.chat.get_default_context_engine",
                return_value=mock_engine,
            ),
        ):
            response = await client.post(
                "/api/chat/context-inspect",
                json={"content": "Inspect this conversation", "source": "api"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["inspection"]["historySummarized"] is True
        assert data["inspection"]["prunedMessages"] == 1
        assert data["inspection"]["durableMemoryCandidates"][0]["category"] == "decision"

        mock_engine.assemble.assert_awaited_once()
        assemble_kwargs = mock_engine.assemble.await_args.kwargs
        assert assemble_kwargs["conversation_messages"] == [
            {
                "role": "assistant",
                "content": "Previous tool output",
                "agent": "tools",
            },
        ]
        assert assemble_kwargs["conversation_summary"] == "Rolling summary"
        assert assemble_kwargs["user_message"] == "Inspect this conversation"
