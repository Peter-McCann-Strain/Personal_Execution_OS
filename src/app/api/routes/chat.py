"""Chat endpoint — accepts messages, returns responses."""

import json
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import structlog
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import Principal, get_anthropic_client, get_current_principal, get_db
from src.app.core.context_engine import ContextInspection, get_default_context_engine
from src.app.core.exceptions import AppError, DatabaseError, user_safe_error_message
from src.app.core.state_packet import merge_persisted_artifacts
from src.app.domain.models import MessageInput
from src.app.domain.services.chat import (
    _get_conversation_context,
    _retrieve_supporting_context,
    persist_recorded_trace,
    process_message,
)
from src.app.persistence.repositories.runtime_records import list_recent_artifacts_for_user

logger = structlog.get_logger()
router = APIRouter()


def _current_request_id() -> str:
    """Reuse the request_id bound by RequestLoggingMiddleware so HTTP logs,
    trace spans, LLM call logs, and enqueued ARQ jobs all share one
    correlation ID. Falls back to a fresh UUID only when the middleware
    hasn't run (e.g. direct service invocation in tests).
    """
    ctx = structlog.contextvars.get_contextvars()
    bound = ctx.get("request_id")
    if isinstance(bound, str) and bound:
        return bound
    return str(uuid.uuid4())


class ChatRequest(BaseModel):
    content: Annotated[
        str,
        StringConstraints(min_length=1, max_length=50_000, strip_whitespace=True),
    ]
    source: Literal["api", "telegram", "voice"] = "api"
    sensitive_mode: bool = False
    suppressed_sources: list[str] = Field(default_factory=list)


class ChatMetadata(BaseModel):
    request_id: str
    agent_used: str
    trace_id: str | None = None
    workflow_id: str | None = None
    workflow_status: str | None = None
    response_id: str | None = None
    tokens_used: int | None = None
    latency_ms: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ChatResponseDTO(BaseModel):
    content: str
    agent: str
    metadata: ChatMetadata


class ContextInspectResponse(BaseModel):
    request_id: str
    inspection: ContextInspection


def _build_message_input(
    request: ChatRequest,
    *,
    user_id: str,
    request_id: str,
) -> MessageInput:
    return MessageInput(
        content=request.content,
        source=request.source,
        user_id=user_id,
        timestamp=datetime.now(UTC),
        metadata={
            "request_id": request_id,
            "sensitive_mode": request.sensitive_mode,
            "suppressed_sources": request.suppressed_sources,
        },
    )


def _principal_user_ref(principal: Principal) -> str:
    return principal.external_subject or principal.subject


def _build_metadata(
    *,
    request_id: str,
    response: Any,
    latency_ms: int,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "agent_used": response.agent,
        "trace_id": response.metadata.get("trace_id"),
        "workflow_id": response.metadata.get("workflow_id"),
        "workflow_status": response.metadata.get("workflow_status"),
        "response_id": response.metadata.get("response_id"),
        "tokens_used": response.metadata.get("tokens_used"),
        "latency_ms": latency_ms,
        **{key: value for key, value in response.metadata.items() if not str(key).startswith("_")},
    }


def _to_chat_response_dto(
    *,
    request_id: str,
    response: Any,
    latency_ms: int,
) -> ChatResponseDTO:
    metadata = _build_metadata(
        request_id=request_id,
        response=response,
        latency_ms=latency_ms,
    )

    return ChatResponseDTO(
        content=response.content,
        agent=response.agent,
        metadata=ChatMetadata(
            request_id=request_id,
            agent_used=response.agent,
            trace_id=metadata.get("trace_id"),
            workflow_id=metadata.get("workflow_id"),
            workflow_status=metadata.get("workflow_status"),
            response_id=metadata.get("response_id"),
            tokens_used=metadata.get("tokens_used"),
            latency_ms=latency_ms,
            details={
                key: value
                for key, value in metadata.items()
                if key
                not in {
                    "request_id",
                    "agent_used",
                    "trace_id",
                    "workflow_id",
                    "workflow_status",
                    "response_id",
                    "tokens_used",
                    "latency_ms",
                }
            },
        ),
    )


def _sse_event(event: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), default=str)
    return f"event: {event}\ndata: {body}\n\n".encode()


def _tokenize_stream_content(content: str) -> list[str]:
    tokens = re.findall(r"\S+\s*", content)
    return tokens or ([content] if content else [])


def _build_stream_error_payload(exc: Exception, *, request_id: str) -> dict[str, Any]:
    if isinstance(exc, AppError):
        return {
            "request_id": request_id,
            "error": user_safe_error_message(exc),
            "error_type": type(exc).__name__,
        }

    return {
        "request_id": request_id,
        "error": f"Internal error while generating the response ({type(exc).__name__}).",
        "error_type": type(exc).__name__,
    }


@router.post("/chat", response_model=ChatResponseDTO)
async def chat(
    request: ChatRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    client: AsyncAnthropic = Depends(get_anthropic_client),
) -> ChatResponseDTO:
    """Process a chat message through the agent system."""
    request_id = _current_request_id()
    start = time.monotonic()
    user_id = _principal_user_ref(principal)
    message = _build_message_input(request, user_id=user_id, request_id=request_id)
    try:
        response = await process_message(message, client, session)
    except Exception:
        try:
            await session.rollback()
            await persist_recorded_trace(session, message.metadata)
        except Exception:
            logger.warning("chat_trace_persist_failed", request_id=request_id, exc_info=True)
        raise

    try:
        await persist_recorded_trace(session, message.metadata)
    except Exception:
        logger.warning("chat_trace_persist_failed", request_id=request_id, exc_info=True)

    latency_ms = int((time.monotonic() - start) * 1000)

    return _to_chat_response_dto(
        request_id=request_id,
        response=response,
        latency_ms=latency_ms,
    )


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    client: AsyncAnthropic = Depends(get_anthropic_client),
) -> StreamingResponse:
    """Process a chat message and emit an SSE stream for the UI."""
    request_id = _current_request_id()
    user_id = _principal_user_ref(principal)

    async def event_stream():
        start = time.monotonic()
        message = _build_message_input(request, user_id=user_id, request_id=request_id)
        yield _sse_event("message_start", {"request_id": request_id, "source": request.source})

        try:
            response = await process_message(message, client, session)
        except Exception as exc:
            logger.exception("chat_stream_failed", request_id=request_id)
            try:
                await session.rollback()
                await persist_recorded_trace(session, message.metadata)
            except Exception:
                logger.warning(
                    "chat_stream_trace_persist_failed",
                    request_id=request_id,
                    exc_info=True,
                )
            yield _sse_event(
                "error",
                _build_stream_error_payload(exc, request_id=request_id),
            )
            return

        try:
            await persist_recorded_trace(session, message.metadata)
        except Exception:
            logger.warning("chat_stream_trace_persist_failed", request_id=request_id, exc_info=True)

        latency_ms = int((time.monotonic() - start) * 1000)
        metadata = _build_metadata(
            request_id=request_id,
            response=response,
            latency_ms=latency_ms,
        )

        yield _sse_event("agent", {"agent": response.agent})

        tool_calls = metadata.get("tool_calls")
        tool_events = metadata.get("tool_events")
        tool_call_list = tool_calls if isinstance(tool_calls, list) else []
        tool_event_list = tool_events if isinstance(tool_events, list) else []
        if tool_call_list or tool_event_list:
            yield _sse_event(
                "tool_status",
                {
                    "tool_calls": tool_call_list,
                    "tool_events": tool_event_list,
                    "tool_count": metadata.get(
                        "tool_count",
                        max(len(tool_call_list), len(tool_event_list)),
                    ),
                    "errors": metadata.get("errors", 0),
                },
            )

        for token in _tokenize_stream_content(response.content):
            yield _sse_event("token", {"content": token})

        yield _sse_event(
            "message_end",
            {
                "content": response.content,
                "agent": response.agent,
                "metadata": metadata,
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/context-inspect", response_model=ContextInspectResponse)
async def inspect_chat_context(
    request: ChatRequest,
    principal: Principal = Depends(get_current_principal),
    client: AsyncAnthropic = Depends(get_anthropic_client),
    session: AsyncSession = Depends(get_db),
) -> ContextInspectResponse:
    """Assemble context without executing a specialist, for operator debugging."""
    request_id = _current_request_id()
    user_id = _principal_user_ref(principal)
    message = _build_message_input(request, user_id=user_id, request_id=request_id)

    conv_ctx = _get_conversation_context()
    raw_messages: list[dict[str, str]] = []
    rolling_summary = ""
    state_packet = None
    rag_chunks: list[dict] = []

    if conv_ctx and message.user_id:
        try:
            context_messages = await conv_ctx.get_context(message.user_id)
            raw_messages = [m.to_dict() for m in context_messages]
            rolling_summary = await conv_ctx.get_summary(message.user_id)
            state_packet = await conv_ctx.get_state_packet(message.user_id)
        except Exception as exc:
            logger.error("context_inspection_conversation_unavailable", exc_info=True)
            raise DatabaseError(
                f"Conversation context inspection failed with {type(exc).__name__}: {exc}",
            ) from exc

    if message.user_id:
        try:
            persisted_artifacts = list(
                await list_recent_artifacts_for_user(
                    session,
                    user_id=message.user_id,
                    limit=8,
                )
            )
            state_packet = merge_persisted_artifacts(state_packet, persisted_artifacts)
        except Exception:
            logger.warning("context_inspection_artifacts_unavailable", exc_info=True)

        try:
            rag_chunks = await _retrieve_supporting_context(
                message,
                session=session,
                user_id=message.user_id,
            )
        except Exception:
            logger.warning("context_inspection_retrieval_unavailable", exc_info=True)

    inspection_result = await get_default_context_engine().assemble(
        conversation_messages=raw_messages,
        conversation_summary=rolling_summary,
        state_packet=state_packet,
        rag_chunks=rag_chunks,
        user_message=message.content,
        client=client,
    )

    return ContextInspectResponse(
        request_id=request_id,
        inspection=inspection_result.inspection,
    )
