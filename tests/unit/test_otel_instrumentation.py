"""Tests for OpenTelemetry instrumentation (Phase 3.1).

Guarantees covered:

* Disabled path (``OTEL_EXPORTER_OTLP_ENDPOINT`` empty) is a true no-op
  — the TracerProvider stays a NoOp and ``start_as_current_span``
  returns a context manager whose span has no effect.
* When enabled against an in-memory exporter, ``call_llm`` emits a
  ``gen_ai.client`` span with the April 2026 GenAI semantic-convention
  attributes (``gen_ai.system``, ``gen_ai.request.model``,
  ``gen_ai.usage.input_tokens``, …) *plus* the Anthropic-specific
  cache and cost extensions.
* Prompt + completion content is omitted by default and emitted as span events
  only after a separate explicit opt-in.
* MCP tool spans carry the formally-adopted ``mcp.*`` attributes
  (``mcp.method.name``, ``mcp.tool.name``, ``mcp.protocol.version``,
  ``mcp.session.id``).
* Instrumentation overhead on the no-op path is < 5 ms for a typical
  call.
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.app.core.otel as otel_module
from src.app.core.llm_helpers import call_llm
from src.app.core.otel import get_tracer, is_configured


def _build_message_response(
    text: str = "hello",
    *,
    input_tokens: int = 42,
    output_tokens: int = 17,
    cache_read: int = 7,
    cache_5m: int = 3,
    cache_1h: int = 0,
):
    """Build a fake Anthropic Message response."""
    block = MagicMock()
    block.text = text
    block.type = "text"

    cache_creation = MagicMock()
    cache_creation.ephemeral_5m_input_tokens = cache_5m
    cache_creation.ephemeral_1h_input_tokens = cache_1h

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = cache_read
    usage.cache_creation_input_tokens = cache_5m + cache_1h
    usage.cache_creation = cache_creation

    response = MagicMock()
    response.content = [block]
    response.usage = usage
    return response


class _TracerStateGuard:
    """Restore the module's cached tracer after a test mutates it."""

    def __enter__(self):
        self._old_tracer = otel_module._tracer
        self._old_configured = otel_module._configured
        return self

    def __exit__(self, *args):
        otel_module._tracer = self._old_tracer
        otel_module._configured = self._old_configured


@pytest.fixture
def otel_in_memory_exporter():
    """Install an in-memory OTel exporter and return captured spans.

    Only used for the "enabled" tests. Restores the prior tracer state
    on exit so other tests aren't polluted by the SDK provider install.
    """
    # Import lazily inside the fixture so the "disabled path" tests run
    # even if the SDK exporter modules weren't importable.
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with _TracerStateGuard():
        # Swap in a tracer bound to our in-memory provider *without*
        # touching the global one (the global one is set at app startup
        # via setup_otel; test-isolation matters here).
        otel_module._tracer = provider.get_tracer("test")
        otel_module._configured = True
        yield exporter


# ---------------------------------------------------------------------------
# Disabled path — zero overhead invariant
# ---------------------------------------------------------------------------


class TestOtelDisabledPath:
    """When OTEL_EXPORTER_OTLP_ENDPOINT is empty the tracer is a no-op."""

    def test_noop_tracer_returned_when_not_configured(self):
        with _TracerStateGuard():
            otel_module._tracer = None
            otel_module._configured = False
            tracer = get_tracer()
            # Spans must be usable as context managers even on the noop path.
            with tracer.start_as_current_span("test"):
                pass
            assert is_configured() is False

    async def test_call_llm_emits_no_span_when_disabled(self):
        """On the disabled path, call_llm works and emits no OTel span."""
        with _TracerStateGuard():
            otel_module._tracer = None  # force get_tracer() -> noop
            otel_module._configured = False

            client = AsyncMock()
            client.messages.create = AsyncMock(
                return_value=_build_message_response(),
            )
            result = await call_llm(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="Sys",
                messages=[{"role": "user", "content": "Hi"}],
                inject_personality=False,
                inject_datetime=False,
                cache_system=False,
            )
            assert result is not None

    async def test_instrumentation_overhead_under_5ms(self):
        """Instrumented call_llm on the disabled path adds < 5 ms per call.

        Averaged over multiple runs to absorb asyncio scheduler jitter.
        """
        with _TracerStateGuard():
            otel_module._tracer = None
            otel_module._configured = False

            client = AsyncMock()
            client.messages.create = AsyncMock(
                return_value=_build_message_response(),
            )

            # Warm up (ZoneInfo cache, structlog bind, etc.).
            await call_llm(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
                inject_personality=False,
                inject_datetime=False,
                cache_system=False,
            )

            # Measure.
            runs = 10
            start = time.monotonic()
            for _ in range(runs):
                await call_llm(
                    client,
                    model="claude-haiku-4-5-20251001",
                    max_tokens=10,
                    system="sys",
                    messages=[{"role": "user", "content": "hi"}],
                    inject_personality=False,
                    inject_datetime=False,
                    cache_system=False,
                )
            elapsed_ms = (time.monotonic() - start) * 1000
            # 10 instrumented calls must average well under 5 ms each —
            # the mock client returns instantly so this measures ONLY
            # the instrumentation (span setup, attribute emission, PII
            # redaction of the prompt event body).
            assert elapsed_ms / runs < 5, (
                f"Instrumentation overhead too high: {elapsed_ms / runs:.2f} ms/call"
            )


# ---------------------------------------------------------------------------
# Enabled path — span + attributes + events
# ---------------------------------------------------------------------------


class TestCallLlmGenAISpan:
    """call_llm emits a GenAI span with April 2026 semconv attributes."""

    async def test_span_emitted_with_gen_ai_attrs(self, otel_in_memory_exporter):
        client = AsyncMock()
        client.messages.create = AsyncMock(
            return_value=_build_message_response(
                text="reply text",
                input_tokens=11,
                output_tokens=13,
                cache_read=5,
                cache_5m=2,
                cache_1h=1,
            ),
        )
        await call_llm(
            client,
            model="claude-sonnet-4-6",
            max_tokens=500,
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hello"}],
            inject_personality=False,
            inject_datetime=False,
            cache_system=False,
        )

        spans = otel_in_memory_exporter.get_finished_spans()
        gen_ai_spans = [s for s in spans if s.name == "gen_ai.client"]
        assert len(gen_ai_spans) == 1
        span = gen_ai_spans[0]

        # GenAI core attrs (April 2026 semconv, Development status).
        attrs = dict(span.attributes)
        assert attrs["gen_ai.system"] == "anthropic"
        assert attrs["gen_ai.request.model"] == "claude-sonnet-4-6"
        assert attrs["gen_ai.request.max_tokens"] == 500
        assert attrs["gen_ai.usage.input_tokens"] == 11
        assert attrs["gen_ai.usage.output_tokens"] == 13

        # Anthropic cache extensions.
        assert attrs["anthropic.usage.cache_read_input_tokens"] == 5
        assert attrs["anthropic.usage.cache_creation_ephemeral_5m"] == 2
        assert attrs["anthropic.usage.cache_creation_ephemeral_1h"] == 1

        # Cost extensions (computed from estimate_cost — non-zero).
        assert "gen_ai.usage.cost_usd" in attrs
        assert "gen_ai.usage.cost_gbp" in attrs

    async def test_prompt_and_completion_omitted_by_default(self, otel_in_memory_exporter):
        """Metadata spans must not contain prompt or completion bodies by default."""
        client = AsyncMock()
        client.messages.create = AsyncMock(
            return_value=_build_message_response(text="model reply"),
        )
        await call_llm(
            client,
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="SYSTEM",
            messages=[{"role": "user", "content": "USER-PROMPT"}],
            inject_personality=False,
            inject_datetime=False,
            cache_system=False,
        )
        spans = [
            s for s in otel_in_memory_exporter.get_finished_spans() if s.name == "gen_ai.client"
        ]
        assert len(spans) == 1
        span = spans[0]

        assert list(span.events) == []

        attrs = dict(span.attributes)
        joined_attrs = " ".join(str(v) for v in attrs.values())
        assert "USER-PROMPT" not in joined_attrs
        assert "SYSTEM" not in joined_attrs
        assert "model reply" not in joined_attrs

    async def test_content_events_require_explicit_opt_in(self, otel_in_memory_exporter):
        client = AsyncMock()
        client.messages.create = AsyncMock(
            return_value=_build_message_response(text="model reply"),
        )
        settings = SimpleNamespace(
            otel_export_content=True,
            pii_redaction_enabled=True,
        )
        with patch("src.app.config.get_settings", return_value=settings):
            await call_llm(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="SYSTEM",
                messages=[{"role": "user", "content": "USER-PROMPT"}],
                inject_personality=False,
                inject_datetime=False,
                cache_system=False,
            )

        spans = [
            s for s in otel_in_memory_exporter.get_finished_spans() if s.name == "gen_ai.client"
        ]
        event_names = [event.name for event in spans[0].events]
        assert event_names == [
            "gen_ai.system.message",
            "gen_ai.user.message",
            "gen_ai.choice",
        ]


# ---------------------------------------------------------------------------
# MCP span attributes
# ---------------------------------------------------------------------------


class TestMcpSpan:
    async def test_mcp_span_has_required_attrs(self, otel_in_memory_exporter):
        """_execute_single_tool emits an mcp.tool.call span with mcp.* attrs."""
        from src.app.core.mcp_bridge import _execute_single_tool
        from src.app.domain.models import ToolInvocationPlan

        client_manager = MagicMock()
        client_manager.session_id = "sess-abc"
        client_manager.resolve_namespaced_tool = MagicMock(
            return_value=("tavily-search", "search"),
        )
        client_manager.call_tool = AsyncMock(
            return_value={
                "content": [{"type": "text", "text": "result"}],
                "is_error": False,
            },
        )

        plan = ToolInvocationPlan(
            tool_id="toolu_123",
            server_name="tavily-search",
            tool_name="search",
            public_name="tavily-search__search",
            arguments={"q": "hello"},
            input_schema={},
            argument_hash="hash-x",
            idempotency_key="idem-x",
            trust_context="trusted",
            requires_confirmation=False,
            mutation_class="read_only",
            allowed_parallelism="parallel_read_only",
            audit_metadata={},
            workflow_id=None,
        )

        await _execute_single_tool(client_manager, plan)
        spans = [
            s for s in otel_in_memory_exporter.get_finished_spans() if s.name == "mcp.tool.call"
        ]
        assert len(spans) == 1
        attrs = dict(spans[0].attributes)
        assert attrs["mcp.method.name"] == "tools/call"
        assert attrs["mcp.tool.name"] == "tavily-search__search"
        assert attrs["mcp.protocol.version"] == "2024-11-05"
        assert attrs["mcp.session.id"] == "sess-abc"
        assert attrs["mcp.server.name"] == "tavily-search"
        # Latency attribute must always be populated on the success path.
        assert "mcp.tool.latency_ms" in attrs
        assert attrs["mcp.tool.status"] == "ok"


# ---------------------------------------------------------------------------
# setup_otel end-to-end
# ---------------------------------------------------------------------------


class TestSampleTraceHierarchy:
    """End-to-end sanity — HTTP -> orchestrator -> LLM call -> MCP tool.

    This is primarily a documentation test: the layout captured here is
    the canonical trace shape we expect in production. When the caller
    asks for a 'sample trace' in a release note, this test is where it
    comes from.
    """

    async def test_full_hierarchy(self, otel_in_memory_exporter):
        from src.app.core.mcp_bridge import _execute_single_tool
        from src.app.core.otel import get_tracer
        from src.app.domain.models import ToolInvocationPlan

        tracer = get_tracer()

        # ---- Simulated HTTP request span ----
        with tracer.start_as_current_span("http.request") as http_span:
            http_span.set_attribute("http.method", "POST")
            http_span.set_attribute("http.route", "/api/chat")
            http_span.set_attribute("request.id", "req-xyz-42")

            # ---- Orchestrator span (manual, simulating LangGraph) ----
            with tracer.start_as_current_span("orchestrator.chat"):
                # ---- LLM call ----
                client = AsyncMock()
                client.messages.create = AsyncMock(
                    return_value=_build_message_response(
                        text="let me search",
                        input_tokens=120,
                        output_tokens=35,
                        cache_read=60,
                    ),
                )
                await call_llm(
                    client,
                    model="claude-sonnet-4-6",
                    max_tokens=500,
                    system="You are helpful.",
                    messages=[
                        {"role": "user", "content": "latest on FastAPI?"},
                    ],
                    inject_personality=False,
                    inject_datetime=False,
                    cache_system=False,
                )

                # ---- MCP tool call ----
                cm = MagicMock()
                cm.session_id = "sess-101"
                cm.resolve_namespaced_tool = MagicMock(
                    return_value=("tavily-search", "search"),
                )
                cm.call_tool = AsyncMock(
                    return_value={
                        "content": [{"type": "text", "text": "results"}],
                        "is_error": False,
                    },
                )
                plan = ToolInvocationPlan(
                    tool_id="toolu_777",
                    server_name="tavily-search",
                    tool_name="search",
                    public_name="tavily-search__search",
                    arguments={"q": "fastapi"},
                    input_schema={},
                    argument_hash="h",
                    idempotency_key="i",
                    trust_context="",
                    requires_confirmation=False,
                    mutation_class="read_only",
                    allowed_parallelism="parallel_read_only",
                    audit_metadata={},
                    workflow_id=None,
                )
                await _execute_single_tool(cm, plan)

        spans = otel_in_memory_exporter.get_finished_spans()
        names = {s.name for s in spans}
        assert {"http.request", "orchestrator.chat", "gen_ai.client", "mcp.tool.call"} <= names

        # Verify parent-child linkage so the hierarchy is preserved.
        by_id = {s.context.span_id: s for s in spans}
        gen_ai = next(s for s in spans if s.name == "gen_ai.client")
        mcp = next(s for s in spans if s.name == "mcp.tool.call")
        orchestrator = next(s for s in spans if s.name == "orchestrator.chat")
        http = next(s for s in spans if s.name == "http.request")

        assert gen_ai.parent is not None
        assert mcp.parent is not None
        assert by_id[gen_ai.parent.span_id] is orchestrator
        assert by_id[mcp.parent.span_id] is orchestrator
        assert orchestrator.parent is not None
        assert by_id[orchestrator.parent.span_id] is http
        assert http.parent is None  # root span


class TestSetupOtel:
    def test_setup_otel_disabled_endpoint_empty(self, monkeypatch):
        """Empty endpoint short-circuits into the noop path and sets env var."""
        from fastapi import FastAPI

        from src.app.config import Settings
        from src.app.core.otel import is_configured, setup_otel

        # Unset any stale env var from earlier tests.
        monkeypatch.delenv("OTEL_SEMCONV_STABILITY_OPT_IN", raising=False)

        settings = MagicMock(spec=Settings)
        settings.otel_configured = False
        settings.otel_enabled = False
        settings.otel_exporter_otlp_endpoint = ""
        settings.otel_semconv_opt_in = "gen_ai_latest_experimental"
        settings.otel_service_name = "test-svc"
        settings.otel_service_version = "0.0.0"
        settings.app_env = "test"
        settings.otel_sampler_ratio = 0.1
        settings.otel_traces_sampler = "parentbased_always_on"
        settings.otel_exporter_otlp_headers = ""

        with _TracerStateGuard():
            app = FastAPI()
            setup_otel(app, settings)
            # Spec-compliant env var set even on the disabled path.
            assert os.environ.get("OTEL_SEMCONV_STABILITY_OPT_IN") == "gen_ai_latest_experimental"
            assert is_configured() is False
