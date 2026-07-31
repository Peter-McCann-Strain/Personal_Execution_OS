"""Integration tests for commitments endpoints through the full FastAPI app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


def _make_commitment(
    *,
    commitment_id: uuid.UUID | None = None,
    status: str = "detected",
    temporal_normalized: datetime | None = None,
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    commitment = MagicMock()
    commitment.id = commitment_id or uuid.uuid4()
    commitment.verbatim_text = "I'll send the report tomorrow."
    commitment.normalized_action = "Send the report"
    commitment.who_committed = "Alex"
    commitment.who_to = "Team"
    commitment.temporal_expression_raw = "tomorrow"
    commitment.temporal_normalized = temporal_normalized
    commitment.commitment_type = "promise"
    commitment.confidence_score = 0.92
    commitment.status = status
    commitment.created_at = now
    commitment.updated_at = now
    return commitment


class TestCommitmentsContracts:
    """Verify commitments response contracts through the real app router."""

    async def test_create_commitment_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        with patch(
            "src.app.api.routes.commitments.repo_create_commitment",
            new_callable=AsyncMock,
            return_value=_make_commitment(),
        ):
            response = await client.post(
                "/api/commitments",
                json={
                    "verbatim_text": "I'll send the report tomorrow.",
                    "normalized_action": "Send the report",
                    "who_committed": "Alex",
                    "who_to": "Team",
                    "temporal_expression": "tomorrow",
                    "confidence_score": 0.92,
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert data["normalized_action"] == "Send the report"
        assert data["status"] == "detected"
        mock_session.refresh.assert_awaited()

    async def test_get_overdue_commitments_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client

        with patch(
            "src.app.api.routes.commitments.repo_get_overdue_commitments",
            new_callable=AsyncMock,
            return_value=[
                _make_commitment(
                    status="active",
                    temporal_normalized=datetime.now(UTC) - timedelta(days=1),
                )
            ],
        ):
            response = await client.get("/api/commitments/overdue")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "active"
        assert data[0]["temporal_normalized"] is not None

    async def test_get_open_commitments_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client

        with patch(
            "src.app.api.routes.commitments.repo_get_open_commitments",
            new_callable=AsyncMock,
            return_value=[_make_commitment(status="in_progress")],
        ) as get_open:
            response = await client.get("/api/commitments/open", params={"limit": 7})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "in_progress"
        get_open.assert_awaited_once()

    async def test_update_commitment_status_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        commitment_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.commitments.repo_update_commitment_status",
            new_callable=AsyncMock,
            return_value=_make_commitment(
                commitment_id=commitment_id,
                status="completed",
            ),
        ):
            response = await client.patch(
                f"/api/commitments/{commitment_id}/status",
                json={"status": "completed"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(commitment_id)
        assert data["status"] == "completed"
        mock_session.refresh.assert_awaited()

    async def test_update_commitment_status_not_found_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        commitment_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.commitments.repo_update_commitment_status",
            new_callable=AsyncMock,
            side_effect=ValueError(f"Commitment not found: {commitment_id}"),
        ):
            response = await client.patch(
                f"/api/commitments/{commitment_id}/status",
                json={"status": "completed"},
            )

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"
