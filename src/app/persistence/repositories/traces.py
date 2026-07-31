"""Trace span repository helpers."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import AgentTraceSpan


async def create_trace_spans(
    session: AsyncSession,
    spans: list[dict],
) -> list[AgentTraceSpan]:
    """Persist a batch of trace spans."""
    records = [
        AgentTraceSpan(
            id=uuid.UUID(str(span["id"])),
            trace_id=str(span["trace_id"]),
            parent_span_id=_optional_str(span.get("parent_span_id")),
            name=str(span["name"]),
            span_kind=str(span["span_kind"]),
            channel=str(span["channel"]),
            specialist=_optional_str(span.get("specialist")),
            status=str(span["status"]),
            error_class=_optional_str(span.get("error_class")),
            model=_optional_str(span.get("model")),
            tokens_in=span.get("tokens_in"),
            tokens_out=span.get("tokens_out"),
            tool_name=_optional_str(span.get("tool_name")),
            cache_hit=span.get("cache_hit"),
            latency_ms=span.get("latency_ms"),
            details=span.get("details") or {},
        )
        for span in spans
    ]
    for record in records:
        session.add(record)
    await session.flush()
    return records


async def list_trace_spans(
    session: AsyncSession,
    *,
    limit: int = 50,
    trace_id: str | None = None,
) -> list[AgentTraceSpan]:
    """List trace spans, newest first."""
    stmt = select(AgentTraceSpan).order_by(AgentTraceSpan.created_at.desc()).limit(limit)
    if trace_id:
        stmt = (
            select(AgentTraceSpan)
            .where(AgentTraceSpan.trace_id == trace_id)
            .order_by(AgentTraceSpan.created_at.asc())
        )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def summarize_traces(
    session: AsyncSession,
    *,
    limit: int = 25,
) -> list[dict]:
    """Group spans by trace_id into lightweight summaries."""
    spans = await list_trace_spans(session, limit=limit * 20)
    grouped: dict[str, list[AgentTraceSpan]] = defaultdict(list)
    for span in spans:
        grouped[span.trace_id].append(span)

    summaries: list[dict] = []
    for trace_id, trace_spans in grouped.items():
        ordered = sorted(trace_spans, key=lambda item: item.created_at)
        root = ordered[0]
        summaries.append(
            {
                "trace_id": trace_id,
                "channel": root.channel,
                "specialist": root.specialist,
                "status": _trace_status(ordered),
                "span_count": len(ordered),
                "created_at": root.created_at.isoformat(),
                "total_latency_ms": sum(span.latency_ms or 0 for span in ordered),
                "error_count": sum(1 for span in ordered if span.status == "error"),
            }
        )

    summaries.sort(key=lambda item: item["created_at"], reverse=True)
    return summaries[:limit]


async def get_trace_detail(
    session: AsyncSession,
    trace_id: str,
) -> dict | None:
    """Return one trace summary with all spans."""
    spans = await list_trace_spans(session, trace_id=trace_id)
    if not spans:
        return None

    return {
        "trace_id": trace_id,
        "channel": spans[0].channel,
        "specialist": spans[0].specialist,
        "status": _trace_status(spans),
        "created_at": spans[0].created_at.isoformat(),
        "spans": [
            {
                "id": str(span.id),
                "parent_span_id": span.parent_span_id,
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
                "details": span.details or {},
                "created_at": span.created_at.isoformat(),
            }
            for span in spans
        ],
    }


def _trace_status(spans: list[AgentTraceSpan]) -> str:
    if any(span.status == "error" for span in spans):
        return "error"
    if any(span.status == "degraded" for span in spans):
        return "degraded"
    return "success"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
