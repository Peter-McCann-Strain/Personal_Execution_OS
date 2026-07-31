"""Calendar API routes — delegates to CalendarService (Google Calendar)."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.app.api.deps import get_current_principal
from src.app.config import get_settings

logger = structlog.get_logger()

router = APIRouter(
    prefix="/calendar",
    tags=["calendar"],
    dependencies=[Depends(get_current_principal)],
)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class CalendarEventDTO(BaseModel):
    """Calendar event returned to the frontend — all datetimes as ISO strings."""

    id: str
    summary: str
    start: str
    end: str
    location: str | None = None
    description: str | None = None
    attendees: list[str] = []


class FreeSlotDTO(BaseModel):
    start: str
    end: str
    duration_minutes: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_google_configured() -> None:
    """Raise 503 using route-local settings resolution.

    Tests patch ``src.app.api.routes.calendar.get_settings`` directly, so this
    wrapper must resolve configuration from the route module rather than the
    shared utility module.
    """
    settings = get_settings()
    if not settings.google_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "Google is not configured. "
                "Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REFRESH_TOKEN."
            ),
        )


def _make_calendar_service():
    """Create a CalendarService from current settings."""
    from src.app.agents.tools.calendar import CalendarService

    settings = get_settings()
    return CalendarService(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        refresh_token=settings.google_refresh_token.get_secret_value(),
    )


def _translate_calendar_error(exc: BaseException):
    """Convert raw Google failures into connector errors handled by middleware."""
    from src.app.agents.tools.google_auth import translate_google_error

    return translate_google_error(exc, connector="calendar")


def _event_to_dto(event) -> CalendarEventDTO:
    """Convert a CalendarEvent to a CalendarEventDTO with ISO string datetimes."""
    start = event.start
    end = event.end
    # date objects need to be converted to ISO string; datetimes use .isoformat()
    start_str = start.isoformat() if hasattr(start, "isoformat") else str(start)
    end_str = end.isoformat() if hasattr(end, "isoformat") else str(end)
    return CalendarEventDTO(
        id=event.id,
        summary=event.summary,
        start=start_str,
        end=end_str,
        location=event.location,
        description=event.description,
        attendees=event.attendees,
    )


def _ensure_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/events", response_model=list[CalendarEventDTO])
async def get_events(
    start: datetime = Query(..., description="Start of date range (ISO 8601)"),
    end: datetime = Query(..., description="End of date range (ISO 8601)"),
) -> list[CalendarEventDTO]:
    """Get calendar events within a date range."""
    _check_google_configured()

    range_start = _ensure_aware_utc(start)
    range_end = _ensure_aware_utc(end)

    # Calculate days between now and range_end to fetch enough events
    now = datetime.now(UTC)
    days_ahead = max(1, (range_end - now).days + 1)

    service = _make_calendar_service()
    try:
        try:
            events = await service.get_upcoming_events(days=days_ahead, max_results=250)
        except Exception as exc:
            raise _translate_calendar_error(exc) from exc
    finally:
        await service.close()

    # Filter to the requested date range
    filtered = []
    for ev in events:
        ev_start = ev.start
        ev_end = ev.end
        # Normalise date objects to datetime for comparison
        if not isinstance(ev_start, datetime):
            ev_start = datetime.combine(ev_start, datetime.min.time(), tzinfo=UTC)
        elif ev_start.tzinfo is None:
            ev_start = ev_start.replace(tzinfo=UTC)
        if not isinstance(ev_end, datetime):
            ev_end = datetime.combine(ev_end, datetime.min.time(), tzinfo=UTC)
        elif ev_end.tzinfo is None:
            ev_end = ev_end.replace(tzinfo=UTC)

        # Include events that overlap the range
        if ev_start < range_end and ev_end > range_start:
            filtered.append(_event_to_dto(ev))

    logger.info("calendar_events_returned", count=len(filtered))
    return filtered


@router.get("/free-slots", response_model=list[FreeSlotDTO])
async def get_free_slots(
    duration_minutes: int = Query(..., gt=0, description="Minimum slot duration in minutes"),
    start_hour: int = Query(9, ge=0, le=23, description="Working day start hour (UTC)"),
    end_hour: int = Query(17, ge=0, le=23, description="Working day end hour (UTC)"),
    days_ahead: int = Query(7, ge=1, le=30, description="Number of days to search"),
) -> list[FreeSlotDTO]:
    """Find free time slots in the calendar."""
    _check_google_configured()

    service = _make_calendar_service()
    try:
        try:
            slots = await service.find_free_slots(
                duration_minutes=duration_minutes,
                days_ahead=days_ahead,
                working_hours=(start_hour, end_hour),
            )
        except Exception as exc:
            raise _translate_calendar_error(exc) from exc
    finally:
        await service.close()

    result = [
        FreeSlotDTO(
            start=slot["start"].isoformat(),
            end=slot["end"].isoformat(),
            duration_minutes=slot["duration_minutes"],
        )
        for slot in slots
    ]

    logger.info("calendar_free_slots_returned", count=len(result))
    return result
