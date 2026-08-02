"""Trace persistence, grouping, and empty-state tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.persistence.models import AgentTraceSpan
from src.app.persistence.repositories.traces import (
    _optional_str,
    _trace_status,
    create_trace_spans,
    get_trace_detail,
    list_trace_spans,
    summarize_traces,
)


class _Scalars:
    def __init__(self, rows: list[object] | None = None) -> None:
        self._rows = list(rows or [])

    def all(self) -> list[object]:
        return list(self._rows)


class _Result:
    def __init__(self, rows: list[object] | None = None) -> None:
        self._rows = list(rows or [])

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


def _session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock(return_value=_Result())
    return session


def _span(**overrides: object) -> AgentTraceSpan:
    span = AgentTraceSpan()
    span.id = overrides.get("id", uuid.uuid4())
    span.trace_id = overrides.get("trace_id", "trace-one")
    span.parent_span_id = overrides.get("parent_span_id")
    span.name = overrides.get("name", "request")
    span.span_kind = overrides.get("span_kind", "orchestrator")
    span.channel = overrides.get("channel", "api")
    span.specialist = overrides.get("specialist")
    span.status = overrides.get("status", "success")
    span.error_class = overrides.get("error_class")
    span.model = overrides.get("model")
    span.tokens_in = overrides.get("tokens_in")
    span.tokens_out = overrides.get("tokens_out")
    span.tool_name = overrides.get("tool_name")
    span.cache_hit = overrides.get("cache_hit")
    span.latency_ms = overrides.get("latency_ms")
    span.details = overrides.get("details", {})
    span.created_at = overrides.get(
        "created_at",
        datetime(2026, 8, 2, 10, tzinfo=UTC),
    )
    return span


@pytest.mark.asyncio
async def test_create_trace_spans_maps_full_and_minimal_payloads_without_commit() -> None:
    session = _session()
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    records = await create_trace_spans(
        session,
        [
            {
                "id": str(first_id),
                "trace_id": "trace-one",
                "parent_span_id": 42,
                "name": "model",
                "span_kind": "model",
                "channel": "api",
                "specialist": "researcher",
                "status": "degraded",
                "error_class": "TimeoutError",
                "model": "model-one",
                "tokens_in": 10,
                "tokens_out": 20,
                "tool_name": "search",
                "cache_hit": False,
                "latency_ms": 125,
                "details": {"attempt": 1},
            },
            {
                "id": second_id,
                "trace_id": "trace-one",
                "name": "finalize",
                "span_kind": "orchestrator",
                "channel": "api",
                "status": "success",
                "details": None,
            },
        ],
    )

    assert [record.id for record in records] == [first_id, second_id]
    assert records[0].parent_span_id == "42"
    assert records[0].specialist == "researcher"
    assert records[0].error_class == "TimeoutError"
    assert records[0].model == "model-one"
    assert records[0].tool_name == "search"
    assert records[0].details == {"attempt": 1}
    assert records[1].parent_span_id is None
    assert records[1].specialist is None
    assert records[1].details == {}
    assert session.add.call_args_list == [
        ((records[0],),),
        ((records[1],),),
    ]
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_empty_batch_still_flushes_transaction_boundary() -> None:
    session = _session()
    assert await create_trace_spans(session, []) == []
    session.add.assert_not_called()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_span_id_fails_before_session_mutation() -> None:
    session = _session()
    with pytest.raises(ValueError, match="badly formed hexadecimal UUID string"):
        await create_trace_spans(
            session,
            [
                {
                    "id": "not-a-uuid",
                    "trace_id": "trace-one",
                    "name": "invalid",
                    "span_kind": "model",
                    "channel": "api",
                    "status": "error",
                }
            ],
        )
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_trace_spans_covers_recent_filtered_and_empty_queries() -> None:
    session = _session()
    first = _span()
    second = _span(name="child", parent_span_id=str(first.id))
    session.execute.side_effect = [
        _Result([first, second]),
        _Result([]),
    ]

    assert await list_trace_spans(session, limit=2) == [first, second]
    assert await list_trace_spans(session, trace_id="missing") == []

    recent_sql = str(session.execute.await_args_list[0].args[0])
    filtered_sql = str(session.execute.await_args_list[1].args[0])
    assert "ORDER BY agent_trace_spans.created_at DESC" in recent_sql
    assert "LIMIT" in recent_sql
    assert "agent_trace_spans.trace_id" in filtered_sql
    assert "ORDER BY agent_trace_spans.created_at ASC" in filtered_sql


@pytest.mark.asyncio
async def test_summaries_group_order_limit_and_all_status_precedence() -> None:
    base = datetime(2026, 8, 2, 10, tzinfo=UTC)
    spans = [
        _span(
            trace_id="trace-success",
            status="success",
            latency_ms=None,
            created_at=base,
        ),
        _span(
            trace_id="trace-degraded",
            status="degraded",
            latency_ms=20,
            created_at=base + timedelta(hours=1),
        ),
        _span(
            trace_id="trace-degraded",
            status="success",
            latency_ms=30,
            created_at=base + timedelta(hours=1, seconds=1),
        ),
        _span(
            trace_id="trace-error",
            status="degraded",
            latency_ms=5,
            created_at=base + timedelta(hours=2, seconds=1),
        ),
        _span(
            trace_id="trace-error",
            status="error",
            latency_ms=15,
            created_at=base + timedelta(hours=2),
        ),
    ]
    with patch(
        "src.app.persistence.repositories.traces.list_trace_spans",
        new=AsyncMock(return_value=spans),
    ) as list_mock:
        summaries = await summarize_traces(_session(), limit=3)

    list_mock.assert_awaited_once()
    assert list_mock.await_args.kwargs == {"limit": 60}
    assert [summary["trace_id"] for summary in summaries] == [
        "trace-error",
        "trace-degraded",
        "trace-success",
    ]
    assert summaries[0]["status"] == "error"
    assert summaries[0]["error_count"] == 1
    assert summaries[0]["total_latency_ms"] == 20
    assert summaries[1]["status"] == "degraded"
    assert summaries[1]["span_count"] == 2
    assert summaries[1]["total_latency_ms"] == 50
    assert summaries[2]["status"] == "success"
    assert summaries[2]["total_latency_ms"] == 0

    with patch(
        "src.app.persistence.repositories.traces.list_trace_spans",
        new=AsyncMock(return_value=[]),
    ):
        assert await summarize_traces(_session(), limit=1) == []


@pytest.mark.asyncio
async def test_trace_detail_covers_empty_and_complete_serialization() -> None:
    root = _span(
        details=None,
        latency_ms=100,
        tokens_in=12,
        tokens_out=20,
        cache_hit=True,
    )
    child = _span(
        parent_span_id=str(root.id),
        name="tool",
        span_kind="tool",
        tool_name="search",
        details={"query": "release"},
        status="error",
        error_class="TimeoutError",
        created_at=root.created_at + timedelta(seconds=1),
    )
    with patch(
        "src.app.persistence.repositories.traces.list_trace_spans",
        new=AsyncMock(side_effect=[[], [root, child]]),
    ) as list_mock:
        assert await get_trace_detail(_session(), "missing") is None
        detail = await get_trace_detail(_session(), "trace-one")

    assert detail is not None
    assert detail["trace_id"] == "trace-one"
    assert detail["status"] == "error"
    assert detail["created_at"] == root.created_at.isoformat()
    assert detail["spans"][0]["details"] == {}
    assert detail["spans"][0]["tokens_in"] == 12
    assert detail["spans"][0]["cache_hit"] is True
    assert detail["spans"][1]["parent_span_id"] == str(root.id)
    assert detail["spans"][1]["tool_name"] == "search"
    assert detail["spans"][1]["details"] == {"query": "release"}
    assert list_mock.await_args_list[0].kwargs == {"trace_id": "missing"}
    assert list_mock.await_args_list[1].kwargs == {"trace_id": "trace-one"}


def test_trace_status_and_optional_string_helpers_cover_all_branches() -> None:
    assert _trace_status([_span(status="error")]) == "error"
    assert _trace_status([_span(status="degraded")]) == "degraded"
    assert _trace_status([_span(status="success")]) == "success"
    assert _optional_str(None) is None
    assert _optional_str(42) == "42"


@pytest.mark.asyncio
async def test_flush_failure_propagates_without_hidden_commit() -> None:
    session = _session()
    session.flush.side_effect = RuntimeError("trace store unavailable")

    with pytest.raises(RuntimeError, match="trace store unavailable"):
        await create_trace_spans(
            session,
            [
                {
                    "id": uuid.uuid4(),
                    "trace_id": "trace-failure",
                    "name": "request",
                    "span_kind": "orchestrator",
                    "channel": "api",
                    "status": "error",
                }
            ],
        )

    session.add.assert_called_once()
    session.commit.assert_not_awaited()
