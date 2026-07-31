"""Integration tests for calendar endpoints through the full FastAPI app."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_event(
    *,
    event_id: str = "ev_123",
    summary: str = "Team standup",
    start: datetime | date | None = None,
    end: datetime | date | None = None,
    location: str | None = "Office",
    description: str | None = "Daily standup meeting",
    attendees: list[str] | None = None,
) -> MagicMock:
    event = MagicMock()
    event.id = event_id
    event.summary = summary
    event.start = start or datetime(2026, 3, 16, 9, 0, tzinfo=UTC)
    event.end = end or datetime(2026, 3, 16, 10, 0, tzinfo=UTC)
    event.location = location
    event.description = description
    event.attendees = attendees or ["alice@example.com"]
    return event


class TestCalendarContracts:
    """Verify calendar response contracts through the real app router."""

    async def test_get_events_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        mock_service = AsyncMock()
        mock_service.get_upcoming_events = AsyncMock(
            return_value=[
                _make_event(
                    start=date(2026, 3, 16),
                    end=date(2026, 3, 17),
                    attendees=["alice@example.com", "bob@example.com"],
                ),
            ],
        )
        mock_service.close = AsyncMock()

        with (
            patch("src.app.api.routes.calendar._check_google_configured"),
            patch(
                "src.app.api.routes.calendar._make_calendar_service",
                return_value=mock_service,
            ),
        ):
            response = await client.get(
                "/api/calendar/events",
                params={
                    "start": "2026-03-16T00:00:00Z",
                    "end": "2026-03-17T00:00:00Z",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "ev_123"
        assert data[0]["summary"] == "Team standup"
        assert data[0]["start"].startswith("2026-03-16")
        assert data[0]["attendees"] == ["alice@example.com", "bob@example.com"]
        mock_service.get_upcoming_events.assert_awaited_once()
        mock_service.close.assert_awaited_once()

    async def test_get_events_contract_filters_out_non_overlapping_events(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        mock_service = AsyncMock()
        mock_service.get_upcoming_events = AsyncMock(
            return_value=[
                _make_event(
                    event_id="ev_outside",
                    summary="Outside window",
                    start=datetime(2026, 3, 20, 9, 0, 0, tzinfo=UTC),
                    end=datetime(2026, 3, 20, 10, 0, 0, tzinfo=UTC),
                ),
            ],
        )
        mock_service.close = AsyncMock()

        with (
            patch("src.app.api.routes.calendar._check_google_configured"),
            patch(
                "src.app.api.routes.calendar._make_calendar_service",
                return_value=mock_service,
            ),
        ):
            response = await client.get(
                "/api/calendar/events",
                params={
                    "start": "2026-03-16T00:00:00Z",
                    "end": "2026-03-17T00:00:00Z",
                },
            )

        assert response.status_code == 200
        assert response.json() == []
        mock_service.close.assert_awaited_once()

    async def test_calendar_write_routes_are_not_exposed(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client

        responses = [
            await client.post("/api/calendar/events", json={}),
            await client.put("/api/calendar/events/ev_123", json={}),
            await client.delete("/api/calendar/events/ev_123"),
        ]

        assert all(response.status_code in {404, 405} for response in responses)

    async def test_get_free_slots_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        mock_service = AsyncMock()
        mock_service.find_free_slots = AsyncMock(
            return_value=[
                {
                    "start": datetime(2026, 3, 16, 10, 0, tzinfo=UTC),
                    "end": datetime(2026, 3, 16, 11, 0, tzinfo=UTC),
                    "duration_minutes": 60,
                },
            ],
        )
        mock_service.close = AsyncMock()

        with (
            patch("src.app.api.routes.calendar._check_google_configured"),
            patch(
                "src.app.api.routes.calendar._make_calendar_service",
                return_value=mock_service,
            ),
        ):
            response = await client.get(
                "/api/calendar/free-slots",
                params={"duration_minutes": 30, "days_ahead": 7},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["duration_minutes"] == 60
        assert data[0]["start"].startswith("2026-03-16T10:00:00")
        mock_service.find_free_slots.assert_awaited_once()
        mock_service.close.assert_awaited_once()

    async def test_calendar_routes_return_503_when_google_is_not_configured(
        self,
        integration_client,
    ):
        client, _mock_session, _mock_anthropic = integration_client
        mock_settings = MagicMock()
        mock_settings.google_configured = False

        with patch("src.app.api.routes.calendar.get_settings", return_value=mock_settings):
            response = await client.get(
                "/api/calendar/events",
                params={
                    "start": "2026-03-16T00:00:00Z",
                    "end": "2026-03-17T00:00:00Z",
                },
            )

        assert response.status_code == 503
