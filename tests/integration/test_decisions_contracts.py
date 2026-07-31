"""Integration tests for decisions endpoints through the full FastAPI app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_decision(
    *,
    decision_id: uuid.UUID | None = None,
    title: str = "Adopt LangGraph",
    decision_made: str = "Use LangGraph for agent orchestration",
    context: str | None = "Needed a more robust orchestration layer",
    options_considered: list[str] | None = None,
    reasoning: str | None = "Best fit for graph-based workflows",
    expected_outcome: str | None = "Clearer and safer multi-agent routing",
    actual_outcome: str | None = None,
    outcome_rating: float | None = None,
    tags: list[str] | None = None,
    review_date: datetime | None = None,
    status: str = "pending_review",
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    decision = MagicMock()
    decision.id = decision_id or uuid.uuid4()
    decision.title = title
    decision.context = context
    decision.options_considered = options_considered or ["LangGraph", "CrewAI", "AutoGen"]
    decision.decision_made = decision_made
    decision.reasoning = reasoning
    decision.expected_outcome = expected_outcome
    decision.actual_outcome = actual_outcome
    decision.outcome_rating = outcome_rating
    decision.tags = tags or ["agents", "architecture"]
    decision.review_date = review_date
    decision.status = status
    decision.created_at = now
    decision.updated_at = now
    return decision


class TestDecisionContracts:
    """Verify decisions response contracts through the real app router."""

    async def test_list_decisions_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client

        with patch(
            "src.app.api.routes.decisions.repo_get_decisions",
            new_callable=AsyncMock,
            return_value=([_make_decision()], 1),
        ):
            response = await client.get("/api/decisions")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "Adopt LangGraph"
        assert data["items"][0]["status"] == "pending_review"

    async def test_due_review_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client

        with patch(
            "src.app.api.routes.decisions.repo_get_decisions_due_for_review",
            new_callable=AsyncMock,
            return_value=[_make_decision(title="Review router choice")],
        ):
            response = await client.get("/api/decisions/due-review")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Review router choice"

    async def test_get_decision_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        decision_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.decisions.repo_get_decision_by_id",
            new_callable=AsyncMock,
            return_value=_make_decision(decision_id=decision_id),
        ):
            response = await client.get(f"/api/decisions/{decision_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(decision_id)
        assert data["title"] == "Adopt LangGraph"
        assert data["decision_made"] == "Use LangGraph for agent orchestration"

    async def test_get_decision_not_found_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        decision_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.decisions.repo_get_decision_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"/api/decisions/{decision_id}")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_create_decision_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        parent_review_date = datetime(2026, 6, 1, tzinfo=UTC)
        decision_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.decisions.repo_create_decision",
            new_callable=AsyncMock,
            return_value=_make_decision(
                decision_id=decision_id,
                review_date=parent_review_date,
            ),
        ) as create_decision:
            response = await client.post(
                "/api/decisions",
                json={
                    "title": "Adopt LangGraph",
                    "decision_made": "Use LangGraph for agent orchestration",
                    "context": "Needed a more robust orchestration layer",
                    "options_considered": ["LangGraph", "CrewAI", "AutoGen"],
                    "reasoning": "Best fit for graph-based workflows",
                    "expected_outcome": "Clearer and safer multi-agent routing",
                    "tags": ["agents", "architecture"],
                    "review_date": "2026-06-01T00:00:00+00:00",
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(decision_id)
        assert data["title"] == "Adopt LangGraph"
        create_decision.assert_awaited_once()
        mock_session.refresh.assert_awaited()

    async def test_create_decision_minimal_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        decision_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.decisions.repo_create_decision",
            new_callable=AsyncMock,
            return_value=_make_decision(
                decision_id=decision_id,
                title="Minimal decision",
                decision_made="Ship it",
                context=None,
                options_considered=None,
                reasoning=None,
                expected_outcome=None,
                tags=None,
            ),
        ):
            response = await client.post(
                "/api/decisions",
                json={
                    "title": "Minimal decision",
                    "decision_made": "Ship it",
                },
            )

        assert response.status_code == 201
        assert response.json()["id"] == str(decision_id)
        mock_session.refresh.assert_awaited()

    async def test_record_outcome_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        decision_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.decisions.repo_update_decision_outcome",
            new_callable=AsyncMock,
            return_value=_make_decision(
                decision_id=decision_id,
                actual_outcome="Queries are 3x faster",
                outcome_rating=8.5,
                status="reviewed",
            ),
        ) as update_outcome:
            response = await client.patch(
                f"/api/decisions/{decision_id}/outcome",
                json={
                    "actual_outcome": "Queries are 3x faster",
                    "outcome_rating": 8.5,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(decision_id)
        assert data["actual_outcome"] == "Queries are 3x faster"
        assert data["outcome_rating"] == 8.5
        update_outcome.assert_awaited_once()
        mock_session.refresh.assert_awaited()

    async def test_record_outcome_not_found_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        decision_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.decisions.repo_update_decision_outcome",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.patch(
                f"/api/decisions/{decision_id}/outcome",
                json={
                    "actual_outcome": "Could not evaluate",
                    "outcome_rating": 1.0,
                },
            )

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"
