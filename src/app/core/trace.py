"""Trace-first runtime helpers for request, tool, and rendering spans."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from src.app.domain.constants import TraceSpanKind, TraceSpanStatus


@dataclass(slots=True)
class RecordedSpan:
    """A completed runtime span ready for persistence."""

    id: str
    trace_id: str
    name: str
    span_kind: str
    channel: str
    parent_span_id: str | None = None
    specialist: str | None = None
    status: str = TraceSpanStatus.SUCCESS
    error_class: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tool_name: str | None = None
    cache_hit: bool | None = None
    latency_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """Convert to a plain dict for persistence."""
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "span_kind": self.span_kind,
            "channel": self.channel,
            "specialist": self.specialist,
            "status": self.status,
            "error_class": self.error_class,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tool_name": self.tool_name,
            "cache_hit": self.cache_hit,
            "latency_ms": self.latency_ms,
            "details": self.details,
        }


@dataclass(slots=True)
class TraceRecorder:
    """Collects runtime spans for one request trace."""

    trace_id: str
    channel: str
    user_id: str | None = None
    specialist: str | None = None
    spans: list[RecordedSpan] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        channel: str,
        user_id: str | None = None,
        trace_id: str | None = None,
        specialist: str | None = None,
    ) -> TraceRecorder:
        return cls(
            trace_id=trace_id or str(uuid.uuid4()),
            channel=channel,
            user_id=user_id,
            specialist=specialist,
        )

    def add_span(
        self,
        *,
        name: str,
        span_kind: TraceSpanKind | str,
        parent_span_id: str | None = None,
        specialist: str | None = None,
        status: TraceSpanStatus | str = TraceSpanStatus.SUCCESS,
        error_class: str | None = None,
        model: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        tool_name: str | None = None,
        cache_hit: bool | None = None,
        latency_ms: int | None = None,
        details: dict[str, Any] | None = None,
        span_id: str | None = None,
    ) -> str:
        """Append a completed span to the trace."""
        resolved_id = span_id or str(uuid.uuid4())
        self.spans.append(
            RecordedSpan(
                id=resolved_id,
                trace_id=self.trace_id,
                parent_span_id=parent_span_id,
                name=name,
                span_kind=str(span_kind),
                channel=self.channel,
                specialist=specialist or self.specialist,
                status=str(status),
                error_class=error_class,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tool_name=tool_name,
                cache_hit=cache_hit,
                latency_ms=latency_ms,
                details=details or {},
            ),
        )
        return resolved_id

    @contextmanager
    def timed_span(
        self,
        *,
        name: str,
        span_kind: TraceSpanKind | str,
        parent_span_id: str | None = None,
        specialist: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
    ):
        """Context manager that records latency and failure state automatically."""
        start = time.monotonic()
        span_id = str(uuid.uuid4())
        span_data: dict[str, Any] = {
            "span_id": span_id,
            "details": {},
            "status": TraceSpanStatus.SUCCESS,
            "cache_hit": None,
            "tokens_in": None,
            "tokens_out": None,
            "error_class": None,
            "model": model,
        }

        try:
            yield span_data
        except Exception as exc:
            self.add_span(
                span_id=span_id,
                name=name,
                span_kind=span_kind,
                parent_span_id=parent_span_id,
                specialist=specialist,
                status=TraceSpanStatus.ERROR,
                error_class=type(exc).__name__,
                model=span_data.get("model") or model,
                tokens_in=span_data.get("tokens_in"),
                tokens_out=span_data.get("tokens_out"),
                tool_name=tool_name,
                cache_hit=span_data.get("cache_hit"),
                latency_ms=int((time.monotonic() - start) * 1000),
                details=span_data.get("details") or {},
            )
            raise

        self.add_span(
            span_id=span_id,
            name=name,
            span_kind=span_kind,
            parent_span_id=parent_span_id,
            specialist=specialist,
            status=span_data.get("status", TraceSpanStatus.SUCCESS),
            error_class=span_data.get("error_class"),
            model=span_data.get("model") or model,
            tokens_in=span_data.get("tokens_in"),
            tokens_out=span_data.get("tokens_out"),
            tool_name=tool_name,
            cache_hit=span_data.get("cache_hit"),
            latency_ms=int((time.monotonic() - start) * 1000),
            details=span_data.get("details") or {},
        )


def get_or_create_trace_recorder(
    metadata: dict[str, Any],
    *,
    channel: str,
    user_id: str | None = None,
) -> TraceRecorder:
    """Return the TraceRecorder stored in metadata, creating one when absent."""
    existing = metadata.get("_trace_recorder")
    if isinstance(existing, TraceRecorder):
        return existing

    recorder = TraceRecorder.create(
        channel=channel,
        user_id=user_id,
        trace_id=metadata.get("trace_id") or metadata.get("request_id"),
    )
    metadata["_trace_recorder"] = recorder
    metadata["trace_id"] = recorder.trace_id
    return recorder
