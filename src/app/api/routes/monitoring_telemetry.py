"""Trace, evaluation, channel, and webhook monitoring routes."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_db
from src.app.core.exceptions import NotFoundError
from src.app.persistence.models import InteractionRecord

from .monitoring_models import (
    ChannelMetricDTO,
    EvalOutcomeDTO,
    TelegramWebhookStatusDTO,
    TraceDetailDTO,
    TraceSummaryDTO,
)

logger = structlog.get_logger()
router = APIRouter()
_TELEGRAM_PENDING_WARNING_THRESHOLD = 10
_TELEGRAM_RECENT_ERROR_WINDOW_SECONDS = 3600


@router.get("/monitoring/traces", response_model=list[TraceSummaryDTO])
@router.get("/ops/traces", response_model=list[TraceSummaryDTO])
async def list_traces(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
) -> list[TraceSummaryDTO]:
    """Return lightweight summaries of recent request traces."""
    from src.app.api.routes import monitoring as monitoring_facade

    summaries = await monitoring_facade.summarize_traces(session, limit=limit)
    return [TraceSummaryDTO(**summary) for summary in summaries]


@router.get("/monitoring/traces/{trace_id}", response_model=TraceDetailDTO)
@router.get("/ops/traces/{trace_id}", response_model=TraceDetailDTO)
async def trace_detail(
    trace_id: str,
    session: AsyncSession = Depends(get_db),
) -> TraceDetailDTO:
    """Return full span detail for one trace."""
    from src.app.api.routes import monitoring as monitoring_facade

    detail = await monitoring_facade.get_trace_detail(session, trace_id)
    if detail is None:
        raise NotFoundError(f"Trace not found: {trace_id}")
    return TraceDetailDTO(**detail)


@router.get("/monitoring/eval-outcomes", response_model=list[EvalOutcomeDTO])
@router.get("/ops/evals", response_model=list[EvalOutcomeDTO])
async def eval_outcomes(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
) -> list[EvalOutcomeDTO]:
    """List recent evaluation outcomes with quality and renderer metadata."""
    stmt = select(InteractionRecord).order_by(InteractionRecord.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    records = list(result.scalars().all())
    return [
        EvalOutcomeDTO(
            id=str(record.id),
            trace_id=record.trace_id,
            response_id=record.response_id,
            specialist=record.specialist,
            source=record.source,
            eval_status=record.eval_status,
            quality_scores=record.quality_scores,
            channel_metrics=record.channel_metrics,
            feedback_rating=record.feedback_rating,
            created_at=record.created_at.isoformat(),
        )
        for record in records
    ]


@router.get("/monitoring/channel-metrics", response_model=list[ChannelMetricDTO])
@router.get("/ops/channel-metrics", response_model=list[ChannelMetricDTO])
async def channel_metrics(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(500, ge=1, le=5000),
) -> list[ChannelMetricDTO]:
    """Aggregate renderer/channel metrics from recent interaction records."""
    stmt = select(InteractionRecord).order_by(InteractionRecord.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    records = list(result.scalars().all())

    grouped: dict[str, list[InteractionRecord]] = {}
    for record in records:
        grouped.setdefault(record.source, []).append(record)

    metrics: list[ChannelMetricDTO] = []
    for source, source_records in grouped.items():
        latencies = [
            float(record.duration_ms) for record in source_records if record.duration_ms is not None
        ]
        chunk_counts = [
            float((record.channel_metrics or {}).get("chunk_count", 1)) for record in source_records
        ]
        retry_counts = [
            int((record.channel_metrics or {}).get("retry_count", 0)) for record in source_records
        ]
        render_failures = sum(
            1
            for record in source_records
            if (record.channel_metrics or {}).get("render_passed") is False
        )
        delivery_failures = sum(
            1
            for record in source_records
            if (record.channel_metrics or {}).get("delivery_status")
            in {"failed", "partial_failure"}
        )
        chunked_count = sum(
            1
            for record in source_records
            if float((record.channel_metrics or {}).get("chunk_count", 1)) > 1
        )
        anchors_requested = sum(
            1
            for record in source_records
            if (record.channel_metrics or {}).get("reply_anchor_requested") is True
        )
        anchors_dropped = sum(
            1
            for record in source_records
            if (record.channel_metrics or {}).get("reply_anchor_dropped") is True
        )
        callback_attempts = sum(
            int((record.channel_metrics or {}).get("feedback_callback_attempts", 0))
            for record in source_records
        )
        callback_successes = sum(
            int((record.channel_metrics or {}).get("feedback_callback_successes", 0))
            for record in source_records
        )

        interaction_count = len(source_records)
        metrics.append(
            ChannelMetricDTO(
                source=source,
                interaction_count=interaction_count,
                avg_latency_ms=round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
                avg_chunk_count=(
                    round(sum(chunk_counts) / len(chunk_counts), 2) if chunk_counts else 0.0
                ),
                render_failures=render_failures,
                delivery_failures=delivery_failures,
                delivery_success_rate=(
                    round((interaction_count - delivery_failures) / interaction_count, 3)
                    if interaction_count
                    else 1.0
                ),
                avg_retry_count=(
                    round(sum(retry_counts) / len(retry_counts), 3) if retry_counts else 0.0
                ),
                total_retry_count=sum(retry_counts),
                chunked_delivery_rate=(
                    round(chunked_count / interaction_count, 3) if interaction_count else 0.0
                ),
                reply_anchor_drop_rate=(
                    round(anchors_dropped / anchors_requested, 3) if anchors_requested else None
                ),
                feedback_callback_success_rate=(
                    round(callback_successes / callback_attempts, 3) if callback_attempts else None
                ),
            )
        )

    metrics.sort(key=lambda item: item.source)
    return metrics


@router.get("/monitoring/telegram-webhook", response_model=TelegramWebhookStatusDTO)
@router.get("/ops/webhook-status", response_model=TelegramWebhookStatusDTO)
async def telegram_webhook_status(request: Request) -> TelegramWebhookStatusDTO:
    """Expose current Telegram webhook state when the bot is configured."""
    telegram_service = getattr(request.app.state, "telegram_service", None)
    if telegram_service is None:
        return TelegramWebhookStatusDTO(status="not_configured")

    try:
        status = await telegram_service.get_webhook_status()
    except Exception:
        logger.warning("telegram_webhook_status_failed", exc_info=True)
        return TelegramWebhookStatusDTO(status="error")

    pending_update_count = status.get("pending_update_count")
    if isinstance(pending_update_count, bool):
        pending_update_count = int(pending_update_count)
    if not isinstance(pending_update_count, int):
        pending_update_count = 0

    warning_threshold = _TELEGRAM_PENDING_WARNING_THRESHOLD
    if pending_update_count >= warning_threshold:
        overall_status = "degraded"
    elif pending_update_count > 0:
        overall_status = "lagging"
    else:
        overall_status = "ok"

    now_timestamp = int(datetime.now(UTC).timestamp())
    last_error_date = status.get("last_error_date")
    if isinstance(last_error_date, bool):
        last_error_date = int(last_error_date)
    if not isinstance(last_error_date, int):
        last_error_date = None

    last_error_age_seconds: int | None = None
    if last_error_date is not None:
        last_error_age_seconds = max(now_timestamp - last_error_date, 0)

    has_recent_error = bool(status.get("last_error_message")) and (
        last_error_age_seconds is None
        or last_error_age_seconds <= _TELEGRAM_RECENT_ERROR_WINDOW_SECONDS
    )
    if has_recent_error:
        overall_status = "degraded"

    payload = dict(status)
    payload.update(
        {
            "pending_update_count": pending_update_count,
            "last_error_date": last_error_date,
            "last_error_age_seconds": last_error_age_seconds,
            "webhook_lagging": pending_update_count > 0,
            "pending_updates_warning_threshold": warning_threshold,
        }
    )
    return TelegramWebhookStatusDTO(status=overall_status, **payload)
