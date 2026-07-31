"""Integration tests for chat routing flow.

Tests the complete path: POST /api/chat -> classify_intent -> specialist handler -> response.
Uses the full FastAPI app with mocked Anthropic client and database session.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.app.domain.models import ChatResponse, Intent, IntentType, Specialist


def _make_fake_conversation_context() -> AsyncMock:
    """Return a conversation context stub that avoids real Redis access."""
    context = AsyncMock()
    context.get_context.return_value = []
    context.get_summary.return_value = ""
    context.get_state_packet.return_value = None
    context.get_pending_tool_plan.return_value = None
    context.get_pending_planning_session.return_value = None
    context.get_pending_conversation_action.return_value = None
    return context


class TestChatRouting:
    """Test that messages route to the correct specialist."""

    async def test_diary_capture_routes_correctly(self, integration_client):
        """A personal capture should route to the diary specialist."""
        client, _mock_session, _mock_anthropic = integration_client

        mock_intent = Intent(
            intent_type=IntentType.CAPTURE,
            specialist=Specialist.DIARY,
            confidence=0.95,
            reasoning="Personal diary entry about the park",
        )

        mock_response = ChatResponse(
            content="Captured your diary entry about the park.",
            agent="diary",
            metadata={"mood_score": 8.0, "tokens_used": 150},
        )

        with (
            patch(
                "src.app.domain.services.chat.classify_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch(
                "src.app.domain.services.chat.handle_diary",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch(
                "src.app.domain.services.chat.evaluate_response",
                new_callable=AsyncMock,
            ) as mock_eval,
            patch(
                "src.app.domain.services.chat.create_interaction",
                new_callable=AsyncMock,
            ) as mock_record,
            patch(
                "src.app.domain.services.chat._get_conversation_context",
                return_value=_make_fake_conversation_context(),
            ),
        ):
            from src.app.core.evaluator import EvaluationResult

            mock_eval.return_value = EvaluationResult(passes=True, issue="")
            mock_record.return_value = AsyncMock(id="fake-interaction-id")

            response = await client.post(
                "/api/chat",
                json={
                    "content": "Had a great day at the park today",
                    "source": "api",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["agent"] == "diary"
        assert "park" in data["content"].lower() or "captured" in data["content"].lower()
        assert "metadata" in data
        assert data["metadata"]["agent_used"] == "diary"

    async def test_memory_query_routes_correctly(self, integration_client):
        """A memory query should route to the memory specialist."""
        client, _mock_session, _mock_anthropic = integration_client

        mock_intent = Intent(
            intent_type=IntentType.QUERY,
            specialist=Specialist.MEMORY,
            confidence=0.9,
            reasoning="User asking about past events",
        )

        mock_response = ChatResponse(
            content="Based on your diary entries, you went to the park last Tuesday.",
            agent="memory",
            metadata={"confidence": 0.85, "tokens_used": 120},
        )

        with (
            patch(
                "src.app.domain.services.chat.classify_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch(
                "src.app.domain.services.chat.handle_memory",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch(
                "src.app.domain.services.chat.evaluate_response",
                new_callable=AsyncMock,
            ) as mock_eval,
            patch(
                "src.app.domain.services.chat.create_interaction",
                new_callable=AsyncMock,
            ) as mock_record,
            patch(
                "src.app.domain.services.chat._get_conversation_context",
                return_value=_make_fake_conversation_context(),
            ),
        ):
            from src.app.core.evaluator import EvaluationResult

            mock_eval.return_value = EvaluationResult(passes=True, issue="")
            mock_record.return_value = AsyncMock(id="fake-interaction-id")

            response = await client.post(
                "/api/chat",
                json={
                    "content": "When did I last go to the park?",
                    "source": "api",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["agent"] == "memory"
        assert "park" in data["content"].lower()

    async def test_research_routes_correctly(self, integration_client):
        """A research request should route to the research specialist."""
        client, _mock_session, _mock_anthropic = integration_client

        mock_intent = Intent(
            intent_type=IntentType.RESEARCH,
            specialist=Specialist.RESEARCH,
            confidence=0.92,
            reasoning="User wants to research a topic",
        )

        mock_response = ChatResponse(
            content="Here is what I found about quantum computing...",
            agent="research",
            metadata={"tokens_used": 500},
        )

        with (
            patch(
                "src.app.domain.services.chat.classify_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch(
                "src.app.domain.services.chat.handle_research",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch(
                "src.app.domain.services.chat.evaluate_response",
                new_callable=AsyncMock,
            ) as mock_eval,
            patch(
                "src.app.domain.services.chat.create_interaction",
                new_callable=AsyncMock,
            ) as mock_record,
            patch(
                "src.app.domain.services.chat._get_conversation_context",
                return_value=_make_fake_conversation_context(),
            ),
        ):
            from src.app.core.evaluator import EvaluationResult

            mock_eval.return_value = EvaluationResult(passes=True, issue="")
            mock_record.return_value = AsyncMock(id="fake-interaction-id")

            response = await client.post(
                "/api/chat",
                json={
                    "content": "Research the latest developments in quantum computing",
                    "source": "api",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["agent"] == "research"
        assert "quantum" in data["content"].lower()

    async def test_chat_rejects_empty_content(self, integration_client):
        """Chat endpoint should reject empty content with 422."""
        client, _, _ = integration_client

        response = await client.post(
            "/api/chat",
            json={
                "content": "",
                "source": "api",
            },
        )

        # StringConstraints(min_length=1) triggers validation error
        assert response.status_code == 422

    async def test_chat_rejects_whitespace_only_content(self, integration_client):
        """Chat endpoint should reject whitespace-only content with 422.

        The ChatRequest model uses strip_whitespace=True, so a string of spaces
        becomes empty and fails the min_length=1 constraint.
        """
        client, _, _ = integration_client

        response = await client.post(
            "/api/chat",
            json={
                "content": "   ",
                "source": "api",
            },
        )

        assert response.status_code == 422

    async def test_chat_rejects_missing_content(self, integration_client):
        """Chat endpoint should reject a request with no content field."""
        client, _, _ = integration_client

        response = await client.post(
            "/api/chat",
            json={
                "source": "api",
            },
        )

        assert response.status_code == 422

    async def test_chat_rejects_invalid_source(self, integration_client):
        """Chat endpoint should reject an unknown source value."""
        client, _, _ = integration_client

        response = await client.post(
            "/api/chat",
            json={
                "content": "Hello there",
                "source": "smoke_signal",
            },
        )

        assert response.status_code == 422

    async def test_chat_response_contains_metadata(self, integration_client):
        """Response should include metadata with request_id, agent_used, and latency_ms."""
        client, _mock_session, _mock_anthropic = integration_client

        mock_intent = Intent(
            intent_type=IntentType.CAPTURE,
            specialist=Specialist.DIARY,
            confidence=0.88,
            reasoning="Diary capture",
        )

        mock_response = ChatResponse(
            content="Got it.",
            agent="diary",
            metadata={"tokens_used": 100},
        )

        with (
            patch(
                "src.app.domain.services.chat.classify_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch(
                "src.app.domain.services.chat.handle_diary",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch(
                "src.app.domain.services.chat.evaluate_response",
                new_callable=AsyncMock,
            ) as mock_eval,
            patch(
                "src.app.domain.services.chat.create_interaction",
                new_callable=AsyncMock,
            ) as mock_record,
            patch(
                "src.app.domain.services.chat._get_conversation_context",
                return_value=_make_fake_conversation_context(),
            ),
        ):
            from src.app.core.evaluator import EvaluationResult

            mock_eval.return_value = EvaluationResult(passes=True, issue="")
            mock_record.return_value = AsyncMock(id="fake-interaction-id")

            response = await client.post(
                "/api/chat",
                json={"content": "Quick note", "source": "api"},
            )

        assert response.status_code == 200
        meta = response.json()["metadata"]
        assert "request_id" in meta
        assert meta["agent_used"] == "diary"
        assert "latency_ms" in meta
        assert isinstance(meta["latency_ms"], int)
        assert meta["latency_ms"] >= 0

    async def test_evaluator_failure_does_not_break_response(self, integration_client):
        """If the evaluator raises, the chat endpoint should still return the specialist response."""
        client, _mock_session, _mock_anthropic = integration_client

        mock_intent = Intent(
            intent_type=IntentType.CAPTURE,
            specialist=Specialist.DIARY,
            confidence=0.95,
            reasoning="Diary entry",
        )

        mock_response = ChatResponse(
            content="Captured.",
            agent="diary",
            metadata={},
        )

        with (
            patch(
                "src.app.domain.services.chat.classify_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch(
                "src.app.domain.services.chat.handle_diary",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch(
                "src.app.domain.services.chat.evaluate_response",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Evaluator exploded"),
            ),
            patch(
                "src.app.domain.services.chat.create_interaction",
                new_callable=AsyncMock,
            ) as mock_record,
            patch(
                "src.app.domain.services.chat._get_conversation_context",
                return_value=_make_fake_conversation_context(),
            ),
        ):
            mock_record.return_value = AsyncMock(id="fake-interaction-id")

            response = await client.post(
                "/api/chat",
                json={"content": "Note to self", "source": "api"},
            )

        # The response should still succeed — evaluator failure is non-fatal
        assert response.status_code == 200
        data = response.json()
        assert data["agent"] == "diary"
        assert data["content"] == "Captured."
