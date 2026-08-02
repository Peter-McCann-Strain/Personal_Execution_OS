"""Specialist execution and response evaluation stages for chat."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import Settings
from src.app.core.conversation_actions import ContinuityResolution
from src.app.core.evaluator import (
    EvaluationResult,
    evaluate_response_deterministic,
)
from src.app.core.exceptions import AppError, EvaluationError
from src.app.core.llm_helpers import call_and_extract_text
from src.app.core.trace import TraceRecorder
from src.app.core.workflow_runtime import LiveWorkflowOutcome
from src.app.domain.constants import TraceSpanKind, TraceSpanStatus
from src.app.domain.models import ChatResponse, Intent, MessageInput

logger = structlog.get_logger()
SpecialistHandler = Callable[
    [MessageInput, AsyncAnthropic, AsyncSession, Intent],
    Awaitable[ChatResponse],
]


class LiveWorkflowExecutor(Protocol):
    """Callable boundary for the optional live workflow runtime."""

    async def __call__(
        self,
        *,
        message: MessageInput,
        intent: Intent,
        client: AsyncAnthropic,
        session: AsyncSession,
        trace_recorder: TraceRecorder,
        parent_span_id: str | None,
        settings: Settings | None = None,
    ) -> LiveWorkflowOutcome | None: ...


class ResponseEvaluator(Protocol):
    """Callable boundary for the optional synchronous LLM evaluator."""

    async def __call__(
        self,
        user_message: str,
        response_content: str,
        specialist: str,
        client: AsyncAnthropic,
        *,
        source: str = "api",
        context_inspection: dict | None = None,
        response_metadata: dict | None = None,
    ) -> EvaluationResult: ...


async def handle_conversational_intent(
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


async def execute_specialist_stage(
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
    live_workflow_executor: LiveWorkflowExecutor,
) -> tuple[ChatResponse, LiveWorkflowOutcome | None]:
    """Run continuity, live workflow, or the routed specialist handler."""
    live_workflow_outcome: LiveWorkflowOutcome | None = None
    try:
        response = continuity_resolution.early_response
        if response is None:
            live_workflow_outcome = await live_workflow_executor(
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
        specialist_label = str(intent.specialist).split(".")[-1] or "specialist"
        raise AppError(f"{specialist_label}_dependency_failed: {type(exc).__name__}") from exc

    return response, live_workflow_outcome


async def evaluate_and_optimize_response(
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
    response_evaluator: ResponseEvaluator,
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
                evaluation = await response_evaluator(
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
