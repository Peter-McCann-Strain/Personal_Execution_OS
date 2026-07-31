"""Settings and integration diagnostics endpoints."""

from __future__ import annotations

from typing import Any, NoReturn

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from src.app.api.deps import get_current_principal
from src.app.config import get_settings
from src.app.core.integration_probes import (
    probe_gmail,
    probe_google_calendar,
    probe_tavily,
)

router = APIRouter(dependencies=[Depends(get_current_principal)])


def _success(message: str) -> dict[str, str]:
    return {"status": "ok", "message": message}


def _raise_unavailable(message: str, *, status_code: int = 503) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=message)


async def _probe_direct_integration(probe: Any, *, label: str) -> dict[str, str]:
    try:
        await probe()
    except Exception as exc:
        _raise_unavailable(f"{label} connection failed ({type(exc).__name__})")
    return _success(f"{label} connection successful")


@router.post("/settings/integrations/{integration_key}/test")
async def test_integration(integration_key: str, request: Request) -> dict[str, str]:
    """Probe one configured integration and return a compact result."""
    settings = get_settings()
    key = integration_key.strip().lower()

    if key == "anthropic":
        if settings.anthropic_api_key.get_secret_value().strip():
            return _success("Anthropic API key configured")
        _raise_unavailable("Anthropic API key missing")

    if key == "google_calendar":
        if not settings.google_configured:
            _raise_unavailable("Google Calendar is not configured")
        return await _probe_direct_integration(
            lambda: probe_google_calendar(settings),
            label="Google Calendar",
        )

    if key == "gmail":
        if not settings.google_configured:
            _raise_unavailable("Gmail is not configured")
        return await _probe_direct_integration(lambda: probe_gmail(settings), label="Gmail")

    if key == "tavily":
        if not settings.tavily_configured:
            _raise_unavailable("Tavily is not configured")
        return await _probe_direct_integration(lambda: probe_tavily(settings), label="Tavily")

    if key == "ollama":
        if not settings.ollama_host.strip():
            _raise_unavailable("Ollama is not configured")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{settings.ollama_host}/api/tags")
        except Exception as exc:
            _raise_unavailable(f"Ollama is unreachable: {exc}")
        if response.status_code != 200:
            _raise_unavailable(f"Ollama returned HTTP {response.status_code}")
        return _success("Ollama connection successful")

    if key == "posthog":
        telemetry = getattr(request.app.state, "telemetry", None)
        posthog_status: dict[str, Any] = getattr(telemetry, "status", {})
        if not settings.posthog_configured:
            _raise_unavailable("PostHog is not configured")
        if posthog_status.get("posthog"):
            return _success("PostHog telemetry enabled")
        _raise_unavailable("PostHog is configured but the telemetry bridge is unavailable")

    if key == "sentry":
        telemetry = getattr(request.app.state, "telemetry", None)
        sentry_status: dict[str, Any] = getattr(telemetry, "status", {})
        if not settings.sentry_configured:
            _raise_unavailable("Sentry is not configured")
        if sentry_status.get("sentry"):
            return _success("Sentry telemetry enabled")
        _raise_unavailable("Sentry is configured but the telemetry bridge is unavailable")

    if key == "telegram":
        _raise_unavailable("Telegram is an internal operator channel", status_code=404)

    _raise_unavailable(f"Unknown integration '{integration_key}'", status_code=404)
