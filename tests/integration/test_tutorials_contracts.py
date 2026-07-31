"""Integration tests for tutorials endpoints through the full FastAPI app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.app.domain.models import ChatResponse


def _make_tutorial_mock(
    *,
    tutorial_id: uuid.UUID | None = None,
    topic: str = "Caching",
    work_type: str = "essay",
    phase: str = "complete",
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    tutorial = MagicMock()
    tutorial.id = tutorial_id or uuid.uuid4()
    tutorial.topic = topic
    tutorial.work_type = work_type
    tutorial.phase = phase
    tutorial.submitted_work = "My essay..."
    tutorial.turn_count = 8
    tutorial.bloom_start = "understand"
    tutorial.bloom_end = "analyse"
    tutorial.speaking_ratio_student_pct = 72.0
    tutorial.knowledge_gaps_found = 3
    tutorial.knowledge_gaps_addressed = 2
    tutorial.created_at = now
    tutorial.completed_at = now
    tutorial.propositions = [{"index": 0, "text": "Claim"}]
    tutorial.transcript = [{"role": "tutor", "content": "Question?"}]
    tutorial.analysis = {"summary": "Good."}
    return tutorial


class TestTutorialContracts:
    """Verify tutorial response contracts through the real app router."""

    async def test_list_tutorials_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client

        tutorials = [
            _make_tutorial_mock(),
            _make_tutorial_mock(topic="Design"),
        ]

        with patch(
            "src.app.api.routes.tutorials.get_past_tutorials",
            new_callable=AsyncMock,
            return_value=tutorials,
        ):
            response = await client.get("/api/tutorials", params={"limit": 2, "offset": 0})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["has_more"] is False
        assert len(data["items"]) == 2
        assert data["items"][0]["topic"] == "Caching"
        assert data["items"][1]["topic"] == "Design"

    async def test_get_tutorial_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        tutorial = _make_tutorial_mock()

        with patch(
            "src.app.api.routes.tutorials.get_tutorial_session",
            new_callable=AsyncMock,
            return_value=tutorial,
        ):
            response = await client.get(f"/api/tutorials/{tutorial.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(tutorial.id)
        assert data["submitted_work"] == "My essay..."
        assert data["analysis"] == {"summary": "Good."}

    async def test_get_tutorial_not_found_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        tutorial_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.tutorials.get_tutorial_session",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"/api/tutorials/{tutorial_id}")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_start_tutorial_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        tutorial_id = uuid.uuid4()
        mock_response = ChatResponse(
            content="Tell me about caching.",
            agent="socratic",
            metadata={"phase": "dialogue", "speaker": "tutor"},
        )

        with patch(
            "src.app.api.routes.tutorials.start_tutorial",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await client.post(f"/api/tutorials/{tutorial_id}/start")

        assert response.status_code == 200
        data = response.json()
        assert data["tutorial_id"] == str(tutorial_id)
        assert data["content"] == "Tell me about caching."
        assert data["phase"] == "dialogue"
        assert data["speaker"] == "tutor"
        mock_session.refresh.assert_not_awaited()

    async def test_tutorial_turn_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        tutorial_id = uuid.uuid4()
        mock_response = ChatResponse(
            content="What evidence supports that?",
            agent="socratic",
            metadata={"phase": "dialogue", "speaker": "tutor", "turn": 3},
        )

        with patch(
            "src.app.api.routes.tutorials.process_tutorial_turn",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await client.post(
                f"/api/tutorials/{tutorial_id}/turn",
                json={"message": "Caching stores data."},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["tutorial_id"] == str(tutorial_id)
        assert data["content"] == "What evidence supports that?"
        assert data["turn"] == 3

    async def test_end_tutorial_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        tutorial_id = uuid.uuid4()
        mock_response = ChatResponse(
            content="Tutorial ended.\n\n## Analysis",
            agent="socratic",
            metadata={"phase": "complete", "analysis": {"summary": "Good session."}},
        )

        with patch(
            "src.app.api.routes.tutorials.end_tutorial",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await client.post(f"/api/tutorials/{tutorial_id}/end")

        assert response.status_code == 200
        data = response.json()
        assert data["tutorial_id"] == str(tutorial_id)
        assert data["phase"] == "complete"
        assert data["analysis"] == {"summary": "Good session."}
