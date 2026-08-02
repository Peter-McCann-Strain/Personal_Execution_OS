"""Native Google Calendar MCP server backed by the in-repo calendar client."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from src.app.agents.tools.calendar import CalendarService
from src.app.agents.tools.google_mcp_env import load_google_mcp_env
from src.app.agents.tools.mcp_subprocess_logging import configure_mcp_subprocess_logging

configure_mcp_subprocess_logging()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _service_from_env() -> CalendarService:
    creds = load_google_mcp_env()
    return CalendarService(
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        refresh_token=creds.refresh_token,
    )


@dataclass
class CalendarContext:
    service: CalendarService


@asynccontextmanager
async def calendar_lifespan(
    _server: MCPServer[CalendarContext],
) -> AsyncIterator[CalendarContext]:
    service = _service_from_env()
    try:
        yield CalendarContext(service=service)
    finally:
        await service.close()


mcp: MCPServer[CalendarContext] = MCPServer(
    "Google Calendar",
    lifespan=calendar_lifespan,
)


def _get_service(ctx: Context[CalendarContext]) -> CalendarService:
    return ctx.request_context.lifespan_context.service


@mcp.tool()
async def list_events(
    ctx: Context[CalendarContext],
    start_time: str | None = None,
    end_time: str | None = None,
    days: int = 7,
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """List calendar events in a time window.

    If no explicit range is provided, lists upcoming events over the next ``days``.
    Datetime inputs should be ISO 8601.
    """
    service = _get_service(ctx)
    if start_time and end_time:
        events = await service.list_events_between(
            _parse_datetime(start_time),
            _parse_datetime(end_time),
            max_results=max_results,
        )
    else:
        events = await service.get_upcoming_events(days=days, max_results=max_results)
    return [event.model_dump(mode="json") for event in events]


async def create_event(
    ctx: Context[CalendarContext],
    title: str,
    start_time: str,
    end_time: str,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    """Create a calendar event from ISO 8601 datetimes."""
    event = await _get_service(ctx).create_event(
        summary=title,
        start=_parse_datetime(start_time),
        end=_parse_datetime(end_time),
        description=description,
        location=location,
        attendees=attendees,
    )
    return event.model_dump(mode="json")


async def update_event(
    ctx: Context[CalendarContext],
    event_id: str,
    title: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    description: str | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    """Update selected fields on a calendar event."""
    event = await _get_service(ctx).update_event(
        event_id=event_id,
        summary=title,
        start=_parse_datetime(start_time) if start_time else None,
        end=_parse_datetime(end_time) if end_time else None,
        description=description,
        location=location,
    )
    return event.model_dump(mode="json")


async def delete_event(ctx: Context[CalendarContext], event_id: str) -> dict[str, bool]:
    """Delete a calendar event by ID."""
    await _get_service(ctx).delete_event(event_id)
    return {"success": True}


@mcp.tool()
async def find_free_slots(
    ctx: Context[CalendarContext],
    duration_minutes: int = 60,
    days_ahead: int = 7,
    workday_start_hour: int = 9,
    workday_end_hour: int = 17,
) -> list[dict[str, Any]]:
    """Find free slots over the next few working days."""
    return await _get_service(ctx).find_free_slots(
        duration_minutes=duration_minutes,
        days_ahead=days_ahead,
        working_hours=(workday_start_hour, workday_end_hour),
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
