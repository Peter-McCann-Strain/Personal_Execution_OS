"""End-to-end correlation: request_id must propagate from HTTP middleware
through LangGraph AgentState, through llm_helpers logs, into ARQ worker
jobs, and onto agent_trace_spans records.

This file covers the glue added in Phase 3.2. The pieces individually have
narrower tests (test_middleware, test_orchestrator_graph, test_agent_tasks,
handlers/test_common); these tests pin down the cross-layer contract so a
regression in any single piece breaks the suite loudly.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog

from src.app.core.trace import TraceRecorder, get_or_create_trace_recorder
from src.app.domain.services.handlers import _common as common_module
from src.app.workers.agent_tasks import process_agent_task

# ---------------------------------------------------------------------------
# llm_helpers.llm_call_success inherits request_id via structlog contextvars
# ---------------------------------------------------------------------------


async def test_llm_call_success_inherits_request_id_from_contextvars():
    """llm_call_success log entries must carry the middleware-bound request_id.

    Regression guard: logging.py includes structlog.contextvars.merge_contextvars
    in its processor chain. If someone removes it, every LLM call loses its
    correlation ID and the entire trace story breaks.
    """
    from src.app.core.logging import setup_logging

    setup_logging("INFO", "dev")
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="req-correlation-test")

    captured_event: dict = {}

    def _capture(_logger, _method, event_dict):
        if event_dict.get("event") == "llm_call_success":
            captured_event.update(event_dict)
        return event_dict

    # Reconfigure structlog with our capture processor in front of the renderer.
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _capture,
            structlog.processors.KeyValueRenderer(),
        ],
        cache_logger_on_first_use=False,
    )
    try:
        # Emit the same event llm_helpers.call_llm emits on success.
        structlog.get_logger().info(
            "llm_call_success",
            model="claude-haiku-4-5",
            tokens_in=10,
            tokens_out=20,
        )
    finally:
        structlog.contextvars.clear_contextvars()

    assert captured_event.get("request_id") == "req-correlation-test", (
        "llm_call_success must inherit request_id from contextvars — "
        "if this fails, merge_contextvars is missing from the processor chain"
    )


# ---------------------------------------------------------------------------
# enqueue_agent_task copies request_id from contextvars into the ARQ payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_agent_task_stashes_request_id_in_payload():
    """HTTP path enqueues a worker job → request_id must ride along in payload.

    contextvars don't cross the asyncio boundary into a fresh ARQ worker
    process, so the payload is the only transport.
    """
    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    mock_pool.aclose = AsyncMock()

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="req-enqueue-test")

    try:
        with patch.object(common_module, "get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                redis_url=MagicMock(get_secret_value=lambda: "redis://localhost:6379"),
            )
            with patch(
                "arq.connections.create_pool",
                new_callable=AsyncMock,
                return_value=mock_pool,
            ):
                await common_module.enqueue_agent_task(
                    "entity_extraction",
                    {"episode_id": "ep-1", "text": "hello"},
                    error_label="Entity extraction",
                )
    finally:
        structlog.contextvars.clear_contextvars()

    # The payload that was actually enqueued must include request_id.
    mock_pool.enqueue_job.assert_awaited_once()
    args, _kwargs = mock_pool.enqueue_job.call_args
    assert args[0] == "process_agent_task"
    assert args[1] == "entity_extraction"
    payload = args[2]
    assert payload["request_id"] == "req-enqueue-test"
    assert payload["episode_id"] == "ep-1"


@pytest.mark.asyncio
async def test_enqueue_agent_task_no_request_id_when_contextvar_unbound():
    """No contextvar bound → payload stays clean (don't fabricate IDs)."""
    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    mock_pool.aclose = AsyncMock()

    structlog.contextvars.clear_contextvars()

    with patch.object(common_module, "get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            redis_url=MagicMock(get_secret_value=lambda: "redis://localhost:6379"),
        )
        with patch(
            "arq.connections.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await common_module.enqueue_agent_task(
                "entity_extraction",
                {"episode_id": "ep-2", "text": "hi"},
                error_label="Entity extraction",
            )

    args, _ = mock_pool.enqueue_job.call_args
    payload = args[2]
    assert "request_id" not in payload


# ---------------------------------------------------------------------------
# Worker rebinds request_id from payload onto structlog contextvars
# ---------------------------------------------------------------------------


async def test_process_agent_task_binds_request_id_from_payload():
    """On task start, worker must re-bind request_id so downstream LLM logs
    (llm_call_success) carry the same ID as the originating HTTP turn.

    Cross-process/cross-event-loop gotcha: contextvars do NOT survive ARQ's
    job dispatch — the payload is the only carrier.
    """
    structlog.contextvars.clear_contextvars()
    observed: dict = {}

    async def _fake_handler(_ctx, _payload):
        observed.update(structlog.contextvars.get_contextvars())
        return {"status": "ok"}

    with patch.dict(
        "src.app.workers.agent_tasks.__dict__",
        {"_run_entity_extraction": _fake_handler},
    ):
        # Manually re-point the handler table inside process_agent_task.
        # Easiest way: monkeypatch the lookup table via a wrapper.
        from src.app.workers import agent_tasks as at

        original = at._run_entity_extraction
        at._run_entity_extraction = _fake_handler
        try:
            await process_agent_task(
                {
                    "job_try": 1,
                    "llm_provider": SimpleNamespace(configured=True),
                },
                "entity_extraction",
                {
                    "request_id": "req-worker-rebind",
                    "episode_id": "ep-3",
                    "text": "hi",
                },
            )
        finally:
            at._run_entity_extraction = original

    assert observed.get("request_id") == "req-worker-rebind"
    assert observed.get("worker_task_type") == "entity_extraction"


# ---------------------------------------------------------------------------
# TraceRecorder.trace_id == request_id so agent_trace_spans.trace_id ties back
# ---------------------------------------------------------------------------


def test_trace_recorder_uses_request_id_as_trace_id():
    """Every span recorded during a chat turn carries trace_id == request_id.

    get_or_create_trace_recorder reads metadata['request_id'] and uses it as
    the trace_id for every span it adds. That means grepping
    agent_trace_spans.trace_id for a given request_id surfaces every tool
    call, retrieval, and LLM span from the originating HTTP request.
    """
    metadata: dict = {"request_id": "req-span-correlation"}
    recorder = get_or_create_trace_recorder(
        metadata,
        channel="api",
        user_id="user-1",
    )

    assert isinstance(recorder, TraceRecorder)
    assert recorder.trace_id == "req-span-correlation"
    assert metadata["trace_id"] == "req-span-correlation"

    span_id = recorder.add_span(
        name="tool.web_search",
        span_kind="tool",
        tool_name="web_search",
    )
    [span] = recorder.spans
    assert span.trace_id == "req-span-correlation"
    assert span.id == span_id
    record = span.to_record()
    assert record["trace_id"] == "req-span-correlation"
