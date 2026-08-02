"""Context assembly and retrieval helpers for the chat service."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.confirmation import is_explicit_confirmation, is_explicit_rejection
from src.app.core.context_engine import ContextInspection
from src.app.core.context_manager import AssembledContext
from src.app.domain.models import (
    MessageInput,
    PendingConversationAction,
    PendingPlanningSession,
    PendingToolPlan,
    SessionStatePacket,
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
from src.app.persistence.repositories.saved_memories import (
    mark_saved_memories_used as mark_retrieved_saved_memories_used,
)


def normalize_context_result(
    result: object,
    *,
    conversation_messages: list[dict[str, str]],
    conversation_summary: str,
    user_message: str,
) -> tuple[AssembledContext, ContextInspection | None]:
    """Normalize context-engine results for backward-compatible callers."""
    del conversation_messages, conversation_summary, user_message

    missing = object()
    assembled = getattr(result, "assembled", missing)
    inspection = getattr(result, "inspection", missing)
    if isinstance(assembled, AssembledContext) and (
        inspection is None or isinstance(inspection, ContextInspection)
    ):
        return assembled, inspection

    if isinstance(result, AssembledContext):
        return result, None

    msg = f"Unsupported context result type: {type(result)!r}"
    raise TypeError(msg)


def build_context_inspection(
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


def build_specialist_message(
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


async def retrieve_supporting_context(
    message: MessageInput,
    *,
    session: AsyncSession,
    user_id: str,
) -> list[dict]:
    """Retrieve durable supporting evidence for the main chat path."""
    normalized_query = _extract_retrieval_query(message.content)
    if not normalized_query:
        return []

    suppressed_sources = resolve_retrieval_suppressed_sources(message.metadata)

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


async def touch_retrieved_saved_memories(
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


def resolve_retrieval_suppressed_sources(metadata: dict | None) -> set[str]:
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


def build_supporting_context_citations(
    retrieved_chunks: list[dict],
) -> list[dict[str, str]]:
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
        label = supporting_context_label(
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


def supporting_context_source_summaries(
    retrieved_chunks: list[dict],
) -> list[dict[str, str]]:
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
                "label": supporting_context_label(
                    source_type=source_type,
                    source_id=source_id,
                    metadata=metadata,
                ),
            }
        )
        if len(summaries) >= 8:
            break
    return summaries


def supporting_context_label(
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


def should_skip_retrieval(
    content: str,
    pending_tool_plan: PendingToolPlan | None,
) -> bool:
    """Skip retrieval for pure confirmation flows where evidence adds no value."""
    if pending_tool_plan is None:
        return False
    return is_explicit_confirmation(content) or is_explicit_rejection(content)
