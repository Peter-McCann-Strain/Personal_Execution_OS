"""Side-effect-free connectivity probes for optional direct integrations."""

from __future__ import annotations

import httpx

from src.app.agents.tools.calendar import CALENDAR_API_BASE, CalendarService
from src.app.agents.tools.email import GMAIL_API_BASE, GmailService
from src.app.config import Settings


def _google_credentials(settings: Settings) -> tuple[str, str, str]:
    return (
        settings.google_client_id,
        settings.google_client_secret.get_secret_value(),
        settings.google_refresh_token.get_secret_value(),
    )


async def probe_google_calendar(settings: Settings) -> None:
    """Verify the Calendar credential and read-only API without reading events."""
    service = CalendarService(*_google_credentials(settings))
    try:
        token = await service._get_access_token()
        response = await service._http_client.get(
            f"{CALENDAR_API_BASE}/calendars/primary",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
    finally:
        await service.close()


async def probe_gmail(settings: Settings) -> None:
    """Verify the Gmail credential via the metadata-only profile endpoint."""
    service = GmailService(*_google_credentials(settings))
    try:
        token = await service._get_access_token()
        response = await service._http_client.get(
            f"{GMAIL_API_BASE}/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
    finally:
        await service.close()


async def probe_tavily(settings: Settings) -> None:
    """Verify a Tavily key through the non-billable usage endpoint."""
    api_key = settings.tavily_api_key.get_secret_value()
    async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
        response = await client.get(
            "https://api.tavily.com/usage",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
