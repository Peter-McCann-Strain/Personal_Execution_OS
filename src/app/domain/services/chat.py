"""Chat service — main entry point for processing user messages.

Routes through supervisor -> specialist -> response.
Specialist failures now surface as real errors instead of canned assistant replies.
Uses deterministic in-band quality checks and sampled async scoring for richer evals.
Records InteractionRecords for the self-improvement pipeline.

Context engineering: uses hierarchical memory with summarize-first strategy.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from hashlib import blake2s
from numbers import Real

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import Settings, get_settings
from src.app.core.confirmation import is_explicit_confirmation, is_explicit_rejection
from src.app.core.context_engine import ContextInspection
from src.app.core.context_manager import AssembledContext, assemble_context
from src.app.core.conversation import ConversationContext
from src.app.core.conversation_actions import ContinuityResolution, resolve_conversation_continuity
from src.app.core.evaluator import (
    EvaluationResult,
    evaluate_response,
    evaluate_response_deterministic,
)
from src.app.core.exceptions import AppError, ConfigError, EvaluationError
from src.app.core.llm_helpers import call_and_extract_text
from src.app.core.observability import calculate_cost
from src.app.core.response_envelope import build_response_envelope, render_response_envelope
from src.app.core.response_style import normalize_response
from src.app.core.security import trust_label_for_message_source
from src.app.core.state_packet import build_session_state_packet, merge_persisted_artifacts
from src.app.core.telemetry import get_telemetry
from src.app.core.trace import TraceRecorder, get_or_create_trace_recorder
from src.app.core.workflow_runtime import (
    LiveWorkflowOutcome,
    maybe_execute_live_workflow,
)
from src.app.core.workflow_shadow import ShadowWorkflowOutcome, maybe_run_shadow_workflow
from src.app.domain.constants import EvalStatus, TraceSpanKind, TraceSpanStatus, WorkflowStatus
from src.app.domain.models import (
    ArtifactRecord,
    ChatResponse,
    Intent,
    IntentType,
    MessageInput,
    PendingConversationAction,
    PendingPlanningSession,
    PendingToolPlan,
    ResponseEnvelope,
    ResponseQuality,
    SessionStatePacket,
    Specialist,
    WorkflowState,
)
from src.app.domain.services.day_plans import planning_session_is_active
from src.app.domain.services.handlers import (
    handle_communications,
    handle_diary,
    handle_memory,
    handle_notification,
    handle_plan_day,
    handle_project,
    handle_research,
    handle_review,
    handle_save,
    handle_socratic,
    handle_tools,
)
from src.app.domain.services.handlers.memory import (
    _dedupe_chunks as _dedupe_retrieved_chunks,
)
from src.app.domain.services.handlers.memory import (
    _extract_query as _extract_retrieval_query,
)
from src.app.domain.services.handlers.memory import (
    _retrieve_context as _retrieve_memory_context,
)
from src.app.domain.services.handlers.memory import (
    _retrieve_interaction_context as _retrieve_interaction_context,
)
from src.app.domain.services.orchestrator import classify_intent
from src.app.domain.services.web_push import dispatch_web_push_for_approval
from src.app.persistence.repositories.interactions import create_interaction
from src.app.persistence.repositories.runtime_records import (
    create_approval_request,
    create_artifact_record,
    create_workflow_run,
    create_workflow_run_step,
    get_latest_pending_workflow_checkpoint_for_user,
    get_pending_approval_request_for_checkpoint,
    list_recent_artifacts_for_user,
    resolve_approval_request,
    update_workflow_run,
)
from src.app.persistence.repositories.saved_memories import (
    mark_saved_memories_used as mark_retrieved_saved_memories_used,
)
from src.app.persistence.repositories.traces import create_trace_spans

logger = structlog.get_logger()
SpecialistHandler = Callable[
    [MessageInput, AsyncAnthropic, AsyncSession, Intent],
    Awaitable[ChatResponse],
]


def _normalize_context_result(
    result: object,
    *,
    conversation_messages: list[dict[str, str]],
    conversation_summary: str,
    user_message: str,
) -> tuple[object, ContextInspection | None]:
    """Normalize context-engine results for backward-compatible callers."""
    del conversation_messages, conversation_summary, user_message

    if hasattr(result, "assembled") and hasattr(result, "inspection"):
        wrapped = result
        return wrapped.assembled, wrapped.inspection

    if hasattr(result, "conversation_context") and hasattr(result, "rag_context"):
        return result, None

    msg = f"Unsupported context result type: {type(result)!r}"
    raise TypeError(msg)


async def _upsert_workflow_run_record(
    session: AsyncSession,
    *,
    workflow_id: str,
    status: str,
    source: str,
    user_id: str,
    message_content: str,
    trace_id: str | None,
    interaction_id: str | None = None,
    specialist: str | None = None,
    response_id: str | None = None,
    flags: list[str] | None = None,
    details: dict | None = None,
) -> bool:
    """Create or update the workflow run backing the current interaction."""
    updated = await update_workflow_run(
        session,
        workflow_id,
        status=status,
        specialist=specialist,
        trace_id=trace_id,
        response_id=response_id,
        details=details,
    )
    if updated:
        return True

    await create_workflow_run(
        session,
        WorkflowState(
            workflow_id=workflow_id,
            status=status,
            source=source,
            user_id=user_id,
            message_content=message_content,
            trace_id=trace_id,
            interaction_id=interaction_id,
            specialist=specialist,
            flags=flags or [],
            details=details or {},
        ),
    )
    return True


async def _recover_pending_tool_plan_from_checkpoint(
    session: AsyncSession,
    *,
    user_id: str,
) -> PendingToolPlan | None:
    """Recover a pending tool confirmation plan from durable workflow checkpoints."""
    checkpoint = await get_latest_pending_workflow_checkpoint_for_user(
        session,
        user_id=user_id,
    )
    if checkpoint is None:
        return None

    payload = getattr(checkpoint, "payload", None)
    if not isinstance(payload, dict):
        return None

    recovered_payload = dict(payload)
    recovered_payload.setdefault("workflow_id", str(getattr(checkpoint, "workflow_id", "")))
    recovered_payload.setdefault("checkpoint_id", str(getattr(checkpoint, "id", "")))
    try:
        return PendingToolPlan.model_validate(recovered_payload)
    except Exception:
        logger.warning("pending_tool_plan_checkpoint_invalid", exc_info=True)
        return None


async def _record_workflow_step(
    session: AsyncSession,
    *,
    workflow_id: str,
    step_type: str,
    title: str,
    status: str = "completed",
    details: dict | None = None,
) -> None:
    """Persist a workflow timeline step without breaking the main request on failure."""
    try:
        await create_workflow_run_step(
            session,
            workflow_id=workflow_id,
            step_type=step_type,
            title=title,
            status=status,
            details=details or {},
        )
    except Exception:
        logger.warning("workflow_step_persist_failed", exc_info=True)


async def _sync_approval_request_for_response(
    session: AsyncSession,
    *,
    workflow_id: str,
    pending_tool_plan: PendingToolPlan | None,
    pending_resolution: str | None,
    response: ChatResponse,
) -> str | None:
    """Create or resolve product-level approval requests around tool checkpoints."""
    checkpoint_id = pending_tool_plan.checkpoint_id if pending_tool_plan is not None else None
    if response.metadata.get("confirmation_required"):
        raw_pending_plan = response.metadata.get("pending_tool_plan")
        if isinstance(raw_pending_plan, dict):
            checkpoint_id = raw_pending_plan.get("checkpoint_id") or checkpoint_id
        existing = await get_pending_approval_request_for_checkpoint(
            session,
            workflow_id=workflow_id,
            checkpoint_id=checkpoint_id,
        )
        if existing is None:
            tool_names = response.metadata.get("tools_pending") or []
            approval = await create_approval_request(
                session,
                workflow_id=workflow_id,
                checkpoint_id=checkpoint_id,
                title="Approval required to continue",
                description=(
                    f"Confirm before executing: {', '.join(tool_names)}"
                    if isinstance(tool_names, list) and tool_names
                    else "Confirm before executing the pending tool action."
                ),
                payload={
                    "tool_names": tool_names,
                    "response_excerpt": response.content[:300],
                },
            )
            response.metadata["approval_request_id"] = str(approval.id)
            return str(approval.id)
        return None

    if pending_resolution is None or checkpoint_id is None:
        return None

    existing = await get_pending_approval_request_for_checkpoint(
        session,
        workflow_id=workflow_id,
        checkpoint_id=checkpoint_id,
    )
    if existing is None:
        return None
    await resolve_approval_request(
        session,
        approval_id=str(existing.id),
        status="approved" if pending_resolution == "confirm" else "rejected",
        payload={
            **(existing.payload or {}),
            "response_excerpt": response.content[:300],
        },
    )
    return None


async def _handle_conversational_intent(
    message: MessageInput,
    client: AsyncAnthropic,
    *,
    settings: Settings,
    specialist_context: str,
    workflow_id: str,
) -> ChatResponse:
    """Answer general conversational turns without routing to a specialist handler."""
    system = (
        "You are the user's personal AI assistant. "
        "Answer the question directly and helpfully. "
        "Use your training knowledge to respond to factual, comparison, "
        "or general questions. "
        "If asked about live data (weather, prices, current events) "
        "explain clearly that you don't have real-time access and "
        "suggest where to find it. "
        "Format responses for Telegram: use HTML tags (<b>, <i>, <code>) sparingly, "
        "keep it concise unless depth is explicitly requested. "
        "Do not offer a list of capabilities unless asked what you can do."
    )
    if specialist_context:
        system += f"\n\n<context>\n{specialist_context}\n</context>"
    try:
        answer = await call_and_extract_text(
            client,
            model=settings.memory_model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": message.content}],
            error_context="conversational",
            timeout_seconds=60.0,
            inject_personality=True,
        )
    except Exception as exc:
        logger.warning("conversational_llm_failed", error=str(exc))
        answer = (
            "I'm not sure what you'd like me to do with that.\n\n"
            "<b>I handle:</b>\n"
            "• 📝 <b>Diary</b> — capture thoughts, mood, daily events\n"
            "• 🔍 <b>Memory</b> — search everything you've captured\n"
            "• 📋 <b>Projects</b> — tasks, planning, prioritisation\n"
            "• 📅 <b>Calendar / Email</b> — schedule and communications\n"
            "• 🔔 <b>Reminders</b> — alerts and notifications\n"
            "• 📊 <b>Review</b> — weekly/quarterly review and patterns\n\n"
            "What would you like me to do?"
        )
    return ChatResponse(
        content=answer,
        agent="conversational",
        metadata={"specialist": "conversational", "workflow_id": workflow_id},
    )


def _get_specialist_handler(specialist: Specialist) -> SpecialistHandler:
    """Resolve the current specialist handler, preserving test-time monkeypatching."""
    handlers: dict[Specialist, SpecialistHandler] = {
        Specialist.DIARY: handle_diary,
        Specialist.MEMORY: handle_memory,
        Specialist.RESEARCH: handle_research,
        Specialist.REVIEW: handle_review,
        Specialist.PROJECT: handle_project,
        Specialist.COMMUNICATIONS: handle_communications,
        Specialist.TOOLS: handle_tools,
        Specialist.NOTIFICATION: handle_notification,
        Specialist.SAVE: handle_save,
        Specialist.PLAN_DAY: handle_plan_day,
        Specialist.SOCRATIC: handle_socratic,
    }
    handler = handlers.get(specialist)
    if handler is None:
        logger.error("no_handler_for_specialist", specialist=specialist)
        raise ConfigError(f"No handler configured for specialist '{specialist}'.")
    return handler


def _build_context_inspection(
    inspection: ContextInspection | None,
    *,
    assembled: AssembledContext,
    state_packet: SessionStatePacket | None,
    pending_tool_plan: PendingToolPlan | None,
    pending_planning_session: PendingPlanningSession | None,
    planning_session_active: bool,
    pending_conversation_action: PendingConversationAction | None,
) -> dict:
    """Build the diagnostic context packet passed through specialist metadata."""
    if inspection is not None:
        return inspection.model_dump(mode="json")

    return {
        "history_summarized": assembled.history_summarized,
        "rag_chunks_included": assembled.rag_chunks_included,
        "rag_chunks_filtered": assembled.rag_chunks_filtered,
        "total_tokens_estimate": assembled.total_tokens_estimate,
        "state_packet_present": assembled.state_packet_used,
        "state_packet_tokens": assembled.state_packet_tokens,
        "state_packet": state_packet.model_dump(mode="json") if state_packet is not None else None,
        "pending_tool_plan": (
            pending_tool_plan.model_dump(mode="json") if pending_tool_plan is not None else None
        ),
        "pending_planning_session": (
            pending_planning_session.model_dump(mode="json")
            if planning_session_active and pending_planning_session is not None
            else None
        ),
        "pending_conversation_action": (
            pending_conversation_action.model_dump(mode="json")
            if pending_conversation_action is not None
            else None
        ),
    }


def _build_specialist_message(
    message: MessageInput,
    *,
    specialist_context: str,
    context_inspection: dict,
) -> MessageInput:
    """Attach assembled context to the specialist-facing message only when useful."""
    if not specialist_context:
        return message

    return MessageInput(
        content=f"{specialist_context}\n\nCurrent message: {message.content}",
        source=message.source,
        user_id=message.user_id,
        metadata={
            **message.metadata,
            "context_inspection": context_inspection,
        },
    )


async def _execute_specialist_stage(
    *,
    enriched_message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    intent: Intent,
    trace_recorder: TraceRecorder,
    request_span_id: str,
    settings: Settings,
    continuity_resolution: ContinuityResolution,
    handler: SpecialistHandler,
) -> tuple[ChatResponse, LiveWorkflowOutcome | None]:
    """Run continuity, live workflow, or the routed specialist handler."""
    live_workflow_outcome: LiveWorkflowOutcome | None = None
    try:
        response = continuity_resolution.early_response
        if response is None:
            live_workflow_outcome = await maybe_execute_live_workflow(
                message=enriched_message,
                intent=intent,
                client=client,
                session=session,
                trace_recorder=trace_recorder,
                parent_span_id=request_span_id,
                settings=settings,
            )
            if live_workflow_outcome is not None and live_workflow_outcome.response is not None:
                response = live_workflow_outcome.response
            else:
                with trace_recorder.timed_span(
                    name=f"specialist.{intent.specialist}",
                    span_kind=TraceSpanKind.SPECIALIST,
                    parent_span_id=request_span_id,
                    specialist=str(intent.specialist),
                ) as specialist_span:
                    response = await handler(enriched_message, client, session, intent)
                    specialist_span["model"] = response.metadata.get("model")
                    specialist_span["tokens_in"] = response.metadata.get("input_tokens")
                    specialist_span["tokens_out"] = response.metadata.get("output_tokens")
                    specialist_span["details"] = {
                        "agent": response.agent,
                        "tool_count": response.metadata.get("tool_count", 0),
                    }
    except AppError:
        raise
    except Exception as exc:
        logger.exception(
            "specialist_handler_error",
            specialist=intent.specialist,
            error_type=type(exc).__name__,
        )
        # Surface the specialist + underlying failure class without exposing raw exception text.
        specialist_label = str(intent.specialist).split(".")[-1] or "specialist"
        raise AppError(f"{specialist_label}_dependency_failed: {type(exc).__name__}") from exc

    return response, live_workflow_outcome


async def _evaluate_and_optimize_response(
    *,
    response: ChatResponse,
    handler: SpecialistHandler,
    message: MessageInput,
    intent: Intent,
    client: AsyncAnthropic,
    session: AsyncSession,
    settings: Settings,
    trace_recorder: TraceRecorder,
    request_span_id: str,
    context_inspection: dict,
    sampled_for_async_eval: bool,
    degraded_flags: set[str],
) -> tuple[ChatResponse, EvaluationResult, bool, str | None]:
    """Run deterministic/sync evaluation and the optional optimizer retry."""
    response.metadata["evaluation_mode"] = settings.runtime_eval_mode
    response.metadata["async_evaluation_scheduled"] = sampled_for_async_eval

    with trace_recorder.timed_span(
        name="evaluation.runtime",
        span_kind=TraceSpanKind.EVALUATION,
        parent_span_id=request_span_id,
        specialist=str(intent.specialist),
    ) as evaluation_span:
        evaluation = evaluate_response_deterministic(
            user_message=message.content,
            response_content=response.content,
            specialist=str(intent.specialist),
            source=message.source,
            context_inspection=context_inspection,
            response_metadata=response.metadata,
        )
        evaluation_degraded = False
        if settings.runtime_eval_mode == "sync":
            try:
                evaluation = await evaluate_response(
                    user_message=message.content,
                    response_content=response.content,
                    specialist=intent.specialist,
                    client=client,
                    source=message.source,
                    context_inspection=context_inspection,
                    response_metadata=response.metadata,
                )
            except Exception as exc:
                logger.error("response_evaluation_unavailable", exc_info=True)
                evaluation_span["status"] = TraceSpanStatus.DEGRADED
                evaluation_span["error_class"] = type(exc).__name__
                evaluation_degraded = True
                response.metadata["evaluation_degraded"] = True
                response.metadata["evaluation_error"] = type(exc).__name__
                degraded_flags.add("evaluation")

        evaluation_span["details"] = {
            "mode": settings.runtime_eval_mode,
            "passes": evaluation.passes,
            "issue": evaluation.issue,
            "final_response_quality": evaluation.final_response_quality,
            "degraded": evaluation_degraded,
            "async_scheduled": sampled_for_async_eval,
        }

    optimizer_triggered = False
    optimizer_issue: str | None = None

    if (
        settings.runtime_eval_mode == "sync"
        and settings.runtime_eval_optimizer_enabled
        and not evaluation.passes
        and evaluation.suggestion
    ):
        optimizer_triggered = True
        optimizer_issue = evaluation.issue
        logger.info(
            "response_evaluation_failed_retrying",
            specialist=intent.specialist,
            issue_present=bool(evaluation.issue),
        )
        retry_message = MessageInput(
            content=(
                f"{message.content}\n\n"
                f"[System note: Previous response didn't address the intent. "
                f"Issue: {evaluation.issue}. {evaluation.suggestion}]"
            ),
            source=message.source,
            user_id=message.user_id,
            metadata=message.metadata,
        )
        with trace_recorder.timed_span(
            name="evaluation.optimizer_retry",
            span_kind=TraceSpanKind.EVALUATION,
            parent_span_id=request_span_id,
            specialist=str(intent.specialist),
        ) as retry_span:
            try:
                response = await handler(retry_message, client, session, intent)
            except Exception as exc:
                logger.error("optimizer_retry_failed", exc_info=True)
                retry_span["status"] = TraceSpanStatus.ERROR
                retry_span["error_class"] = type(exc).__name__
                retry_span["details"] = {"issue": evaluation.issue}
                raise EvaluationError(
                    f"Optimizer retry failed with {type(exc).__name__}: {exc}",
                ) from exc

    return response, evaluation, optimizer_triggered, optimizer_issue


def _post_process_response(
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
            _supporting_context_source_summaries(retrieved_chunks),
        )
        if not isinstance(response.metadata.get("citations"), list):
            response.metadata["citations"] = _build_supporting_context_citations(retrieved_chunks)

    quality_record = _coerce_quality_record(
        evaluation,
        route_quality=1.0 if response.agent == str(intent.specialist) else 0.0,
    )
    if quality_record.context_quality is None:
        quality_record.context_quality = _derive_context_quality(context_inspection)
    if quality_record.tool_use_quality is None:
        quality_record.tool_use_quality = _derive_tool_use_quality(response)
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
            _assistant_native_channel_metrics(
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


async def process_message(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
) -> ChatResponse:
    """Process an incoming message end-to-end.

    1. Start timing
    2. Retrieve conversation context + rolling summary
    3. Assemble context using hierarchical memory (summarize-first)
    4. Classify intent via supervisor (Haiku)
    5. Route to specialist agent
    6. Apply deterministic quality checks and schedule async evaluation
    7. Update conversation context + rolling summary
    8. Record InteractionRecord for evaluation pipeline

    Specialist, evaluation, and persistence errors propagate to the caller.
    """
    settings = get_settings()
    start_ns = time.monotonic_ns()
    trace_recorder = get_or_create_trace_recorder(
        message.metadata,
        channel=message.source,
        user_id=message.user_id,
    )

    logger.info(
        "processing_message",
        source=message.source,
        content_length=len(message.content),
    )

    with trace_recorder.timed_span(
        name="request.process_message",
        span_kind=TraceSpanKind.REQUEST,
    ) as request_span:
        request_span["details"] = {"source": message.source}
        request_span_id = request_span["span_id"]
        workflow_id = str(message.metadata.get("workflow_id") or uuid.uuid4())
        workflow_status = WorkflowStatus.RUNNING
        degraded_flags: set[str] = set()

        conv_ctx = _get_conversation_context()
        raw_messages: list[dict[str, str]] = []
        rolling_summary = ""
        state_packet: SessionStatePacket | None = None
        pending_tool_plan: PendingToolPlan | None = None
        pending_planning_session: PendingPlanningSession | None = None
        pending_conversation_action: PendingConversationAction | None = None
        persisted_artifacts: list[object] = []
        retrieved_chunks: list[dict] = []
        pending_resolution: str | None = None
        message = message.model_copy(
            update={
                "metadata": {
                    **message.metadata,
                    "workflow_id": workflow_id,
                    "workflow_status": str(workflow_status),
                    "trust_label": str(trust_label_for_message_source(message.source)),
                }
            }
        )

        if conv_ctx and message.user_id:
            with trace_recorder.timed_span(
                name="context.fetch_session",
                span_kind=TraceSpanKind.CONTEXT,
                parent_span_id=request_span_id,
            ) as context_fetch_span:
                try:
                    context_messages = await conv_ctx.get_context(message.user_id)
                    raw_messages = [m.to_dict() for m in context_messages]
                    rolling_summary = await conv_ctx.get_summary(message.user_id)
                    state_packet = await conv_ctx.get_state_packet(message.user_id)
                    pending_tool_plan = await conv_ctx.get_pending_tool_plan(message.user_id)
                    pending_planning_session = await conv_ctx.get_pending_planning_session(
                        message.user_id
                    )
                    pending_conversation_action = await conv_ctx.get_pending_conversation_action(
                        message.user_id
                    )
                    context_fetch_span["details"] = {
                        "message_count": len(raw_messages),
                        "has_summary": bool(rolling_summary),
                        "has_state_packet": state_packet is not None,
                        "has_pending_tool_plan": pending_tool_plan is not None,
                        "has_pending_planning_session": pending_planning_session is not None,
                        "has_pending_conversation_action": (
                            pending_conversation_action is not None
                        ),
                    }
                except Exception as exc:
                    logger.error("conversation_context_unavailable", exc_info=True)
                    context_fetch_span["status"] = TraceSpanStatus.DEGRADED
                    context_fetch_span["error_class"] = type(exc).__name__
                    context_fetch_span["details"] = {
                        "message_count": 0,
                        "has_summary": False,
                        "has_state_packet": False,
                        "has_pending_tool_plan": False,
                        "has_pending_planning_session": False,
                        "has_pending_conversation_action": False,
                        "degraded": True,
                    }
                    degraded_flags.add("context_fetch")

        if message.user_id:
            with trace_recorder.timed_span(
                name="context.fetch_artifacts",
                span_kind=TraceSpanKind.CONTEXT,
                parent_span_id=request_span_id,
            ) as artifact_span:
                try:
                    persisted_artifacts = list(
                        await list_recent_artifacts_for_user(
                            session,
                            user_id=message.user_id,
                            limit=8,
                        )
                    )
                    state_packet = merge_persisted_artifacts(state_packet, persisted_artifacts)
                    artifact_span["details"] = {
                        "artifact_count": len(persisted_artifacts),
                        "state_packet_enriched": bool(persisted_artifacts),
                    }
                except Exception as exc:
                    logger.error("artifact_context_unavailable", exc_info=True)
                    artifact_span["status"] = TraceSpanStatus.DEGRADED
                    artifact_span["error_class"] = type(exc).__name__
                    artifact_span["details"] = {
                        "artifact_count": 0,
                        "degraded": True,
                    }
                    degraded_flags.add("artifact_context")

        if pending_tool_plan is None and message.user_id:
            with trace_recorder.timed_span(
                name="context.recover_pending_checkpoint",
                span_kind=TraceSpanKind.CONTEXT,
                parent_span_id=request_span_id,
            ) as checkpoint_span:
                try:
                    pending_tool_plan = await _recover_pending_tool_plan_from_checkpoint(
                        session,
                        user_id=message.user_id,
                    )
                    if pending_tool_plan is not None:
                        recovered_workflow_id = pending_tool_plan.workflow_id
                        if recovered_workflow_id:
                            workflow_id = recovered_workflow_id
                            message = message.model_copy(
                                update={
                                    "metadata": {
                                        **message.metadata,
                                        "workflow_id": workflow_id,
                                        "workflow_status": str(workflow_status),
                                    }
                                }
                            )
                        checkpoint_span["details"] = {
                            "recovered": True,
                            "plan_id": pending_tool_plan.plan_id,
                        }
                    else:
                        checkpoint_span["details"] = {"recovered": False}
                except Exception as exc:
                    logger.error("pending_tool_plan_checkpoint_recovery_failed", exc_info=True)
                    checkpoint_span["status"] = TraceSpanStatus.DEGRADED
                    checkpoint_span["error_class"] = type(exc).__name__
                    checkpoint_span["details"] = {"recovered": False, "degraded": True}
                    degraded_flags.add("pending_tool_checkpoint")

        if pending_tool_plan is not None:
            message = message.model_copy(
                update={
                    "metadata": {
                        **message.metadata,
                        "pending_tool_plan": pending_tool_plan.model_dump(mode="json"),
                    }
                }
            )
        planning_session_active = False
        if pending_planning_session is not None:
            planning_session_active = planning_session_is_active(
                pending_planning_session,
                settings=settings,
            )
            if planning_session_active:
                message = message.model_copy(
                    update={
                        "metadata": {
                            **message.metadata,
                            "pending_planning_session": pending_planning_session.model_dump(
                                mode="json"
                            ),
                        }
                    }
                )

        if bool(getattr(settings, "continuity_runtime_enabled", True)):
            continuity_resolution = resolve_conversation_continuity(
                message,
                pending_action=pending_conversation_action,
                recent_artifacts=persisted_artifacts,
            )
        else:
            continuity_resolution = ContinuityResolution(message=message)
        message = continuity_resolution.message

        with trace_recorder.timed_span(
            name="persistence.workflow_init",
            span_kind=TraceSpanKind.PERSISTENCE,
            parent_span_id=request_span_id,
        ) as workflow_init_span:
            try:
                await _upsert_workflow_run_record(
                    session,
                    workflow_id=workflow_id,
                    status=str(workflow_status),
                    source=message.source,
                    user_id=message.user_id,
                    message_content=message.content,
                    trace_id=trace_recorder.trace_id,
                    specialist=None if pending_tool_plan is None else Specialist.TOOLS.value,
                    flags=sorted(degraded_flags),
                    details={"request_channel": message.source},
                )
                await _record_workflow_step(
                    session,
                    workflow_id=workflow_id,
                    step_type="request",
                    title="Request received",
                    details={"source": message.source},
                )
            except Exception as exc:
                logger.error("workflow_run_init_failed", exc_info=True)
                workflow_init_span["status"] = TraceSpanStatus.DEGRADED
                workflow_init_span["error_class"] = type(exc).__name__
                degraded_flags.add("workflow_init")

        if message.user_id and not _should_skip_retrieval(message.content, pending_tool_plan):
            with trace_recorder.timed_span(
                name="context.retrieve_evidence",
                span_kind=TraceSpanKind.CONTEXT,
                parent_span_id=request_span_id,
            ) as retrieval_span:
                try:
                    retrieved_chunks = await _retrieve_supporting_context(
                        message,
                        session=session,
                        user_id=message.user_id,
                    )
                    await _touch_retrieved_saved_memories(
                        session,
                        user_id=message.user_id,
                        retrieved_chunks=retrieved_chunks,
                    )
                    retrieval_span["details"] = {
                        "retrieved_chunk_count": len(retrieved_chunks),
                        "degraded": False,
                    }
                except Exception as exc:
                    logger.error("supporting_context_unavailable", exc_info=True)
                    retrieval_span["status"] = TraceSpanStatus.DEGRADED
                    retrieval_span["error_class"] = type(exc).__name__
                    retrieval_span["details"] = {
                        "retrieved_chunk_count": 0,
                        "degraded": True,
                    }
                    degraded_flags.add("supporting_context")

        with trace_recorder.timed_span(
            name="context.assemble",
            span_kind=TraceSpanKind.CONTEXT,
            parent_span_id=request_span_id,
        ) as context_span:
            try:
                assembled_result = await assemble_context(
                    conversation_messages=raw_messages,
                    conversation_summary=rolling_summary,
                    state_packet=state_packet,
                    rag_chunks=retrieved_chunks,
                    user_message=message.content,
                    client=client,
                )
                assembled, _inspection = _normalize_context_result(
                    assembled_result,
                    conversation_messages=raw_messages,
                    conversation_summary=rolling_summary,
                    user_message=message.content,
                )
            except Exception as exc:
                logger.error("context_assembly_unavailable", exc_info=True)
                context_span["status"] = TraceSpanStatus.DEGRADED
                context_span["error_class"] = type(exc).__name__
                degraded_flags.add("context_assembly")
                assembled = AssembledContext(
                    conversation_context="",
                    rag_context="",
                    total_tokens_estimate=0,
                    history_summarized=False,
                    rag_chunks_included=0,
                    rag_chunks_filtered=0,
                )
                _inspection = None
            context_span["details"] = {
                "history_summarized": assembled.history_summarized,
                "rag_chunks_included": assembled.rag_chunks_included,
                "rag_chunks_filtered": assembled.rag_chunks_filtered,
                "total_tokens_estimate": assembled.total_tokens_estimate,
                "state_packet_used": assembled.state_packet_used,
                "state_packet_tokens": assembled.state_packet_tokens,
                "persisted_artifact_count": len(persisted_artifacts),
                "retrieved_chunk_count": len(retrieved_chunks),
                "degraded": "context_assembly" in degraded_flags,
            }

        context_str = assembled.conversation_context
        specialist_context = "\n\n".join(
            part for part in [assembled.conversation_context, assembled.rag_context] if part
        )
        classify_content = message.content
        if context_str:
            classify_content = f"{context_str}\n\nCurrent message: {message.content}"

        with trace_recorder.timed_span(
            name="routing.classify_intent",
            span_kind=TraceSpanKind.ROUTING,
            parent_span_id=request_span_id,
        ) as routing_span:
            if pending_tool_plan is not None and is_explicit_confirmation(message.content):
                pending_resolution = "confirm"
            elif pending_tool_plan is not None and is_explicit_rejection(message.content):
                pending_resolution = "cancel"

            if pending_resolution is not None:
                intent = Intent(
                    intent_type=IntentType.COMMAND,
                    confidence=1.0,
                    specialist=Specialist.TOOLS,
                    reasoning="Pending tool confirmation flow.",
                )
            elif continuity_resolution.forced_intent is not None:
                intent = continuity_resolution.forced_intent
            elif planning_session_active:
                intent = Intent(
                    intent_type=IntentType.PLAN_DAY,
                    confidence=1.0,
                    specialist=Specialist.PLAN_DAY,
                    reasoning="Pending daily planning or closeout session.",
                )
            else:
                intent = await classify_intent(classify_content, client)
            trace_recorder.specialist = str(intent.specialist)
            routing_span["details"] = {
                "intent_type": str(intent.intent_type),
                "specialist": str(intent.specialist),
                "confidence": intent.confidence,
                "pending_tool_plan": pending_tool_plan is not None,
                "pending_planning_session": planning_session_active,
                "pending_conversation_action": pending_conversation_action is not None,
                "pending_resolution": pending_resolution,
                "continuity_resolution": message.metadata.get("continuity_resolution"),
            }

        logger.info(
            "intent_classified",
            intent_type=intent.intent_type,
            specialist=intent.specialist,
            confidence=intent.confidence,
            history_summarized=assembled.history_summarized,
        )
        await _record_workflow_step(
            session,
            workflow_id=workflow_id,
            step_type="routing",
            title=f"Routed to {intent.specialist}",
            details={
                "intent_type": str(intent.intent_type),
                "confidence": intent.confidence,
                "pending_resolution": pending_resolution,
            },
        )

        # Conversational inputs: general questions, comparisons, knowledge queries,
        # capability meta-comments. Answer directly with Sonnet — no specialist needed.
        if intent.specialist == Specialist.CONVERSATIONAL:
            logger.info("conversational_intent_handled", reasoning=intent.reasoning)
            return await _handle_conversational_intent(
                message,
                client,
                settings=settings,
                specialist_context=specialist_context,
                workflow_id=workflow_id,
            )

        handler = _get_specialist_handler(intent.specialist)
        context_inspection = _build_context_inspection(
            _inspection,
            assembled=assembled,
            state_packet=state_packet,
            pending_tool_plan=pending_tool_plan,
            pending_planning_session=pending_planning_session,
            planning_session_active=planning_session_active,
            pending_conversation_action=pending_conversation_action,
        )
        enriched_message = _build_specialist_message(
            message,
            specialist_context=specialist_context,
            context_inspection=context_inspection,
        )

        response, live_workflow_outcome = await _execute_specialist_stage(
            enriched_message=enriched_message,
            client=client,
            session=session,
            intent=intent,
            trace_recorder=trace_recorder,
            request_span_id=request_span_id,
            settings=settings,
            continuity_resolution=continuity_resolution,
            handler=handler,
        )

        if live_workflow_outcome is not None and live_workflow_outcome.status in {
            "timeout",
            "error",
        }:
            degraded_flags.add("workflow_runtime")

        sampled_for_async_eval = _should_sample_runtime_evaluation(
            trace_id=trace_recorder.trace_id,
            sample_rate=settings.runtime_eval_sample_rate,
        ) and bool(settings.auto_judge_enabled)
        (
            response,
            evaluation,
            optimizer_triggered,
            optimizer_issue,
        ) = await _evaluate_and_optimize_response(
            response=response,
            handler=handler,
            message=message,
            intent=intent,
            client=client,
            session=session,
            settings=settings,
            trace_recorder=trace_recorder,
            request_span_id=request_span_id,
            context_inspection=context_inspection,
            sampled_for_async_eval=sampled_for_async_eval,
            degraded_flags=degraded_flags,
        )
        response, quality_record, envelope, channel_metrics = _post_process_response(
            response=response,
            message=message,
            intent=intent,
            evaluation=evaluation,
            retrieved_chunks=retrieved_chunks,
            context_inspection=context_inspection,
            trace_recorder=trace_recorder,
            request_span_id=request_span_id,
            workflow_id=workflow_id,
            workflow_status=workflow_status,
            live_workflow_outcome=live_workflow_outcome,
        )

        shadow_outcome = await maybe_run_shadow_workflow(
            live_workflow_id=workflow_id,
            live_specialist=str(intent.specialist),
            route_message=classify_content,
            specialist_message=message.content,
            context_chunks=retrieved_chunks,
            client=client,
            trace_recorder=trace_recorder,
            parent_span_id=request_span_id,
        )
        if shadow_outcome is not None:
            response.metadata["shadow_workflow"] = shadow_outcome.model_dump(mode="json")
            if shadow_outcome.status in {"error", "timeout"}:
                degraded_flags.add("workflow_shadow")

        if conv_ctx and message.user_id:
            with trace_recorder.timed_span(
                name="persistence.conversation_context",
                span_kind=TraceSpanKind.PERSISTENCE,
                parent_span_id=request_span_id,
                specialist=str(intent.specialist),
            ) as persistence_span:
                try:
                    await conv_ctx.add_message(message.user_id, "user", message.content)
                    await conv_ctx.add_message(
                        message.user_id,
                        "assistant",
                        response.content,
                        agent=response.agent,
                    )
                except Exception as exc:
                    logger.error("conversation_history_update_failed", exc_info=True)
                    persistence_span["status"] = TraceSpanStatus.DEGRADED
                    persistence_span["error_class"] = type(exc).__name__
                    degraded_flags.add("conversation_history")

                try:
                    pending_plan_payload = response.metadata.get("pending_tool_plan")
                    if response.metadata.get("pending_tool_plan_cleared"):
                        await conv_ctx.clear_pending_tool_plan(message.user_id)
                    elif isinstance(pending_plan_payload, dict):
                        await conv_ctx.set_pending_tool_plan(
                            message.user_id,
                            PendingToolPlan.model_validate(pending_plan_payload),
                        )
                except Exception as exc:
                    logger.error("pending_tool_plan_update_failed", exc_info=True)
                    persistence_span["status"] = TraceSpanStatus.DEGRADED
                    persistence_span["error_class"] = type(exc).__name__
                    degraded_flags.add("pending_tool_plan")

                try:
                    pending_action_payload = response.metadata.get("pending_conversation_action")
                    if response.metadata.get("pending_conversation_action_cleared"):
                        await conv_ctx.clear_pending_conversation_action(message.user_id)
                    elif isinstance(pending_action_payload, dict):
                        await conv_ctx.set_pending_conversation_action(
                            message.user_id,
                            PendingConversationAction.model_validate(pending_action_payload),
                        )
                except Exception as exc:
                    logger.error("pending_conversation_action_update_failed", exc_info=True)
                    persistence_span["status"] = TraceSpanStatus.DEGRADED
                    persistence_span["error_class"] = type(exc).__name__
                    degraded_flags.add("pending_conversation_action")

                try:
                    pending_planning_payload = response.metadata.get("pending_planning_session")
                    if response.metadata.get("pending_planning_session_cleared"):
                        await conv_ctx.clear_pending_planning_session(message.user_id)
                    elif isinstance(pending_planning_payload, dict):
                        await conv_ctx.set_pending_planning_session(
                            message.user_id,
                            PendingPlanningSession.model_validate(pending_planning_payload),
                        )
                    elif pending_planning_session is not None and not planning_session_active:
                        await conv_ctx.clear_pending_planning_session(message.user_id)
                except Exception as exc:
                    logger.error("pending_planning_session_update_failed", exc_info=True)
                    persistence_span["status"] = TraceSpanStatus.DEGRADED
                    persistence_span["error_class"] = type(exc).__name__
                    degraded_flags.add("pending_planning_session")

                if assembled.history_summarized and assembled.conversation_context:
                    updated_messages = [
                        *raw_messages,
                        {"role": "user", "content": message.content},
                        {"role": "assistant", "content": response.content, "agent": response.agent},
                    ]
                    try:
                        updated_summary = await _update_rolling_summary(
                            conv_ctx,
                            message.user_id,
                            updated_messages,
                            client,
                        )
                        if updated_summary:
                            rolling_summary = updated_summary
                    except Exception as exc:
                        logger.error("rolling_summary_update_failed", exc_info=True)
                        persistence_span["status"] = TraceSpanStatus.DEGRADED
                        persistence_span["error_class"] = type(exc).__name__
                        degraded_flags.add("rolling_summary")

                try:
                    packet = build_session_state_packet(
                        [
                            *raw_messages,
                            {"role": "user", "content": message.content},
                            {
                                "role": "assistant",
                                "content": response.content,
                                "agent": response.agent,
                            },
                        ],
                        conversation_summary=rolling_summary,
                        previous_packet=state_packet,
                        response=response,
                    )
                    await conv_ctx.set_state_packet(message.user_id, packet)
                    response.metadata["state_packet"] = packet.model_dump(mode="json")
                except Exception as exc:
                    logger.error("state_packet_update_failed", exc_info=True)
                    persistence_span["status"] = TraceSpanStatus.DEGRADED
                    persistence_span["error_class"] = type(exc).__name__
                    degraded_flags.add("state_packet")

        duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
        estimated_cost = _estimate_interaction_cost(response)
        if response.metadata.get("confirmation_required"):
            workflow_status = WorkflowStatus.INTERRUPTED
        elif degraded_flags:
            workflow_status = WorkflowStatus.DEGRADED
        else:
            workflow_status = WorkflowStatus.COMPLETED
        response.metadata["workflow_status"] = str(workflow_status)
        envelope.workflow_status = str(workflow_status)
        response.metadata["_response_envelope"] = envelope.model_dump(mode="json")
        interaction_eval_status = _runtime_eval_status(sampled_for_async_eval)
        response.metadata["evaluation_status"] = interaction_eval_status

        with trace_recorder.timed_span(
            name="persistence.runtime_records",
            span_kind=TraceSpanKind.PERSISTENCE,
            parent_span_id=request_span_id,
            specialist=str(intent.specialist),
        ) as runtime_records_span:
            interaction_id: str | None = None
            try:
                interaction = await create_interaction(
                    session,
                    user_id=message.user_id,
                    user_message=message.content,
                    source=message.source,
                    intent_type=intent.intent_type,
                    specialist=intent.specialist,
                    routing_confidence=intent.confidence,
                    response_content=response.content,
                    response_agent=response.agent,
                    optimizer_triggered=optimizer_triggered,
                    optimizer_issue=optimizer_issue,
                    duration_ms=duration_ms,
                    trace_id=trace_recorder.trace_id,
                    workflow_id=workflow_id,
                    workflow_status=str(workflow_status),
                    response_id=envelope.response_id,
                    quality_scores=quality_record.model_dump(mode="json"),
                    channel_metrics=channel_metrics,
                    eval_status=interaction_eval_status,
                )
                interaction_id = str(interaction.id)
                response.metadata["interaction_id"] = interaction_id
            except Exception as exc:
                runtime_records_span["status"] = TraceSpanStatus.DEGRADED
                runtime_records_span["error_class"] = type(exc).__name__
                degraded_flags.add("runtime_records")
                logger.error("interaction_record_persistence_failed", exc_info=True)
                try:
                    await session.rollback()
                except Exception:
                    logger.warning("interaction_record_rollback_failed", exc_info=True)

            try:
                await _upsert_workflow_run_record(
                    session,
                    workflow_id=workflow_id,
                    status=str(workflow_status),
                    source=message.source,
                    user_id=message.user_id,
                    message_content=message.content,
                    trace_id=trace_recorder.trace_id,
                    interaction_id=interaction_id,
                    specialist=str(intent.specialist),
                    response_id=envelope.response_id,
                    flags=sorted(degraded_flags),
                    details={
                        "response_id": envelope.response_id,
                        "quality_scores": quality_record.model_dump(mode="json"),
                        "channel_metrics": channel_metrics,
                        "workflow_runtime": response.metadata.get("workflow_runtime"),
                    },
                )
                created_approval_id = await _sync_approval_request_for_response(
                    session,
                    workflow_id=workflow_id,
                    pending_tool_plan=pending_tool_plan,
                    pending_resolution=pending_resolution,
                    response=response,
                )
                await _record_workflow_step(
                    session,
                    workflow_id=workflow_id,
                    step_type=(
                        "approval" if response.metadata.get("confirmation_required") else "response"
                    ),
                    title=(
                        "Awaiting approval"
                        if response.metadata.get("confirmation_required")
                        else "Response ready"
                    ),
                    details={
                        "agent": response.agent,
                        "tool_count": response.metadata.get("tool_count", 0),
                        "workflow_status": str(workflow_status),
                    },
                )
                await create_artifact_record(
                    session,
                    user_id=message.user_id,
                    artifact=ArtifactRecord(
                        artifact_type="response_envelope",
                        summary=response.content[:500],
                        source_id=envelope.response_id,
                        trace_id=trace_recorder.trace_id,
                        workflow_id=workflow_id,
                        payload=envelope.model_dump(mode="json"),
                    ),
                )
                if shadow_outcome is not None:
                    await create_workflow_run(
                        session,
                        WorkflowState(
                            workflow_id=shadow_outcome.workflow_id,
                            status=str(WorkflowStatus.SHADOW),
                            source=message.source,
                            user_id=message.user_id,
                            message_content=message.content,
                            trace_id=trace_recorder.trace_id,
                            specialist=shadow_outcome.shadow_specialist,
                            flags=["shadow"],
                            details=_shadow_workflow_details(shadow_outcome),
                        ),
                    )
                    await create_artifact_record(
                        session,
                        user_id=message.user_id,
                        artifact=ArtifactRecord(
                            artifact_type="workflow_shadow",
                            summary=_shadow_workflow_summary(shadow_outcome),
                            source_id=shadow_outcome.workflow_id,
                            trace_id=trace_recorder.trace_id,
                            workflow_id=shadow_outcome.workflow_id,
                            payload=shadow_outcome.model_dump(mode="json"),
                        ),
                    )
                await session.commit()
                if created_approval_id is not None:
                    try:
                        await dispatch_web_push_for_approval(
                            session,
                            user_id=message.user_id,
                            approval_id=created_approval_id,
                        )
                    except Exception:
                        logger.warning(
                            "approval_web_push_dispatch_failed",
                            approval_id=created_approval_id,
                            exc_info=True,
                        )
            except Exception as exc:
                runtime_records_span["status"] = TraceSpanStatus.DEGRADED
                runtime_records_span["error_class"] = type(exc).__name__
                degraded_flags.add("runtime_records")
                logger.error("workflow_runtime_persistence_failed", exc_info=True)
                try:
                    await session.rollback()
                except Exception:
                    logger.warning("runtime_record_rollback_failed", exc_info=True)

        if estimated_cost is not None:
            response.metadata["estimated_cost_usd"] = round(estimated_cost, 6)
        if "runtime_records" in degraded_flags:
            response.metadata["interaction_record_degraded"] = True
        if response.metadata.get("confirmation_required"):
            workflow_status = WorkflowStatus.INTERRUPTED
        elif degraded_flags:
            workflow_status = WorkflowStatus.DEGRADED
        else:
            workflow_status = WorkflowStatus.COMPLETED
        response.metadata["workflow_status"] = str(workflow_status)
        envelope.workflow_status = str(workflow_status)
        response.metadata["_response_envelope"] = envelope.model_dump(mode="json")
        if degraded_flags:
            request_span["status"] = TraceSpanStatus.DEGRADED
            request_span["details"] = {
                **request_span.get("details", {}),
                "degraded_flags": sorted(degraded_flags),
            }

        return response


async def _update_rolling_summary(
    conv_ctx: ConversationContext,
    user_id: str,
    messages: list[dict[str, str]],
    client: AsyncAnthropic,
) -> str:
    """Update the rolling session summary in Redis.

    Called after assemble_context triggers summarization. This persists the
    summary so subsequent messages can reuse it without re-summarizing.

    Raises on failure — no silent degradation.
    """
    from src.app.core.context_manager import summarize_messages

    settings = get_settings()
    summary = await summarize_messages(messages, client, model=settings.summary_model)
    if summary:
        await conv_ctx.set_summary(user_id, summary)
    return summary


def _estimate_interaction_cost(response: ChatResponse) -> float | None:
    """Estimate the USD cost of a specialist interaction from response metadata.

    Returns None if the metadata doesn't contain model/token information.
    Uses the observability module's calculate_cost for accurate pricing.
    """
    meta = response.metadata
    model = meta.get("model")
    input_tokens = meta.get("input_tokens")
    output_tokens = meta.get("output_tokens")

    if model and input_tokens is not None and output_tokens is not None:
        try:
            return calculate_cost(model, int(input_tokens), int(output_tokens))
        except (TypeError, ValueError):
            return None
    return None


async def _retrieve_supporting_context(
    message: MessageInput,
    *,
    session: AsyncSession,
    user_id: str,
) -> list[dict]:
    """Retrieve durable supporting evidence for the main chat path."""
    normalized_query = _extract_retrieval_query(message.content)
    if not normalized_query:
        return []

    suppressed_sources = _resolve_retrieval_suppressed_sources(message.metadata)

    chunks = await _retrieve_memory_context(
        normalized_query,
        session,
        user_id=user_id,
        suppressed_sources=suppressed_sources,
    )
    if user_id and "episode" not in suppressed_sources:
        chunks.extend(
            await _retrieve_interaction_context(
                normalized_query,
                session,
                user_id=user_id,
            )
        )
    return _dedupe_retrieved_chunks(chunks)


async def _touch_retrieved_saved_memories(
    session: AsyncSession,
    *,
    user_id: str,
    retrieved_chunks: list[dict],
) -> None:
    """Record that explicit saved memories influenced the current answer path."""
    memory_ids: list[uuid.UUID] = []
    for chunk in retrieved_chunks:
        if chunk.get("source_type") != "saved_memory":
            continue
        source_id = str(chunk.get("source_id") or "").strip()
        if not source_id:
            continue
        try:
            memory_ids.append(uuid.UUID(source_id))
        except ValueError:
            continue
    if not memory_ids:
        return
    await mark_retrieved_saved_memories_used(
        session,
        user_id=user_id,
        memory_ids=memory_ids,
    )


def _resolve_retrieval_suppressed_sources(metadata: dict | None) -> set[str]:
    """Normalize per-request retrieval suppression flags carried in message metadata."""
    if not isinstance(metadata, dict):
        return set()

    raw_sources = metadata.get("suppressed_sources", [])
    if isinstance(raw_sources, str):
        raw_values = [raw_sources]
    elif isinstance(raw_sources, list):
        raw_values = raw_sources
    else:
        raw_values = []

    suppressed = {str(value).strip() for value in raw_values if str(value).strip()}
    if bool(metadata.get("sensitive_mode")):
        suppressed |= {"saved_memory", "connector_document"}
    return suppressed


def _build_supporting_context_citations(retrieved_chunks: list[dict]) -> list[dict[str, str]]:
    """Convert retrieved context into lightweight citations for the response envelope."""
    citations: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in retrieved_chunks:
        source_type = str(chunk.get("source_type") or "supporting_context")
        source_id = str(chunk.get("source_id") or "").strip()
        if not source_id:
            continue
        key = (source_type, source_id)
        if key in seen:
            continue
        seen.add(key)

        metadata = chunk.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        excerpt = str(chunk.get("content") or "").strip()
        label = _supporting_context_label(
            source_type=source_type,
            source_id=source_id,
            metadata=metadata,
        )
        citation: dict[str, str] = {
            "source_id": source_id,
            "source_type": source_type,
            "label": label,
        }
        if excerpt:
            citation["excerpt"] = excerpt[:180]
        timestamp = (
            metadata.get("created_at") or metadata.get("updated_at") or metadata.get("synced_at")
        )
        if timestamp:
            citation["timestamp"] = str(timestamp)
        source_url = metadata.get("source_url") or metadata.get("web_view_link")
        if isinstance(source_url, str) and source_url.strip():
            citation["url"] = source_url.strip()
        citations.append(citation)
        if len(citations) >= 6:
            break
    return citations


def _supporting_context_source_summaries(retrieved_chunks: list[dict]) -> list[dict[str, str]]:
    """Expose retrieved source summaries in response metadata for UI inspection."""
    summaries: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in retrieved_chunks:
        source_type = str(chunk.get("source_type") or "supporting_context")
        source_id = str(chunk.get("source_id") or "").strip()
        if not source_id:
            continue
        key = (source_type, source_id)
        if key in seen:
            continue
        seen.add(key)
        metadata = chunk.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        summaries.append(
            {
                "source_type": source_type,
                "source_id": source_id,
                "label": _supporting_context_label(
                    source_type=source_type,
                    source_id=source_id,
                    metadata=metadata,
                ),
            }
        )
        if len(summaries) >= 8:
            break
    return summaries


def _supporting_context_label(
    *,
    source_type: str,
    source_id: str,
    metadata: dict[str, object],
) -> str:
    """Render a human label for a retrieved evidence source."""
    title = metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    if source_type == "episode":
        summary = metadata.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()[:80]
        return "Recent chat"
    if source_type == "note":
        return "Note"
    if source_type == "entity":
        entity_type = metadata.get("entity_type")
        return (
            f"Entity ({entity_type})"
            if isinstance(entity_type, str) and entity_type.strip()
            else "Entity"
        )
    if source_type == "saved_memory":
        return "Saved memory"
    if source_type == "connector_document":
        connector_source_type = metadata.get("connector_source_type")
        if isinstance(connector_source_type, str) and connector_source_type.strip():
            return connector_source_type.replace("_", " ").title()
        return "Synced connector data"
    if source_type == "interaction":
        return "Recent interaction"
    if source_type == "session":
        return "Session state"
    return source_id


def _should_skip_retrieval(
    content: str,
    pending_tool_plan: PendingToolPlan | None,
) -> bool:
    """Skip retrieval for pure confirmation flows where evidence adds no value."""
    if pending_tool_plan is None:
        return False
    return is_explicit_confirmation(content) or is_explicit_rejection(content)


async def persist_recorded_trace(
    session: AsyncSession,
    metadata: dict,
) -> int:
    """Persist any recorded spans attached to a message metadata dict."""
    recorder = metadata.get("_trace_recorder")
    if not isinstance(recorder, TraceRecorder):
        return 0
    if metadata.get("_trace_persisted"):
        return 0
    if not recorder.spans:
        return 0

    await create_trace_spans(
        session,
        [span.to_record() for span in recorder.spans],
    )
    await session.commit()
    get_telemetry().record_trace(recorder)
    metadata["_trace_persisted"] = True
    return len(recorder.spans)


def _derive_context_quality(context_inspection: dict) -> float:
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


def _assistant_native_channel_metrics(
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


def _derive_tool_use_quality(response: ChatResponse) -> float | None:
    """Derive a lightweight tool-use quality score from response metadata."""
    tool_count = response.metadata.get("tool_count")
    if tool_count in (None, 0):
        return None
    errors = int(response.metadata.get("errors", 0) or 0)
    if errors <= 0:
        return 0.95
    return max(0.3, 1.0 - (errors * 0.3))


def _coerce_quality_record(
    evaluation: object,
    *,
    route_quality: float | None,
):
    """Convert evaluator output into a ResponseQuality, tolerating test doubles."""
    from src.app.domain.models import ResponseQuality

    if isinstance(evaluation, ResponseQuality):
        return evaluation

    if hasattr(evaluation, "to_quality_record"):
        candidate = evaluation.to_quality_record(route_quality=route_quality)
        if isinstance(candidate, ResponseQuality):
            return candidate

    return ResponseQuality(
        route_quality=route_quality,
        context_quality=_coerce_optional_score(getattr(evaluation, "context_quality", None)),
        tool_use_quality=_coerce_optional_score(getattr(evaluation, "tool_use_quality", None)),
        final_response_quality=_coerce_optional_score(
            getattr(evaluation, "final_response_quality", None)
        ),
        grounding=_coerce_optional_score(getattr(evaluation, "grounding", None)),
        channel_style=_coerce_optional_score(getattr(evaluation, "channel_style", None)),
        passes=bool(getattr(evaluation, "passes", True)),
        issue=str(getattr(evaluation, "issue", "")),
        suggestion=str(getattr(evaluation, "suggestion", "")),
    )


def _coerce_optional_score(value: object) -> float | None:
    """Return a numeric score or None for non-numeric test doubles."""
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value)
    return None


def _should_sample_runtime_evaluation(*, trace_id: str, sample_rate: float) -> bool:
    """Deterministically sample interactions for async evaluation."""
    if sample_rate <= 0.0:
        return False
    if sample_rate >= 1.0:
        return True
    digest = blake2s(trace_id.encode("utf-8"), digest_size=4).digest()
    bucket = int.from_bytes(digest, "big") / 0xFFFFFFFF
    return bucket < sample_rate


def _runtime_eval_status(sampled_for_async_eval: bool) -> str:
    """Return the persisted evaluation lifecycle state for this interaction."""
    if sampled_for_async_eval:
        return str(EvalStatus.PENDING)
    return str(EvalStatus.SKIPPED)


def _shadow_workflow_summary(outcome: ShadowWorkflowOutcome) -> str:
    """Return a compact operator-facing summary for one shadow run."""
    match = "match" if outcome.route_match else "mismatch"
    shadow_specialist = outcome.shadow_specialist or "unknown"
    return (
        f"shadow {outcome.status}: live={outcome.live_specialist} "
        f"shadow={shadow_specialist} {match}"
    )[:500]


def _shadow_workflow_details(outcome: ShadowWorkflowOutcome) -> dict:
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


def _get_conversation_context() -> ConversationContext | None:
    """Get conversation context instance, or None if not configured.

    Returns None only when settings are genuinely unavailable (e.g. in test
    environments without .env). Configuration errors propagate.
    """
    try:
        settings = get_settings()
        return ConversationContext(redis_url=settings.redis_url.get_secret_value())
    except (ImportError, AttributeError, ValueError, OSError, RuntimeError):
        return None
