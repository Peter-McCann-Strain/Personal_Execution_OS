"""OpenTelemetry instrumentation bootstrap (Phase 3.1).

Design goals
------------
* **Fully optional.** When ``OTEL_EXPORTER_OTLP_ENDPOINT`` is empty the
  TracerProvider stays a ``NoOpTracerProvider``, so every
  ``tracer.start_as_current_span`` call becomes a near-zero-cost no-op
  (no exporter, no span processor, no queue). The target is < 5 ms
  added latency per request when disabled — measured by
  ``test_otel_instrumentation.test_no_op_overhead``.
* **April 2026 GenAI semconv.** The semantic conventions for GenAI are
  still ``Development`` status. Callers must set
  ``OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`` to get
  the stable ``gen_ai.*`` attribute names. ``setup_otel`` defaults this
  env var if unset so the behaviour matches regardless of how uvicorn
  is launched.
* **MCP semconv formally adopted.** We emit ``mcp.*`` attributes on
  tool-call spans (``mcp.method.name``, ``mcp.tool.name``,
  ``mcp.protocol.version``, ``mcp.session.id``, ``mcp.server.name``,
  ``mcp.tool.latency_ms``).
* **Prompt/completion content goes in span events, not attributes.**
  This is the spec-compliant shape as of April 2026 — span event names
  are ``gen_ai.user.message`` / ``gen_ai.system.message`` /
  ``gen_ai.choice``, and the content itself goes in the event body so
  the Collector can drop it for PII without touching the parent span.
  We wrap the content through ``pii_redactor.redact`` before it ever
  leaves the process when ``pii_redaction_enabled=True``.
* **Tail-sampling belongs at the Collector, not in-process.** In-proc
  we head-sample at ``otel_sampler_ratio``; the Collector then keeps
  100% of errors, 100% of slow (> p95), and 10% of head-sampled
  successes. See ``docs/OBSERVABILITY.md`` for the Collector YAML.
* **agent_trace_spans table stays.** The DB-backed span table remains
  the source of truth for the app's own UI queries (trace viewer,
  SLO dashboards). OTEL spans are emitted **in addition**, not
  instead, so external collectors get the same picture without the DB
  becoming a telemetry bottleneck.

Contract
--------
Call :func:`setup_otel` from the FastAPI ``lifespan`` ONCE at startup.
Import ``get_tracer`` anywhere you need a tracer. Nothing else in the
codebase should touch the global TracerProvider directly.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from fastapi import FastAPI

    from src.app.config import Settings

logger = structlog.get_logger()

# Module-level handle so repeated calls to ``get_tracer()`` don't pay
# the lookup cost twice.
_tracer: Any | None = None
_configured: bool = False


def _noop_tracer() -> Any:
    """Return a tracer that emits no spans.

    This matches the shape of ``opentelemetry.trace.Tracer`` closely
    enough that instrumented code paths don't need to branch on
    ``if tracer is None``. The context-manager spans are real context
    managers, just without any exporter behind them.
    """
    # Lazy import: if OTEL libs aren't installed we still want the app
    # to boot. The `opentelemetry-api` package ships its own noop
    # tracer provider, so prefer that shape.
    try:
        from opentelemetry import trace as otel_trace

        return otel_trace.NoOpTracer()
    except Exception:  # pragma: no cover - OTel not installed
        # Fallback: a tiny inline stub. Only exercised in minimal test
        # environments that skip installing OTel.
        class _Span:
            def set_attribute(self, *_a: Any, **_k: Any) -> None: ...
            def set_attributes(self, *_a: Any, **_k: Any) -> None: ...
            def add_event(self, *_a: Any, **_k: Any) -> None: ...
            def record_exception(self, *_a: Any, **_k: Any) -> None: ...
            def set_status(self, *_a: Any, **_k: Any) -> None: ...
            def end(self) -> None: ...

        class _Ctx:
            def __enter__(self) -> _Span:
                return _Span()

            def __exit__(self, *args: Any) -> None:
                return None

        class _Tracer:
            def start_as_current_span(self, *_a: Any, **_k: Any) -> _Ctx:
                return _Ctx()

            def start_span(self, *_a: Any, **_k: Any) -> _Span:
                return _Span()

        return _Tracer()


def _build_sampler(settings: Settings) -> Any:
    """Construct a Sampler from the ``otel_traces_sampler`` setting.

    Returns ``None`` when the library isn't installed (caller falls
    back to the noop provider).
    """
    try:
        from opentelemetry.sdk.trace.sampling import (
            ALWAYS_OFF,
            ALWAYS_ON,
            ParentBased,
            TraceIdRatioBased,
        )
    except Exception:  # pragma: no cover - OTel not installed
        return None

    name = settings.otel_traces_sampler.lower().strip()

    if name == "always_on":
        return ALWAYS_ON
    if name == "always_off":
        return ALWAYS_OFF
    if name == "parentbased_traceidratio":
        return ParentBased(root=TraceIdRatioBased(settings.otel_sampler_ratio))
    # default: parent-based always-on. Honours upstream sampling
    # decisions (e.g. tail sampler at the Collector) and falls back to
    # always-on for root spans.
    return ParentBased(root=ALWAYS_ON)


def setup_otel(app: FastAPI, settings: Settings) -> None:
    """Configure the global TracerProvider and instrument FastAPI.

    Call once from the app's lifespan startup. Safe to call on an app
    that has no OTLP endpoint configured — that path installs a no-op
    tracer and returns without raising.
    """
    global _tracer, _configured

    # GenAI semconv opt-in. Set on the process env so any transitively
    # imported instrumentation sees the correct stability flag.
    os.environ.setdefault(
        "OTEL_SEMCONV_STABILITY_OPT_IN",
        settings.otel_semconv_opt_in,
    )

    if not settings.otel_configured:
        _tracer = _noop_tracer()
        _configured = False
        logger.info(
            "otel_disabled",
            reason=("OTEL_EXPORTER_OTLP_ENDPOINT empty or otel_enabled=False"),
        )
        return

    # Lazy imports so a partially-installed environment doesn't crash
    # the app. If any of these fails we degrade to the noop tracer.
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception:
        logger.warning("otel_libs_unavailable_noop_tracer", exc_info=True)
        _tracer = _noop_tracer()
        _configured = False
        return

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": settings.otel_service_version,
            "deployment.environment": settings.app_env,
        }
    )

    sampler = _build_sampler(settings)
    provider = (
        TracerProvider(resource=resource, sampler=sampler)
        if sampler is not None
        else TracerProvider(resource=resource)
    )

    # Parse optional OTLP headers (comma-separated k=v pairs, same
    # convention as OTEL_EXPORTER_OTLP_HEADERS in the spec).
    headers: dict[str, str] = {}
    raw_headers = settings.otel_exporter_otlp_headers.strip()
    if raw_headers:
        for chunk in raw_headers.split(","):
            if "=" in chunk:
                k, v = chunk.split("=", 1)
                headers[k.strip()] = v.strip()

    exporter = OTLPSpanExporter(
        endpoint=settings.otel_exporter_otlp_endpoint,
        headers=headers or None,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)

    _tracer = otel_trace.get_tracer(
        settings.otel_service_name,
        settings.otel_service_version,
    )
    _configured = True

    # Auto-instrument FastAPI. ``excluded_urls`` keeps noisy health
    # probes out of the trace set — they'd dwarf real traffic otherwise.
    try:
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="healthz,livez,readyz,metrics",
        )
    except Exception:
        logger.warning("otel_fastapi_instrument_failed", exc_info=True)

    logger.info(
        "otel_configured",
        endpoint=settings.otel_exporter_otlp_endpoint,
        service=settings.otel_service_name,
        version=settings.otel_service_version,
        environment=settings.app_env,
        sampler=settings.otel_traces_sampler,
    )


def get_tracer() -> Any:
    """Return the configured tracer (no-op if OTel is disabled).

    Always safe to call — returns a no-op tracer if :func:`setup_otel`
    has not been invoked yet (e.g. in tests or CLI scripts).
    """
    if _tracer is None:
        return _noop_tracer()
    return _tracer


def is_configured() -> bool:
    """True when an OTLP exporter is wired up."""
    return _configured


def bind_request_id(span: Any, request_id: str | None) -> None:
    """Attach the in-app ``request_id`` correlation ID to a span.

    We emit both ``request.id`` (the app's own canonical name) and
    ``trace_id`` (mirror for tooling that filters on that). OTel
    assigns its own cryptographic trace ID; this attribute is for
    human-facing cross-reference with structlog lines.
    """
    if span is None or not request_id:
        return
    try:
        span.set_attribute("request.id", request_id)
        span.set_attribute("trace_id", request_id)
    except Exception:
        # Never let telemetry bookkeeping break the request path.
        logger.debug("otel_bind_request_id_failed", exc_info=True)


__all__ = [
    "bind_request_id",
    "get_tracer",
    "is_configured",
    "setup_otel",
]
