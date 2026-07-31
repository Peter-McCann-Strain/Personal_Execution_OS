"""Optional observability bridge for PostHog and Sentry."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from contextlib import suppress
from importlib import import_module
from typing import Any

import httpx
import structlog

from src.app.config import Settings, get_settings
from src.app.core.trace import TraceRecorder

logger = structlog.get_logger()


class _PostHogClient:
    """Tiny async PostHog client for best-effort event export."""

    def __init__(self, *, api_key: str, host: str) -> None:
        self._api_key = api_key
        self._endpoint = f"{host.rstrip('/')}/capture/"
        self._tasks: set[asyncio.Task[None]] = set()

    def capture(
        self,
        *,
        event: str,
        distinct_id: str,
        properties: dict[str, Any],
    ) -> None:
        """Schedule an event export when an event loop is available."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("telemetry_posthog_capture_skipped_no_loop", event=event)
            return

        task = loop.create_task(
            self._send_event(
                event=event,
                distinct_id=distinct_id,
                properties=properties,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        with suppress(asyncio.CancelledError):
            try:
                task.result()
            except Exception:
                logger.warning("telemetry_posthog_capture_failed", exc_info=True)

    async def _send_event(
        self,
        *,
        event: str,
        distinct_id: str,
        properties: dict[str, Any],
    ) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                self._endpoint,
                json={
                    "api_key": self._api_key,
                    "event": event,
                    "distinct_id": distinct_id,
                    "properties": properties,
                },
            )
            response.raise_for_status()


class TelemetryBridge:
    """Best-effort bridge to external telemetry systems.

    The bridge never raises into request handling. If PostHog or Sentry are
    unavailable, the application continues with database-backed observability.
    """

    def __init__(self) -> None:
        self._posthog_client: _PostHogClient | None = None
        self._sentry_sdk: Any | None = None
        self._configured = False
        self._installation_salt = ""

    def configure(self, settings: Settings | None = None) -> None:
        """Configure external telemetry clients when credentials are available."""
        settings = settings or get_settings()
        self._posthog_client = None
        self._sentry_sdk = None
        self._configured = False
        self._installation_salt = settings.telemetry_installation_salt.get_secret_value().strip()

        sentry_configured = bool(getattr(settings, "sentry_configured", False))
        posthog_configured = bool(getattr(settings, "posthog_configured", False))

        if sentry_configured:
            try:
                sentry_sdk = import_module("sentry_sdk")
                sentry_dsn = getattr(settings, "sentry_dsn", None)
                if sentry_dsn is None:
                    raise ValueError("sentry_dsn missing")
                sentry_sdk.init(
                    dsn=sentry_dsn.get_secret_value(),
                    enable_tracing=True,
                    traces_sample_rate=(
                        0.0
                        if settings.app_env == "test"
                        else getattr(settings, "sentry_traces_sample_rate", 0.1)
                    ),
                    profiles_sample_rate=(
                        0.0
                        if settings.app_env == "test"
                        else getattr(settings, "sentry_profiles_sample_rate", 0.0)
                    ),
                    send_default_pii=getattr(settings, "sentry_send_default_pii", False),
                    environment=settings.app_env,
                )
                self._sentry_sdk = sentry_sdk
                logger.info(
                    "telemetry_sentry_configured",
                    environment=settings.app_env,
                    traces_sample_rate=(
                        0.0
                        if settings.app_env == "test"
                        else getattr(settings, "sentry_traces_sample_rate", 0.1)
                    ),
                    profiles_sample_rate=(
                        0.0
                        if settings.app_env == "test"
                        else getattr(settings, "sentry_profiles_sample_rate", 0.0)
                    ),
                )
            except Exception:
                logger.warning("telemetry_sentry_unavailable", exc_info=True)

        if posthog_configured:
            try:
                api_key = getattr(settings, "posthog_api_key", None)
                if api_key is None:
                    raise ValueError("posthog_api_key missing")
                self._posthog_client = _PostHogClient(
                    api_key=api_key.get_secret_value(),
                    host=getattr(settings, "posthog_host", "https://eu.i.posthog.com"),
                )
                logger.info(
                    "telemetry_posthog_configured",
                    host=getattr(settings, "posthog_host", "https://eu.i.posthog.com"),
                )
            except Exception:
                logger.warning("telemetry_posthog_unavailable", exc_info=True)

        self._configured = True

    @property
    def status(self) -> dict[str, bool]:
        """Return the configured telemetry surface."""
        return {
            "configured": self._configured,
            "sentry": self._sentry_sdk is not None,
            "posthog": self._posthog_client is not None,
        }

    def capture_exception(
        self,
        exc: BaseException,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Forward one exception to Sentry when available."""
        if self._sentry_sdk is None:
            return
        try:
            safe_exception = RuntimeError(type(exc).__name__)
            if context:
                with self._sentry_sdk.push_scope() as scope:
                    for key, value in context.items():
                        scope.set_context(
                            str(key),
                            value if isinstance(value, dict) else {"value": value},
                        )
                    self._sentry_sdk.capture_exception(safe_exception)
                return
            self._sentry_sdk.capture_exception(safe_exception)
        except Exception:
            logger.warning("telemetry_capture_exception_failed", exc_info=True)

    def record_trace(self, recorder: TraceRecorder) -> None:
        """Best-effort export of trace and span summaries into PostHog."""
        if self._posthog_client is None or not recorder.spans:
            return

        try:
            total_latency_ms = sum(span.latency_ms or 0 for span in recorder.spans)
            error_count = sum(1 for span in recorder.spans if span.status != "success")
            distinct_id = self._analytics_distinct_id(recorder.user_id)

            self._posthog_client.capture(
                event="assistant_trace_completed",
                distinct_id=distinct_id,
                properties={
                    "trace_id": recorder.trace_id,
                    "channel": recorder.channel,
                    "specialist": recorder.specialist,
                    "span_count": len(recorder.spans),
                    "total_latency_ms": total_latency_ms,
                    "error_count": error_count,
                },
            )

            for span in recorder.spans:
                self._posthog_client.capture(
                    event="assistant_span_completed",
                    distinct_id=distinct_id,
                    properties={
                        "trace_id": recorder.trace_id,
                        "span_id": span.id,
                        "name": span.name,
                        "span_kind": span.span_kind,
                        "channel": span.channel,
                        "specialist": span.specialist,
                        "status": span.status,
                        "error_class": span.error_class,
                        "model": span.model,
                        "tokens_in": span.tokens_in,
                        "tokens_out": span.tokens_out,
                        "tool_name": span.tool_name,
                        "cache_hit": span.cache_hit,
                        "latency_ms": span.latency_ms,
                    },
                )
        except Exception:
            logger.warning("telemetry_record_trace_failed", exc_info=True)

    def _analytics_distinct_id(self, user_id: str | None) -> str:
        """Return a non-identifying PostHog key.

        Raw owner/user IDs never leave the installation. Without an explicit
        installation salt, analytics is deliberately anonymous and cannot
        correlate a person across installations.
        """
        if not self._installation_salt:
            return "anonymous"
        local_subject = user_id or "owner"
        digest = hmac.new(
            self._installation_salt.encode("utf-8"),
            local_subject.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"installation:{digest[:32]}"


_telemetry_bridge = TelemetryBridge()


def configure_telemetry(settings: Settings | None = None) -> TelemetryBridge:
    """Configure and return the global telemetry bridge."""
    _telemetry_bridge.configure(settings)
    return _telemetry_bridge


def get_telemetry() -> TelemetryBridge:
    """Return the configured global telemetry bridge."""
    return _telemetry_bridge
