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

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import get_settings
from src.app.core.confirmation import is_explicit_confirmation, is_explicit_rejection
from src.app.core.context_manager import AssembledContext, assemble_context
from src.app.core.conversation import ConversationContext
from src.app.core.conversation_actions import ContinuityResolution, resolve_conversation_continuity
from src.app.core.evaluator import evaluate_response
from src.app.core.exceptions import ConfigError
from src.app.core.observability import calculate_cost
from src.app.core.security import trust_label_for_message_source
from src.app.core.state_packet import build_session_state_packet, merge_persisted_artifacts
from src.app.core.trace import get_or_create_trace_recorder
from src.app.core.workflow_runtime import maybe_execute_live_workflow
from src.app.core.workflow_shadow import maybe_run_shadow_workflow
from src.app.domain.constants import TraceSpanKind, TraceSpanStatus, WorkflowStatus
from src.app.domain.models import (
    ArtifactRecord,
    ChatResponse,
    Intent,
    IntentType,
    MessageInput,
    PendingConversationAction,
    PendingPlanningSession,
    PendingToolPlan,
    SessionStatePacket,
    Specialist,
    WorkflowState,
)
from src.app.domain.services._chat_context import (
    build_context_inspection as _build_context_inspection,
)
from src.app.domain.services._chat_context import (
    build_specialist_message as _build_specialist_message,
)
from src.app.domain.services._chat_context import (
    normalize_context_result as _normalize_context_result,
)
from src.app.domain.services._chat_context import (
    retrieve_supporting_context as _retrieve_supporting_context,
)
from src.app.domain.services._chat_context import (
    should_skip_retrieval as _should_skip_retrieval,
)
from src.app.domain.services._chat_context import (
    touch_retrieved_saved_memories as _touch_retrieved_saved_memories,
)
from src.app.domain.services._chat_execution import (
    evaluate_and_optimize_response as _evaluate_and_optimize_response,
)
from src.app.domain.services._chat_execution import (
    execute_specialist_stage as _execute_specialist_stage,
)
from src.app.domain.services._chat_execution import (
    handle_conversational_intent as _handle_conversational_intent,
)
from src.app.domain.services._chat_persistence import (
    persist_recorded_trace as persist_recorded_trace,
)
from src.app.domain.services._chat_persistence import (
    record_workflow_step as _record_workflow_step,
)
from src.app.domain.services._chat_persistence import (
    sync_approval_request_for_response as _sync_approval_request_for_response,
)
from src.app.domain.services._chat_persistence import (
    upsert_workflow_run_record as _upsert_workflow_run_record,
)
from src.app.domain.services._chat_quality import (
    coerce_quality_record as _coerce_quality_record,
)
from src.app.domain.services._chat_quality import (
    post_process_response as _post_process_response,
)
from src.app.domain.services._chat_quality import (
    runtime_eval_status as _runtime_eval_status,
)
from src.app.domain.services._chat_quality import (
    shadow_workflow_details as _shadow_workflow_details,
)
from src.app.domain.services._chat_quality import (
    shadow_workflow_summary as _shadow_workflow_summary,
)
from src.app.domain.services._chat_quality import (
    should_sample_runtime_evaluation as _should_sample_runtime_evaluation,
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
from src.app.domain.services.orchestrator import classify_intent
from src.app.domain.services.web_push import dispatch_web_push_for_approval
from src.app.persistence.repositories.interactions import create_interaction
from src.app.persistence.repositories.runtime_records import (
    create_artifact_record,
    create_workflow_run,
    get_latest_pending_workflow_checkpoint_for_user,
    list_recent_artifacts_for_user,
)

logger = structlog.get_logger()
SpecialistHandler = Callable[
    [MessageInput, AsyncAnthropic, AsyncSession, Intent],
    Awaitable[ChatResponse],
]
__all__ = [
    "_coerce_quality_record",
    "_get_conversation_context",
    "_normalize_context_result",
    "_retrieve_supporting_context",
    "persist_recorded_trace",
    "process_message",
]


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
            live_workflow_executor=maybe_execute_live_workflow,
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
            response_evaluator=evaluate_response,
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
