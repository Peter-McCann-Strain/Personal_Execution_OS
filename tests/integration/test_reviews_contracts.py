"""Integration tests for reviews endpoints through the full FastAPI app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock


def _make_review(
    *,
    review_id: uuid.UUID | None = None,
    review_type: str = "weekly",
    period: str = "2026-03-09 to 2026-03-16",
    content: dict | None = None,
) -> MagicMock:
    now = datetime(2026, 3, 16, 12, 0, tzinfo=UTC)
    review = MagicMock()
    review.id = review_id or uuid.uuid4()
    review.review_type = review_type
    review.period = period
    review.content = content or {
        "accomplishments": ["Completed project kickoff", "Morning runs"],
        "mood_summary": "Generally positive mood this period.",
        "average_mood": 7.5,
        "goal_progress": [{"title": "Ship MVP", "progress": 0.6, "status": "active"}],
        "open_commitments": [{"action": "Follow up with Alice", "status": "detected"}],
        "relationship_alerts": [],
        "patterns_noticed": ["Higher energy on workout days"],
        "recommendations": ["Keep morning routine"],
        "key_insight": "Consistency drives progress.",
    }
    review.created_at = now
    return review


class TestReviewsContracts:
    """Verify review response contracts through the real app router."""

    async def test_list_reviews_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [_make_review()]
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

        response = await client.get("/api/reviews")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["period"] == "2026-03-09 to 2026-03-16"
        assert item["average_mood"] == 7.5
        assert item["key_insight"] == "Consistency drives progress."

    async def test_get_review_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        review_id = uuid.uuid4()
        mock_session.get = AsyncMock(return_value=_make_review(review_id=review_id))

        response = await client.get(f"/api/reviews/{review_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(review_id)
        assert isinstance(data["goal_progress"], list)
        assert isinstance(data["open_commitments"], list)

    async def test_get_review_not_found_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        review_id = uuid.uuid4()
        mock_session.get = AsyncMock(return_value=None)

        response = await client.get(f"/api/reviews/{review_id}")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_generate_weekly_review_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        generated_id = uuid.uuid4()

        episodes_result = MagicMock()
        episodes_result.scalars.return_value.all.return_value = []
        goals_result = MagicMock()
        goals_result.scalars.return_value.all.return_value = []
        commitments_result = MagicMock()
        commitments_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(
            side_effect=[episodes_result, goals_result, commitments_result],
        )

        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        def _set_review_metadata(review_obj):
            review_obj.id = generated_id
            review_obj.created_at = datetime(2026, 3, 16, 12, 0, tzinfo=UTC)

        mock_session.add.side_effect = _set_review_metadata

        response = await client.post("/api/reviews/generate", json={"type": "weekly"})

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(generated_id)
        assert data["accomplishments"] == []
        assert data["average_mood"] is None
        assert data["goal_progress"] == []
        assert data["open_commitments"] == []
        mock_session.commit.assert_awaited_once()
