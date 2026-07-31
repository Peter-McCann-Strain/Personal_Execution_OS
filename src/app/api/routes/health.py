"""Health check endpoint — checks all critical services."""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_db
from src.app.config import get_settings
from src.app.core.integration_probes import (
    probe_gmail,
    probe_google_calendar,
    probe_tavily,
)
from src.app.core.preflight import PreflightReport, run_startup_preflight

logger = structlog.get_logger()
router = APIRouter()
_TELEGRAM_PENDING_WARNING_THRESHOLD = 10
_TELEGRAM_RECENT_ERROR_WINDOW_SECONDS = 3600

# Simple cache: (timestamp, result)
_cache: tuple[float, dict[str, Any]] | None = None
_CACHE_TTL_SECONDS = 10.0


def _service_status(status: str, message: str, **details: Any) -> dict[str, Any]:
    """Build a consistent service status payload for API clients."""
    return {"status": status, "message": message, **details}


async def _check_database(session: AsyncSession) -> dict[str, Any]:
    """Check PostgreSQL connectivity."""
    start = time.monotonic()
    try:
        await session.execute(text("SELECT 1"))
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return _service_status("ok", "Database reachable", latency_ms=latency_ms)
    except Exception:
        logger.exception("health_check_db_failed")
        return _service_status("down", "Database unreachable")


async def _check_redis() -> dict[str, Any]:
    """Check Redis connectivity via PING."""
    start = time.monotonic()
    try:
        import redis.asyncio as aioredis

        settings = get_settings()
        r = aioredis.from_url(settings.redis_url.get_secret_value(), socket_connect_timeout=3)
        try:
            pong = await r.ping()
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            if pong:
                return _service_status("ok", "Redis reachable", latency_ms=latency_ms)
            return _service_status("down", "Redis ping failed")
        finally:
            await r.aclose()
    except ImportError:
        return _service_status("unknown", "redis package not installed")
    except Exception:
        logger.exception("health_check_redis_failed")
        return _service_status("down", "Redis unreachable")


async def _check_ollama() -> dict[str, Any]:
    """Check Ollama connectivity by hitting /api/tags."""
    start = time.monotonic()
    try:
        import httpx

        settings = get_settings()
        if not settings.ollama_host.strip():
            return _service_status("unknown", "Ollama is not configured")
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_host}/api/tags")
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            if resp.status_code == 200:
                return _service_status("ok", "Ollama reachable", latency_ms=latency_ms)
            return _service_status(
                "down",
                f"Ollama returned HTTP {resp.status_code}",
            )
    except ImportError:
        return _service_status("unknown", "httpx package not installed")
    except Exception:
        logger.exception("health_check_ollama_failed")
        return _service_status("down", "Ollama unreachable")


def _check_llm_provider(request: Request) -> dict[str, Any]:
    """Report provider capability without making a billable model call."""
    try:
        provider = getattr(request.app.state, "llm_provider", None)
        if provider is not None and bool(getattr(provider, "configured", False)):
            return _service_status(
                "ok",
                "Configured; live provider probe skipped to avoid billable traffic",
                provider=getattr(provider, "name", "unknown"),
            )
        return _service_status("unknown", "No model provider configured", provider="disabled")
    except Exception:
        logger.exception("health_check_llm_provider_failed")
        return _service_status("unknown", "Model provider status unavailable")


def _check_anthropic(request: Request | None = None) -> dict[str, Any]:
    """Compatibility seam around the provider-neutral health check.

    The request-aware path is the live runtime path. The no-argument branch is
    retained for older operator probes and never makes a billable API request.
    """
    if request is not None:
        return _check_llm_provider(request)
    try:
        key = get_settings().anthropic_api_key.get_secret_value().strip()
        if key and not key.startswith("PLACEHOLDER"):
            return _service_status(
                "ok",
                "Configured; live provider probe skipped to avoid billable traffic",
                provider="anthropic",
            )
        return _service_status("down", "Anthropic is not configured", provider="anthropic")
    except Exception:
        logger.exception("health_check_anthropic_config_failed")
        return _service_status("down", "Anthropic configuration unavailable")


async def _check_direct_integration(
    probe: Any,
    *,
    configured: bool,
    label: str,
) -> dict[str, Any]:
    """Probe a configured direct integration without MCP or billable calls."""
    if not configured:
        return _service_status("unknown", f"{label} not configured")

    start = time.monotonic()
    try:
        await probe()
    except Exception:
        logger.exception("health_check_direct_integration_failed", integration=label)
        return _service_status("down", f"{label} connection failed")
    latency_ms = round((time.monotonic() - start) * 1000, 1)
    return _service_status("ok", f"{label} reachable", latency_ms=latency_ms)


def _check_telemetry_integration(
    request: Request,
    *,
    configured: bool,
    key: str,
    label: str,
) -> dict[str, Any]:
    """Check whether a configured telemetry sink is active."""
    if not configured:
        return _service_status("unknown", f"{label} not configured")

    telemetry = getattr(request.app.state, "telemetry", None)
    status = getattr(telemetry, "status", {}) if telemetry is not None else {}
    if status.get(key):
        return _service_status("ok", f"{label} telemetry enabled")
    return _service_status("down", f"{label} configured but telemetry bridge unavailable")


async def _check_telegram_webhook(request: Request) -> dict[str, Any]:
    """Check current Telegram webhook state when a bot is configured."""
    telegram_service = getattr(request.app.state, "telegram_service", None)
    if telegram_service is None:
        return _service_status("unknown", "Telegram not configured")

    try:
        info = await telegram_service.get_webhook_status()
    except Exception:
        logger.exception("health_check_telegram_failed")
        return _service_status("down", "Telegram webhook status unavailable")

    pending_update_count = info.get("pending_update_count")
    if isinstance(pending_update_count, bool):
        pending_update_count = int(pending_update_count)
    if not isinstance(pending_update_count, int):
        pending_update_count = 0

    status = "ok"
    if pending_update_count >= _TELEGRAM_PENDING_WARNING_THRESHOLD:
        status = "degraded"
    elif pending_update_count > 0:
        status = "lagging"

    last_error_date = info.get("last_error_date")
    if isinstance(last_error_date, bool):
        last_error_date = int(last_error_date)
    if not isinstance(last_error_date, int):
        last_error_date = None

    last_error_age_seconds: int | None = None
    if last_error_date is not None:
        now_timestamp = int(datetime.now(UTC).timestamp())
        last_error_age_seconds = max(now_timestamp - last_error_date, 0)

    has_recent_error = bool(info.get("last_error_message")) and (
        last_error_age_seconds is None
        or last_error_age_seconds <= _TELEGRAM_RECENT_ERROR_WINDOW_SECONDS
    )
    if has_recent_error:
        status = "degraded"

    message = "Telegram webhook healthy"
    if status == "lagging":
        message = "Telegram webhook has pending updates"
    elif status == "degraded":
        if has_recent_error:
            message = "Telegram webhook has a recent delivery error"
        else:
            message = "Telegram webhook backlog exceeds the warning threshold"

    return _service_status(
        status,
        message,
        pending_update_count=pending_update_count,
        last_error_message=info.get("last_error_message"),
        last_error_date=last_error_date,
        last_error_age_seconds=last_error_age_seconds,
        webhook_lagging=pending_update_count > 0,
        pending_updates_warning_threshold=_TELEGRAM_PENDING_WARNING_THRESHOLD,
        url=info.get("url"),
    )


@router.get("/health")
async def health_check(request: Request, session: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Check application health — verifies all critical services."""
    global _cache

    # Return cached result if fresh
    now = time.monotonic()
    if _cache is not None:
        cached_time, cached_result = _cache
        if now - cached_time < _CACHE_TTL_SECONDS:
            return JSONResponse(
                content=cached_result,
                status_code=200 if cached_result["status"] != "down" else 503,
            )

    settings = get_settings()

    (
        db_result,
        redis_result,
        ollama_result,
        telegram_result,
        google_calendar_result,
        gmail_result,
        tavily_result,
    ) = await asyncio.gather(
        _check_database(session),
        _check_redis(),
        _check_ollama(),
        _check_telegram_webhook(request),
        _check_direct_integration(
            lambda: probe_google_calendar(settings),
            configured=bool(settings.google_configured),
            label="Google Calendar",
        ),
        _check_direct_integration(
            lambda: probe_gmail(settings),
            configured=bool(settings.google_configured),
            label="Gmail",
        ),
        _check_direct_integration(
            lambda: probe_tavily(settings),
            configured=bool(settings.tavily_configured),
            label="Tavily",
        ),
    )

    llm_result = _check_anthropic(request)
    sentry_result = _check_telemetry_integration(
        request,
        configured=bool(settings.sentry_configured),
        key="sentry",
        label="Sentry",
    )
    posthog_result = _check_telemetry_integration(
        request,
        configured=bool(settings.posthog_configured),
        key="posthog",
        label="PostHog",
    )

    services = {
        "database": db_result,
        "redis": redis_result,
        "ollama": ollama_result,
        "llm": llm_result,
        "google_calendar": google_calendar_result,
        "gmail": gmail_result,
        "tavily": tavily_result,
        "posthog": posthog_result,
        "sentry": sentry_result,
        "telegram": telegram_result,
    }

    # Determine overall status
    # database down = "down" (critical dependency)
    # any other service down = "degraded"
    # all ok/unknown = "ok"
    if db_result["status"] == "down":
        overall = "down"
    elif any(
        s["status"] in {"down", "degraded", "lagging"}
        for name, s in services.items()
        if name not in {"database", "llm"}
    ):
        overall = "degraded"
    else:
        overall = "ok"

    result = {
        "status": overall,
        "services": services,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # Cache the result
    _cache = (now, result)

    status_code = 200 if overall != "down" else 503
    return JSONResponse(content=result, status_code=status_code)


@router.get("/healthz")
async def liveness() -> JSONResponse:
    """Liveness probe — returns 200 whenever the process is alive.

    Intentionally does NOT touch the database, Redis, Ollama, or any
    external dependency. Orchestrators and reverse proxies use this to decide
    whether the container needs to be restarted; if the process can
    answer HTTP at all it is considered live.

    The corresponding readiness probe (``/readyz``) is what decides
    whether traffic may be routed to this instance.
    """
    return JSONResponse(
        content={"status": "ok", "timestamp": datetime.now(UTC).isoformat()},
        status_code=200,
    )


@router.get("/readyz")
async def readiness(request: Request, session: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Readiness probe — returns 200 only when every hard dependency is up.

    Only PostgreSQL and Redis are hard dependencies. Model providers,
    embeddings, Telegram, and external integrations are reported by
    ``/health`` but never prevent capture/retrieval traffic.

    Returns 503 with per-dependency status when any probe fails. The web proxy
    should not route traffic upstream until this endpoint reports 200.
    """
    (db_result, redis_result) = await asyncio.gather(
        _check_database(session),
        _check_redis(),
    )

    services = {
        "database": db_result,
        "redis": redis_result,
    }

    # Every hard dependency must be "ok". Anything else (down / unknown /
    # degraded) means we are not ready to receive traffic.
    overall_ready = all(svc["status"] == "ok" for svc in services.values())
    status_code = 200 if overall_ready else 503
    return JSONResponse(
        content={
            "status": "ready" if overall_ready else "not_ready",
            "services": services,
            "timestamp": datetime.now(UTC).isoformat(),
        },
        status_code=status_code,
    )


@router.get("/health/preflight")
async def health_preflight(request: Request) -> JSONResponse:
    """Return the most recent startup preflight report."""
    report: PreflightReport | None = getattr(request.app.state, "preflight_report", None)
    if report is None:
        report = await run_startup_preflight(
            settings=get_settings(),
            include_runtime_checks=False,
        )
    status_code = 200 if report.status != "fail" else 503
    return JSONResponse(content=report.model_dump(mode="json"), status_code=status_code)
