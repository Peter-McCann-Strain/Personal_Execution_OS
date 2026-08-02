"""Response quality, rendering, and shadow-workflow projections for chat."""

from __future__ import annotations

from hashlib import blake2s
from numbers import Real

from src.app.core.evaluator import EvaluationResult
from src.app.core.response_envelope import build_response_envelope, render_response_envelope
from src.app.core.response_style import normalize_response
from src.app.core.trace import TraceRecorder
from src.app.core.workflow_runtime import LiveWorkflowOutcome
from src.app.core.workflow_shadow import ShadowWorkflowOutcome
from src.app.domain.constants import EvalStatus, TraceSpanKind, WorkflowStatus
from src.app.domain.models import (
    ChatResponse,
    Intent,
    MessageInput,
    ResponseEnvelope,
    ResponseQuality,
)
from src.app.domain.services._chat_context import (
    build_supporting_context_citations,
    supporting_context_source_summaries,
)


def post_process_response(
    *,
    response: ChatResponse,
    message: MessageInput,
    intent: Intent,
    evaluation: EvaluationResult,
    retrieved_chunks: list[dict],
    context_inspection: dict,
    trace_recorder: TraceRecorder,
    request_span_id: str,
    workflow_id: str,
    workflow_status: WorkflowStatus,
    live_workflow_outcome: LiveWorkflowOutcome | None,
) -> tuple[ChatResponse, ResponseQuality, ResponseEnvelope, dict]:
    """Normalize, score, envelop, and render the routed response."""
    response = normalize_response(response, message=message, intent=intent)
    if retrieved_chunks:
        response.metadata.setdefault(
            "supporting_context_sources",
            supporting_context_source_summaries(retrieved_chunks),
        )
        if not isinstance(response.metadata.get("citations"), list):
            response.metadata["citations"] = build_supporting_context_citations(retrieved_chunks)

    quality_record = coerce_quality_record(
        evaluation,
        route_quality=1.0 if response.agent == str(intent.specialist) else 0.0,
    )
    if quality_record.context_quality is None:
        quality_record.context_quality = derive_context_quality(context_inspection)
    if quality_record.tool_use_quality is None:
        quality_record.tool_use_quality = derive_tool_use_quality(response)
    if quality_record.final_response_quality is None:
        quality_record.final_response_quality = 1.0 if quality_record.passes else 0.5
    if quality_record.channel_style is None:
        quality_record.channel_style = 1.0

    response.metadata["trace_id"] = trace_recorder.trace_id
    response.metadata["workflow_id"] = workflow_id
    response.metadata["workflow_status"] = str(workflow_status)
    response.metadata["quality"] = quality_record.model_dump(mode="json")
    if live_workflow_outcome is not None:
        response.metadata["workflow_runtime"] = live_workflow_outcome.model_dump(
            mode="json",
            exclude={"response"},
        )

    envelope = build_response_envelope(
        response,
        message=message,
        intent=intent,
        quality=quality_record,
    )
    envelope.trace_id = trace_recorder.trace_id
    envelope.workflow_id = workflow_id
    envelope.workflow_status = str(workflow_status)
    response.metadata["response_id"] = envelope.response_id

    with trace_recorder.timed_span(
        name=f"render.{message.source}",
        span_kind=TraceSpanKind.RENDER,
        parent_span_id=request_span_id,
        specialist=str(intent.specialist),
    ) as render_span:
        rendered_content, channel_metrics = render_response_envelope(
            envelope,
            message=message,
            metadata=response.metadata,
        )
        channel_metrics.update(
            assistant_native_channel_metrics(
                message=message,
                response=response,
            )
        )
        render_span["details"] = channel_metrics

    response = response.model_copy(
        update={
            "content": rendered_content,
            "metadata": {
                **response.metadata,
                "trace_id": trace_recorder.trace_id,
                "workflow_id": workflow_id,
                "workflow_status": str(workflow_status),
                "response_id": envelope.response_id,
                "quality": quality_record.model_dump(mode="json"),
                "channel_metrics": channel_metrics,
                "_response_envelope": envelope.model_dump(mode="json"),
            },
        }
    )
    return response, quality_record, envelope, channel_metrics


def derive_context_quality(context_inspection: dict) -> float:
    """Derive a conservative context quality score from assembly metadata."""
    total_tokens = int(context_inspection.get("total_tokens_estimate", 0) or 0)
    pruned = int(context_inspection.get("pruned_messages", 0) or 0)
    rag_filtered = int(context_inspection.get("rag_chunks_filtered", 0) or 0)

    if total_tokens == 0:
        return 0.5
    if pruned == 0 and rag_filtered == 0:
        return 0.95
    if rag_filtered > 0 or pruned > 0:
        return 0.8
    return 0.7


def assistant_native_channel_metrics(
    *,
    message: MessageInput,
    response: ChatResponse,
) -> dict[str, object]:
    """Project assistant-native continuity and receipt signals into channel metrics."""
    continuity = message.metadata.get("continuity_resolution")
    if not isinstance(continuity, dict):
        continuity = response.metadata.get("continuity_resolution")
    continuity_type = continuity.get("type") if isinstance(continuity, dict) else None
    continuity_type = continuity_type if isinstance(continuity_type, str) else None

    return {
        "continuity_resolution_type": continuity_type,
        "continuity_retry_replayed": continuity_type
        in {
            "retry_pending_action",
            "retry_recent_artifact",
        },
        "continuity_duplicate_prevented": continuity_type == "already_completed_action",
        "continuity_note_reference_resolved": continuity_type == "resolved_note_reference",
        "assistant_receipt_present": isinstance(response.metadata.get("receipt_text"), str),
        "pending_action_cleared": bool(
            response.metadata.get("pending_conversation_action_cleared", False)
        ),
        "project_draft_created": bool(response.metadata.get("draft_created", False)),
        "project_draft_id": str(response.metadata.get("project_draft_id"))
        if response.metadata.get("project_draft_id")
        else None,
    }


def derive_tool_use_quality(response: ChatResponse) -> float | None:
    """Derive a lightweight tool-use quality score from response metadata."""
    tool_count = response.metadata.get("tool_count")
    if tool_count in (None, 0):
        return None
    errors = int(response.metadata.get("errors", 0) or 0)
    if errors <= 0:
        return 0.95
    return max(0.3, 1.0 - (errors * 0.3))


def coerce_quality_record(
    evaluation: object,
    *,
    route_quality: float | None,
) -> ResponseQuality:
    """Convert evaluator output into a ResponseQuality, tolerating test doubles."""
    if isinstance(evaluation, ResponseQuality):
        return evaluation

    to_quality_record = getattr(evaluation, "to_quality_record", None)
    if callable(to_quality_record):
        candidate = to_quality_record(route_quality=route_quality)
        if isinstance(candidate, ResponseQuality):
            return candidate

    return ResponseQuality(
        route_quality=route_quality,
        context_quality=coerce_optional_score(getattr(evaluation, "context_quality", None)),
        tool_use_quality=coerce_optional_score(getattr(evaluation, "tool_use_quality", None)),
        final_response_quality=coerce_optional_score(
            getattr(evaluation, "final_response_quality", None)
        ),
        grounding=coerce_optional_score(getattr(evaluation, "grounding", None)),
        channel_style=coerce_optional_score(getattr(evaluation, "channel_style", None)),
        passes=bool(getattr(evaluation, "passes", True)),
        issue=str(getattr(evaluation, "issue", "")),
        suggestion=str(getattr(evaluation, "suggestion", "")),
    )


def coerce_optional_score(value: object) -> float | None:
    """Return a numeric score or None for non-numeric test doubles."""
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value)
    return None


def should_sample_runtime_evaluation(*, trace_id: str, sample_rate: float) -> bool:
    """Deterministically sample interactions for async evaluation."""
    if sample_rate <= 0.0:
        return False
    if sample_rate >= 1.0:
        return True
    digest = blake2s(trace_id.encode("utf-8"), digest_size=4).digest()
    bucket = int.from_bytes(digest, "big") / 0xFFFFFFFF
    return bucket < sample_rate


def runtime_eval_status(sampled_for_async_eval: bool) -> str:
    """Return the persisted evaluation lifecycle state for this interaction."""
    if sampled_for_async_eval:
        return str(EvalStatus.PENDING)
    return str(EvalStatus.SKIPPED)


def shadow_workflow_summary(outcome: ShadowWorkflowOutcome) -> str:
    """Return a compact operator-facing summary for one shadow run."""
    match = "match" if outcome.route_match else "mismatch"
    shadow_specialist = outcome.shadow_specialist or "unknown"
    return (
        f"shadow {outcome.status}: live={outcome.live_specialist} "
        f"shadow={shadow_specialist} {match}"
    )[:500]


def shadow_workflow_details(outcome: ShadowWorkflowOutcome) -> dict:
    """Project a shadow outcome into workflow metadata."""
    return {
        "live_workflow_id": outcome.live_workflow_id,
        "live_specialist": outcome.live_specialist,
        "shadow_specialist": outcome.shadow_specialist,
        "route_match": outcome.route_match,
        "shadow_status": outcome.status,
        "executed": outcome.executed,
        "skipped_reason": outcome.skipped_reason,
        "confidence": outcome.confidence,
        "latency_ms": outcome.latency_ms,
        "result_preview": outcome.result_preview,
    }
