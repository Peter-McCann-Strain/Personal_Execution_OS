"""Tests for CalendarService — Google Calendar API integration."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.app.agents.tools.calendar import (
    CalendarService,
    _parse_event,
    _parse_event_time,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api_event(
    event_id: str = "evt1",
    summary: str = "Standup",
    start_dt: str = "2026-03-10T10:00:00+00:00",
    end_dt: str = "2026-03-10T10:30:00+00:00",
    location: str | None = None,
    description: str | None = None,
    attendees: list[dict] | None = None,
) -> dict:
    """Build a raw Google Calendar API event item."""
    item: dict = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt},
    }
    if location:
        item["location"] = location
    if description:
        item["description"] = description
    if attendees:
        item["attendees"] = attendees
    return item


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def calendar_service() -> CalendarService:
    svc = CalendarService(
        client_id="fake-id",
        client_secret="fake-secret",
        refresh_token="fake-refresh",
    )
    svc._http_client = AsyncMock(spec=httpx.AsyncClient)
    # Pre-cache a valid token to avoid token refresh in every test
    svc._cached_token = "valid-access-token"
    svc._token_expiry = datetime.now(UTC) + timedelta(hours=1)
    return svc


# ---------------------------------------------------------------------------
# _parse_event_time
# ---------------------------------------------------------------------------


def test_parse_event_time_datetime():
    result = _parse_event_time("2026-03-10T10:00:00+00:00")
    assert isinstance(result, datetime)
    assert result.year == 2026
    assert result.month == 3
    assert result.day == 10


def test_parse_event_time_date():
    """In Python 3.12+, fromisoformat parses date-only as datetime at midnight."""
    result = _parse_event_time("2026-03-10")
    assert isinstance(result, date)
    # Python 3.12: datetime.fromisoformat("2026-03-10") returns datetime(2026, 3, 10, 0, 0)
    # so the function returns a datetime, not a plain date
    assert result.year == 2026
    assert result.month == 3
    assert result.day == 10


# ---------------------------------------------------------------------------
# _parse_event
# ---------------------------------------------------------------------------


def test_parse_event_timed():
    item = _make_api_event(attendees=[{"email": "alice@example.com"}])
    event = _parse_event(item)
    assert event is not None
    assert event.id == "evt1"
    assert event.summary == "Standup"
    assert isinstance(event.start, datetime)
    assert event.attendees == ["alice@example.com"]


def test_parse_event_all_day():
    item = {
        "id": "evt2",
        "summary": "Holiday",
        "start": {"date": "2026-03-10"},
        "end": {"date": "2026-03-11"},
    }
    event = _parse_event(item)
    assert event is not None
    assert isinstance(event.start, date)


def test_parse_event_missing_time_returns_none():
    item = {"id": "bad", "summary": "No times", "start": {}, "end": {}}
    assert _parse_event(item) is None


def test_parse_event_untitled():
    item = {
        "id": "evt3",
        "start": {"dateTime": "2026-03-10T10:00:00+00:00"},
        "end": {"dateTime": "2026-03-10T11:00:00+00:00"},
    }
    event = _parse_event(item)
    assert event is not None
    assert event.summary == "Untitled"


# ---------------------------------------------------------------------------
# CalendarService.get_upcoming_events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_upcoming_events(calendar_service: CalendarService):
    items = [_make_api_event("e1", "Meeting"), _make_api_event("e2", "Lunch")]
    calendar_service._http_client.get.return_value = _mock_response({"items": items})

    events = await calendar_service.get_upcoming_events(days=7, max_results=10)
    assert len(events) == 2
    assert events[0].summary == "Meeting"
    assert events[1].summary == "Lunch"
    calendar_service._http_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_get_upcoming_events_empty(calendar_service: CalendarService):
    calendar_service._http_client.get.return_value = _mock_response({"items": []})
    events = await calendar_service.get_upcoming_events()
    assert events == []


@pytest.mark.asyncio
async def test_get_upcoming_events_skips_invalid_items(calendar_service: CalendarService):
    """Invalid calendar items should be filtered out without breaking the request."""
    items = [
        {"id": "bad", "summary": "Broken", "start": {}, "end": {}},
        _make_api_event("e1", "Meeting"),
    ]
    calendar_service._http_client.get.return_value = _mock_response({"items": items})

    events = await calendar_service.get_upcoming_events(days=3, max_results=5)

    assert len(events) == 1
    assert events[0].id == "e1"


# ---------------------------------------------------------------------------
# CalendarService.create_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_event(calendar_service: CalendarService):
    now = datetime.now(UTC)
    created_item = _make_api_event(
        "new1", "New Event", now.isoformat(), (now + timedelta(hours=1)).isoformat()
    )
    calendar_service._http_client.post.return_value = _mock_response(created_item)

    event = await calendar_service.create_event(
        summary="New Event",
        start=now,
        end=now + timedelta(hours=1),
        description="A test event",
        location="Office",
        attendees=["bob@example.com"],
    )
    assert event.id == "new1"
    assert event.summary == "New Event"
    calendar_service._http_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_create_event_minimal_body(calendar_service: CalendarService):
    """When optional fields are omitted, the request body should stay minimal."""
    now = datetime.now(UTC)
    created_item = _make_api_event(
        "new2", "Minimal Event", now.isoformat(), (now + timedelta(hours=1)).isoformat()
    )
    calendar_service._http_client.post.return_value = _mock_response(created_item)

    await calendar_service.create_event(
        summary="Minimal Event",
        start=now,
        end=now + timedelta(hours=1),
    )

    request_body = calendar_service._http_client.post.call_args.kwargs["json"]
    assert request_body == {
        "summary": "Minimal Event",
        "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
    }


@pytest.mark.asyncio
async def test_create_event_missing_time_raises(calendar_service: CalendarService):
    calendar_service._http_client.post.return_value = _mock_response(
        {"id": "bad", "start": {}, "end": {}}
    )
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="Created event missing time fields"):
        await calendar_service.create_event("Bad", now, now + timedelta(hours=1))


# ---------------------------------------------------------------------------
# CalendarService.update_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_event(calendar_service: CalendarService):
    updated_item = _make_api_event("evt1", "Updated Title")
    calendar_service._http_client.patch.return_value = _mock_response(updated_item)

    event = await calendar_service.update_event(event_id="evt1", summary="Updated Title")
    assert event.summary == "Updated Title"
    calendar_service._http_client.patch.assert_called_once()


@pytest.mark.asyncio
async def test_update_event_without_summary(calendar_service: CalendarService):
    """When summary is omitted, it should not be included in the payload."""
    now = datetime.now(UTC)
    updated_item = _make_api_event(
        "evt2",
        "Untouched Title",
        now.isoformat(),
        (now + timedelta(hours=1)).isoformat(),
    )
    calendar_service._http_client.patch.return_value = _mock_response(updated_item)

    await calendar_service.update_event(
        event_id="evt2",
        start=now,
        end=now + timedelta(hours=1),
    )

    request_body = calendar_service._http_client.patch.call_args.kwargs["json"]
    assert "summary" not in request_body
    assert request_body["start"] == {"dateTime": now.isoformat(), "timeZone": "UTC"}
    assert request_body["end"] == {
        "dateTime": (now + timedelta(hours=1)).isoformat(),
        "timeZone": "UTC",
    }


@pytest.mark.asyncio
async def test_update_event_with_all_optional_fields(calendar_service: CalendarService):
    """Updating with all optional fields should include each field in the payload."""
    now = datetime.now(UTC)
    updated_item = _make_api_event(
        "evt1",
        "Updated Title",
        now.isoformat(),
        (now + timedelta(hours=1)).isoformat(),
    )
    calendar_service._http_client.patch.return_value = _mock_response(updated_item)

    await calendar_service.update_event(
        event_id="evt1",
        summary="Updated Title",
        start=now,
        end=now + timedelta(hours=1),
        description="Updated description",
        location="New Office",
    )

    request_body = calendar_service._http_client.patch.call_args.kwargs["json"]
    assert request_body == {
        "summary": "Updated Title",
        "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
        "description": "Updated description",
        "location": "New Office",
    }


@pytest.mark.asyncio
async def test_update_event_missing_time_raises(calendar_service: CalendarService):
    calendar_service._http_client.patch.return_value = _mock_response(
        {"id": "evt1", "start": {}, "end": {}}
    )
    with pytest.raises(ValueError, match="Updated event missing time fields"):
        await calendar_service.update_event(event_id="evt1", summary="x")


# ---------------------------------------------------------------------------
# CalendarService.delete_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_event(calendar_service: CalendarService):
    calendar_service._http_client.delete.return_value = _mock_response({}, 204)
    await calendar_service.delete_event("evt1")
    calendar_service._http_client.delete.assert_called_once()


# ---------------------------------------------------------------------------
# CalendarService.find_free_slots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_free_slots_no_events(calendar_service: CalendarService):
    """No events means the whole working day is free."""
    calendar_service._http_client.get.return_value = _mock_response({"items": []})

    slots = await calendar_service.find_free_slots(
        duration_minutes=60,
        days_ahead=1,
        working_hours=(9, 17),
    )
    # Should have at least 1 free slot (the whole day or remainder of today)
    assert isinstance(slots, list)


@pytest.mark.asyncio
async def test_find_free_slots_with_events(calendar_service: CalendarService):
    """Events split the day into multiple free slots."""
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    event_start = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 12, 0, tzinfo=UTC)
    event_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 13, 0, tzinfo=UTC)

    items = [_make_api_event("e1", "Lunch", event_start.isoformat(), event_end.isoformat())]
    calendar_service._http_client.get.return_value = _mock_response({"items": items})

    slots = await calendar_service.find_free_slots(
        duration_minutes=60,
        days_ahead=2,
        working_hours=(9, 17),
    )
    # Should find free slots before and after the event
    assert isinstance(slots, list)
    assert len(slots) >= 1


@pytest.mark.asyncio
async def test_find_free_slots_handles_naive_busy_times_and_short_gaps(
    calendar_service: CalendarService,
):
    """Naive event times should be normalized to UTC and short gaps ignored."""
    fixed_now = datetime(2026, 4, 8, 0, 0, 0, tzinfo=UTC)
    first_start = datetime(2026, 4, 8, 9, 0)
    first_end = datetime(2026, 4, 8, 16, 30)
    second_start = datetime(2026, 4, 8, 16, 45)
    second_end = datetime(2026, 4, 8, 16, 50)

    items = [
        _make_api_event("e1", "Early", first_start.isoformat(), first_end.isoformat()),
        _make_api_event("e2", "Later", second_start.isoformat(), second_end.isoformat()),
    ]
    calendar_service._http_client.get.return_value = _mock_response({"items": items})

    from unittest.mock import patch

    class _MockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    with patch("src.app.agents.tools.calendar.datetime", _MockDatetime):
        _MockDatetime.combine = datetime.combine
        _MockDatetime.min = datetime.min

        slots = await calendar_service.find_free_slots(
            duration_minutes=60,
            days_ahead=1,
            working_hours=(9, 17),
        )

    assert slots == []


@pytest.mark.asyncio
async def test_find_free_slots_event_reaches_day_end(calendar_service: CalendarService):
    """An event that runs until closing time should skip the trailing gap branch."""
    fixed_now = datetime(2026, 4, 8, 0, 0, 0, tzinfo=UTC)
    day_start = datetime(2026, 4, 8, 9, 0)
    day_end = datetime(2026, 4, 8, 17, 0)

    calendar_service._http_client.get.return_value = _mock_response(
        {"items": [_make_api_event("full", "Full Day", day_start.isoformat(), day_end.isoformat())]}
    )

    from unittest.mock import patch

    class _MockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    with patch("src.app.agents.tools.calendar.datetime", _MockDatetime):
        slots = await calendar_service.find_free_slots(
            duration_minutes=60,
            days_ahead=1,
            working_hours=(9, 17),
        )

    assert slots == []


# ---------------------------------------------------------------------------
# CalendarService.get_events_for_date
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_events_for_date(calendar_service: CalendarService):
    items = [_make_api_event("d1", "Day Event")]
    calendar_service._http_client.get.return_value = _mock_response({"items": items})

    events = await calendar_service.get_events_for_date(date(2026, 3, 10))
    assert len(events) == 1
    assert events[0].summary == "Day Event"


@pytest.mark.asyncio
async def test_get_events_for_date_skips_invalid_items(calendar_service: CalendarService):
    """A malformed event should be skipped while valid events still return."""
    items = [
        {"id": "bad", "summary": "Broken", "start": {}, "end": {}},
        _make_api_event("good", "Good Event"),
    ]
    calendar_service._http_client.get.return_value = _mock_response({"items": items})

    events = await calendar_service.get_events_for_date(date(2026, 3, 10))

    assert len(events) == 1
    assert events[0].id == "good"


# ---------------------------------------------------------------------------
# Token refresh flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_refresh_when_expired(calendar_service: CalendarService):
    """When cached token is expired, service refreshes before making API call."""
    # Expire the token
    calendar_service._cached_token = None
    calendar_service._token_expiry = None

    # Token refresh response
    token_resp = _mock_response({"access_token": "new-token", "expires_in": 3600})
    # Calendar API response
    api_resp = _mock_response({"items": []})

    calendar_service._http_client.post.return_value = token_resp
    calendar_service._http_client.get.return_value = api_resp

    events = await calendar_service.get_upcoming_events()
    assert events == []
    # Token refresh should have been called via post
    calendar_service._http_client.post.assert_called_once()
    assert calendar_service._cached_token == "new-token"


@pytest.mark.asyncio
async def test_token_cached_not_refreshed(calendar_service: CalendarService):
    """When token is still valid, no refresh call is made."""
    calendar_service._http_client.get.return_value = _mock_response({"items": []})

    await calendar_service.get_upcoming_events()
    # No post call should be made (token refresh uses post)
    calendar_service._http_client.post.assert_not_called()


# ---------------------------------------------------------------------------
# _parse_event_time — ValueError fallback to date.fromisoformat
# ---------------------------------------------------------------------------


def test_parse_event_time_datetime_fromisoformat_fails_falls_back_to_date():
    """Cover lines 43-44: datetime.fromisoformat raises ValueError, fallback to date.

    In Python 3.12+ datetime.fromisoformat accepts date-only strings, so we
    patch the datetime class at the calendar module level to force a ValueError
    on date-only strings, exercising the except branch.
    """
    from unittest.mock import patch

    original_fromisoformat = datetime.fromisoformat

    class _MockDatetime(datetime):
        """datetime subclass whose fromisoformat raises on date-only strings."""

        @classmethod
        def fromisoformat(cls, date_string: str):
            # Simulate pre-3.12: date-only string raises ValueError
            if "T" not in date_string and len(date_string) == 10:
                raise ValueError("mocked: no time component")
            return original_fromisoformat(date_string)

    with patch("src.app.agents.tools.calendar.datetime", _MockDatetime):
        result = _parse_event_time("2026-03-10")

    assert isinstance(result, date)
    assert not isinstance(result, datetime)  # plain date, not datetime subclass
    assert result == date(2026, 3, 10)


# ---------------------------------------------------------------------------
# CalendarService.find_free_slots — day_start < now (line 250)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_free_slots_today_midday_adjusts_start(calendar_service: CalendarService):
    """Cover line 250: when now is mid-day, day_start is adjusted to now.

    Mock datetime.now(UTC) to return a mid-day time (e.g. 12:00) so that
    the 09:00 work start is already past and day_start gets bumped to now.
    """
    from unittest.mock import patch

    # Fix "now" to 12:00 UTC on a specific day
    fixed_now = datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC)

    # No events — the entire remaining afternoon should be free
    calendar_service._http_client.get.return_value = _mock_response({"items": []})

    with patch("src.app.agents.tools.calendar.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        mock_dt.min = datetime.min
        mock_dt.combine = datetime.combine
        mock_dt.fromisoformat = datetime.fromisoformat

        slots = await calendar_service.find_free_slots(
            duration_minutes=60,
            days_ahead=1,
            working_hours=(9, 17),
        )

    # Should get one slot: from 12:00 to 17:00 (5 hours)
    assert len(slots) == 1
    assert slots[0]["start"] == fixed_now
    assert slots[0]["end"] == datetime(2026, 3, 17, 17, 0, 0, tzinfo=UTC)
    assert slots[0]["duration_minutes"] == 300


# ---------------------------------------------------------------------------
# CalendarService.find_free_slots — day_start >= day_end (line 253-254)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_free_slots_past_working_hours_skips_day(calendar_service: CalendarService):
    """Cover lines 253-254: when now is past work_end_hour, the day is skipped.

    Mock datetime.now(UTC) to 18:00 so that for today, after adjusting
    day_start to now (18:00), it is >= day_end (17:00), and the day is skipped.
    """
    from unittest.mock import patch

    # Fix "now" to 18:00 UTC — past the default 17:00 work end
    fixed_now = datetime(2026, 3, 17, 18, 0, 0, tzinfo=UTC)

    calendar_service._http_client.get.return_value = _mock_response({"items": []})

    with patch("src.app.agents.tools.calendar.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        mock_dt.min = datetime.min
        mock_dt.combine = datetime.combine
        mock_dt.fromisoformat = datetime.fromisoformat

        slots = await calendar_service.find_free_slots(
            duration_minutes=60,
            days_ahead=1,  # Only look at today
            working_hours=(9, 17),
        )

    # Today is past working hours, and days_ahead=1 means only today → no slots
    assert slots == []
