"""Read-only Google Calendar API surface tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import Principal, get_current_principal
from src.app.api.routes.calendar import router


def _build_app() -> FastAPI:
    app = FastAPI()

    async def principal() -> Principal:
        return Principal(
            subject="owner",
            external_subject=None,
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
            account_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            role="owner",
            plan="community",
            scopes=("account:owner",),
            auth_method="api_key",
        )

    app.dependency_overrides[get_current_principal] = principal
    app.include_router(router, prefix="/api")
    return app


async def test_events_are_filtered_to_requested_range() -> None:
    event = MagicMock(
        id="event",
        summary="Planning",
        start=datetime(2026, 3, 16, 9, tzinfo=UTC),
        end=datetime(2026, 3, 16, 10, tzinfo=UTC),
        location=None,
        description=None,
        attendees=[],
    )
    service = AsyncMock()
    service.get_upcoming_events.return_value = [event]
    app = _build_app()

    with (
        patch("src.app.api.routes.calendar._check_google_configured"),
        patch("src.app.api.routes.calendar._make_calendar_service", return_value=service),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/calendar/events",
                params={
                    "start": "2026-03-16T00:00:00Z",
                    "end": "2026-03-17T00:00:00Z",
                },
            )

    assert response.status_code == 200
    assert response.json()[0]["id"] == "event"
    service.close.assert_awaited_once()


async def test_free_slots_are_read_only() -> None:
    service = AsyncMock()
    service.find_free_slots.return_value = [
        {
            "start": datetime(2026, 3, 16, 10, tzinfo=UTC),
            "end": datetime(2026, 3, 16, 11, tzinfo=UTC),
            "duration_minutes": 60,
        }
    ]
    app = _build_app()

    with (
        patch("src.app.api.routes.calendar._check_google_configured"),
        patch("src.app.api.routes.calendar._make_calendar_service", return_value=service),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/calendar/free-slots",
                params={"duration_minutes": 30},
            )

    assert response.status_code == 200
    assert response.json()[0]["duration_minutes"] == 60


async def test_google_not_configured_returns_503() -> None:
    settings = MagicMock(google_configured=False)
    app = _build_app()

    with patch("src.app.api.routes.calendar.get_settings", return_value=settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/calendar/events",
                params={
                    "start": "2026-03-16T00:00:00Z",
                    "end": "2026-03-17T00:00:00Z",
                },
            )

    assert response.status_code == 503


def test_only_get_routes_are_public() -> None:
    methods = {method for route in router.routes for method in getattr(route, "methods", set())}

    assert methods == {"GET"}
