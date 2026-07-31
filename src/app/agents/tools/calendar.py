"""Google Calendar integration via API.

Requires GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN in env.
No fallback. Fails loudly if credentials missing or API fails.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from pydantic import BaseModel, Field

from .google_auth import GoogleOAuthClient, google_http_retry

logger = structlog.get_logger()

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


class CalendarEvent(BaseModel):
    """Represents a Google Calendar event.

    start/end can be a datetime (timed events) or a date (all-day events).
    """

    id: str
    summary: str
    start: datetime | date
    end: datetime | date
    location: str | None = None
    description: str | None = None
    attendees: list[str] = Field(default_factory=list)


def _parse_event_time(raw: str) -> datetime | date:
    """Parse a Google Calendar time string as datetime or date.

    Google returns ISO datetime for timed events (e.g. '2026-03-10T10:00:00+00:00')
    and ISO date for all-day events (e.g. '2026-03-10').
    """
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return date.fromisoformat(raw)


def _parse_event(item: dict[str, Any]) -> CalendarEvent | None:
    """Parse a raw Google Calendar API event item into a CalendarEvent.

    Returns None if the event is missing required time fields.
    """
    raw_start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
    raw_end = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
    if raw_start is None or raw_end is None:
        logger.warning("calendar_event_missing_time", event_id=item.get("id"))
        return None
    return CalendarEvent(
        id=item["id"],
        summary=item.get("summary", "Untitled"),
        start=_parse_event_time(raw_start),
        end=_parse_event_time(raw_end),
        location=item.get("location"),
        description=item.get("description"),
        attendees=[a.get("email", "") for a in item.get("attendees", [])],
    )


class CalendarService(GoogleOAuthClient):
    """Google Calendar operations. Requires OAuth2 credentials."""

    @google_http_retry
    async def list_events_between(
        self,
        start: datetime,
        end: datetime,
        max_results: int = 50,
    ) -> list[CalendarEvent]:
        """List events in a specific UTC datetime window."""
        token = await self._get_access_token()

        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)

        response = await self._http_client.get(
            f"{CALENDAR_API_BASE}/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            },
        )
        response.raise_for_status()
        data = response.json()

        events = []
        for item in data.get("items", []):
            event = _parse_event(item)
            if event is not None:
                events.append(event)

        logger.info(
            "calendar_events_listed_between",
            count=len(events),
            start=start.isoformat(),
            end=end.isoformat(),
        )
        return events

    @google_http_retry
    async def get_upcoming_events(
        self,
        days: int = 7,
        max_results: int = 20,
    ) -> list[CalendarEvent]:
        """Get upcoming calendar events within the specified number of days."""
        now = datetime.now(UTC)
        time_max = now + timedelta(days=days)
        events = await self.list_events_between(now, time_max, max_results=max_results)
        logger.info("calendar_events_fetched", count=len(events), days=days)
        return events

    @google_http_retry
    async def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
    ) -> CalendarEvent:
        """Create a new calendar event. Returns the created event."""
        token = await self._get_access_token()

        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        }
        if description is not None:
            body["description"] = description
        if location is not None:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": email} for email in attendees]

        response = await self._http_client.post(
            f"{CALENDAR_API_BASE}/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        response.raise_for_status()
        item = response.json()

        event = _parse_event(item)
        if event is None:
            msg = f"Created event missing time fields: {item.get('id')}"
            raise ValueError(msg)

        logger.info(
            "calendar_event_created",
            event_id=event.id,
            summary_length=len(summary),
            attendee_count=len(attendees or []),
        )
        return event

    @google_http_retry
    async def update_event(
        self,
        event_id: str,
        summary: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> CalendarEvent:
        """Update an existing calendar event. Only updates provided fields."""
        token = await self._get_access_token()

        body: dict[str, Any] = {}
        if summary is not None:
            body["summary"] = summary
        if start is not None:
            body["start"] = {"dateTime": start.isoformat(), "timeZone": "UTC"}
        if end is not None:
            body["end"] = {"dateTime": end.isoformat(), "timeZone": "UTC"}
        if description is not None:
            body["description"] = description
        if location is not None:
            body["location"] = location

        response = await self._http_client.patch(
            f"{CALENDAR_API_BASE}/calendars/primary/events/{event_id}",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        response.raise_for_status()
        item = response.json()

        event = _parse_event(item)
        if event is None:
            msg = f"Updated event missing time fields: {event_id}"
            raise ValueError(msg)

        logger.info("calendar_event_updated", event_id=event_id)
        return event

    @google_http_retry
    async def delete_event(self, event_id: str) -> None:
        """Delete a calendar event by ID."""
        token = await self._get_access_token()

        response = await self._http_client.delete(
            f"{CALENDAR_API_BASE}/calendars/primary/events/{event_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()

        logger.info("calendar_event_deleted", event_id=event_id)

    async def find_free_slots(
        self,
        duration_minutes: int = 60,
        days_ahead: int = 7,
        working_hours: tuple[int, int] = (9, 17),
    ) -> list[dict[str, Any]]:
        """Find free time slots in the calendar.

        Scans working hours over the next `days_ahead` days and returns gaps
        between events that are at least `duration_minutes` long.

        Returns list of {"start": datetime, "end": datetime, "duration_minutes": int}.
        """
        now = datetime.now(UTC)
        events = await self.get_upcoming_events(days=days_ahead, max_results=250)

        # Collect all busy intervals as UTC datetimes
        busy: list[tuple[datetime, datetime]] = []
        for ev in events:
            ev_start = (
                ev.start
                if isinstance(ev.start, datetime)
                else datetime.combine(ev.start, datetime.min.time(), tzinfo=UTC)
            )
            ev_end = (
                ev.end
                if isinstance(ev.end, datetime)
                else datetime.combine(ev.end, datetime.min.time(), tzinfo=UTC)
            )
            # Ensure timezone-aware
            if ev_start.tzinfo is None:
                ev_start = ev_start.replace(tzinfo=UTC)
            if ev_end.tzinfo is None:
                ev_end = ev_end.replace(tzinfo=UTC)
            busy.append((ev_start, ev_end))

        # Sort by start time
        busy.sort(key=lambda x: x[0])

        work_start_hour, work_end_hour = working_hours
        duration = timedelta(minutes=duration_minutes)
        free_slots: list[dict[str, Any]] = []

        for day_offset in range(days_ahead):
            day = now.date() + timedelta(days=day_offset)
            day_start = datetime(day.year, day.month, day.day, work_start_hour, tzinfo=UTC)
            day_end = datetime(day.year, day.month, day.day, work_end_hour, tzinfo=UTC)

            # Don't include time already past today
            if day_start < now:
                day_start = now

            # Skip if working hours already over for today
            if day_start >= day_end:
                continue

            # Get busy intervals that overlap this working day
            day_busy = [
                (max(s, day_start), min(e, day_end))
                for s, e in busy
                if s < day_end and e > day_start
            ]
            day_busy.sort(key=lambda x: x[0])

            # Walk through the day finding gaps
            cursor = day_start
            for busy_start, busy_end in day_busy:
                if busy_start > cursor:
                    gap = busy_start - cursor
                    if gap >= duration:
                        free_slots.append(
                            {
                                "start": cursor,
                                "end": busy_start,
                                "duration_minutes": int(gap.total_seconds() / 60),
                            }
                        )
                cursor = max(cursor, busy_end)

            # Check remaining time after last event
            if cursor < day_end:
                gap = day_end - cursor
                if gap >= duration:
                    free_slots.append(
                        {
                            "start": cursor,
                            "end": day_end,
                            "duration_minutes": int(gap.total_seconds() / 60),
                        }
                    )

        logger.info(
            "calendar_free_slots_found",
            count=len(free_slots),
            duration_minutes=duration_minutes,
            days_ahead=days_ahead,
        )
        return free_slots

    @google_http_retry
    async def get_events_for_date(self, target_date: date) -> list[CalendarEvent]:
        """Get all events for a specific date."""
        token = await self._get_access_token()

        day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)

        response = await self._http_client.get(
            f"{CALENDAR_API_BASE}/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "timeMin": day_start.isoformat(),
                "timeMax": day_end.isoformat(),
                "singleEvents": True,
                "orderBy": "startTime",
            },
        )
        response.raise_for_status()
        data = response.json()

        events = []
        for item in data.get("items", []):
            event = _parse_event(item)
            if event is not None:
                events.append(event)

        logger.info("calendar_events_for_date", date=str(target_date), count=len(events))
        return events
