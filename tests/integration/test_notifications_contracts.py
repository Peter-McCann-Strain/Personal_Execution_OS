"""Integration tests for notifications endpoints through the full FastAPI app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from src.app.domain.constants import NotificationStatus


def _make_notification(
    *,
    notification_id: uuid.UUID | None = None,
    message: str = "Review your calendar",
    priority: str = "P1",
    category: str = "planning",
    status: str = NotificationStatus.UNREAD,
) -> MagicMock:
    notification = MagicMock()
    notification.id = notification_id or uuid.uuid4()
    notification.message = message
    notification.priority = priority
    notification.category = category
    notification.status = status
    notification.created_at = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    return notification


class TestNotificationContracts:
    """Verify notifications response contracts through the real app router."""

    async def test_list_notifications_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [_make_notification()]
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

        response = await client.get(
            "/api/notifications",
            params={"priority": "P0,P1", "category": "planning", "status": "unread"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["message"] == "Review your calendar"
        assert data["items"][0]["dismissed"] is False

    async def test_list_notifications_ignores_blank_priority_tokens_contract(
        self,
        integration_client,
    ):
        client, mock_session, _mock_anthropic = integration_client

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

        response = await client.get(
            "/api/notifications",
            params={
                "priority": " , P0 , ",
                "category": "planning",
                "status": "dismissed",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_list_notifications_ignores_empty_priority_list_contract(
        self,
        integration_client,
    ):
        client, mock_session, _mock_anthropic = integration_client

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

        response = await client.get(
            "/api/notifications",
            params={
                "priority": " , ",
                "category": "planning",
                "status": "read",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_dismiss_notification_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        notification_id = uuid.uuid4()
        notification = _make_notification(notification_id=notification_id)
        mock_session.get = AsyncMock(return_value=notification)

        response = await client.patch(f"/api/notifications/{notification_id}/dismiss")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert notification.status == "dismissed"
        mock_session.commit.assert_awaited()

    async def test_dismiss_notification_not_found_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        notification_id = uuid.uuid4()
        mock_session.get = AsyncMock(return_value=None)

        response = await client.patch(f"/api/notifications/{notification_id}/dismiss")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_dismiss_all_notifications_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        response = await client.patch("/api/notifications/dismiss-all")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_session.execute.assert_awaited_once()
        mock_session.commit.assert_awaited()

    async def test_mark_all_read_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        response = await client.patch("/api/notifications/mark-all-read")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_session.execute.assert_awaited_once()
        mock_session.commit.assert_awaited()

    async def test_unread_count_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        total_result = MagicMock()
        total_result.scalar_one.return_value = 5
        p0_result = MagicMock()
        p0_result.scalar_one.return_value = 1
        p1_result = MagicMock()
        p1_result.scalar_one.return_value = 0
        mock_session.execute = AsyncMock(side_effect=[total_result, p0_result, p1_result])

        response = await client.get("/api/notifications/unread-count")

        assert response.status_code == 200
        data = response.json()
        assert data == {"total": 5, "hasP0": True, "hasP1": False}
