"""Memory handler — unified search with session and interaction fallbacks."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.specialists.memory import answer_from_memory
from src.app.config import get_settings
from src.app.core.context_manager import gate_by_relevance
from src.app.core.embeddings import OllamaEmbeddings
from src.app.core.exceptions import DatabaseError
from src.app.core.state_packet import render_session_state_packet
from src.app.domain.models import ChatResponse, Intent, MessageInput
from src.app.domain.services.handlers._common import enqueue_entity_extraction
from src.app.persistence.repositories.episodes import record_episode_access
from src.app.persistence.repositories.interactions import get_recent_interactions_for_user
from src.app.persistence.repositories.notes import record_note_access
from src.app.persistence.repositories.saved_memories import (
    mark_saved_memories_used as record_saved_memory_access,
)
from src.app.persistence.repositories.unified_search import unified_search

logger = structlog.get_logger()

_META_ASSISTANT_PATTERNS = (
    "how do you work",
    "how you work",
    "explain how you work",
    "what can you do",
    "how are you set up",
    "how do you remember",
)
_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "about",
    "did",
    "do",
    "for",
    "from",
    "get",
    "got",
    "have",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "that",
    "the",
    "to",
    "up",
    "was",
    "were",
    "what",
    "when",
    "where",
    "who",
    "why",
    "yesterday",
    "today",
    "morning",
    "afternoon",
    "night",
    "week",
}
_EMPTY_MEMORY_REPLY_PATTERNS = (
    re.compile(r"(?i)^nothing stored about that yet\.?$"),
    re.compile(
        r"(?i)^i (?:do not|don't) have (?:any )?(?:relevant )?information "
        r"stored about that\.?$"
    ),
    re.compile(r"(?i)^i don't have a durable record for that yet\.?$"),
    re.compile(r"(?i)^i don't have a durable record for .+ yet\.?$"),
)


async def handle_memory(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    _intent: Intent,
) -> ChatResponse:
    """Handle memory recall using durable, session, and interaction stores."""
    query = _extract_query(message.content)
    suppressed_sources = _resolve_suppressed_sources(message.metadata)
    meta_reply = _build_meta_assistant_reply(query)
    if meta_reply is not None:
        return ChatResponse(
            content=meta_reply,
            agent="memory",
            metadata={
                "result_count": 0,
                "filtered_count": 0,
                "search_method": "capabilities",
            },
        )

    raw_chunks = await _retrieve_context(
        query,
        session,
        user_id=message.user_id,
        suppressed_sources=suppressed_sources,
    )
    if "episode" not in suppressed_sources:
        raw_chunks.extend(
            await _retrieve_interaction_context(
                query,
                session,
                user_id=message.user_id,
            )
        )
        raw_chunks.extend(_build_session_context_chunks(query, message))
    raw_chunks = _dedupe_chunks(raw_chunks)

    context_chunks, num_filtered = gate_by_relevance(raw_chunks)

    if not context_chunks:
        return ChatResponse(
            content=_build_empty_memory_reply(query),
            agent="memory",
            metadata={
                "result_count": 0,
                "filtered_count": num_filtered,
                "search_method": "none",
            },
        )

    episode_ids = [
        uuid.UUID(c["source_id"]) for c in context_chunks if c.get("source_type") == "episode"
    ]
    note_ids = [uuid.UUID(c["source_id"]) for c in context_chunks if c.get("source_type") == "note"]
    saved_memory_ids = [
        uuid.UUID(c["source_id"]) for c in context_chunks if c.get("source_type") == "saved_memory"
    ]
    try:
        if episode_ids:
            await record_episode_access(session, episode_ids)
        if note_ids:
            await record_note_access(session, note_ids)
        if saved_memory_ids:
            await record_saved_memory_access(
                session,
                user_id=message.user_id,
                memory_ids=saved_memory_ids,
            )
    except Exception as exc:
        logger.error("access_recording_failed", agent="memory", exc_info=True)
        raise DatabaseError(
            f"Memory access recording failed with {type(exc).__name__}: {exc}",
        ) from exc

    source_types = sorted({c.get("source_type", "unknown") for c in context_chunks})
    answer = await answer_from_memory(query, context_chunks, client)
    answer_text = _stabilize_memory_answer_text(answer.answer, context_chunks)
    answer_confidence = answer.confidence
    if answer_text != answer.answer:
        answer_confidence = max(answer_confidence, 0.45)

    try:
        await enqueue_entity_extraction(
            episode_id=str(uuid.uuid4()),
            text_content=answer_text,
        )
    except Exception as exc:
        logger.warning(
            "memory_entity_extraction_degraded",
            error=str(exc),
            exc_info=True,
        )

    return ChatResponse(
        content=answer_text,
        agent="memory",
        metadata={
            "confidence": answer_confidence,
            "source_count": len(answer.sources),
            "follow_up_suggestions": answer.follow_up_suggestions,
            "search_method": "unified",
            "source_types": source_types,
            "chunks_filtered": num_filtered,
        },
    )


def _extract_query(content: str) -> str:
    """Strip assembled context wrappers and optimizer notes from a routed message."""
    query = content
    if "Current message:" in query:
        query = query.split("Current message:")[-1].strip()
    if "[System note:" in query:
        query = query.split("[System note:")[0].strip()
    return query.strip()


def _build_meta_assistant_reply(query: str) -> str | None:
    """Answer simple assistant meta-questions directly."""
    lower = query.lower()
    if not any(pattern in lower for pattern in _META_ASSISTANT_PATTERNS):
        return None

    return (
        "I work in three layers: recent conversation context, longer-term saved memory "
        "such as entries, notes, and entities, and tool-backed actions like calendar, "
        "email, research, and planning. If something was never saved, or if it has "
        "aged out of short-term session memory, I may not be able to recall it until "
        "we capture it properly."
    )


def _build_empty_memory_reply(query: str) -> str:
    """Return a useful empty-memory reply instead of a hard dead end."""
    window = _resolve_time_window(query)
    if window is not None:
        period = _format_time_window(window)
        return (
            f"I don't have a durable record for {period} yet. I can reliably "
            "recall saved entries, notes, and recent session context; if you want, I "
            "can help you capture this kind of work so yesterday-style questions land."
        )
    return (
        "I don't have a durable record for that yet. If you want, I can help "
        "you capture it now or search a different angle."
    )


def _build_session_context_chunks(query: str, message: MessageInput) -> list[dict]:
    """Expose the current session state packet as a fallback memory chunk."""
    inspection = message.metadata.get("context_inspection")
    if not isinstance(inspection, dict):
        return []

    packet = inspection.get("state_packet")
    if not packet:
        return []

    rendered = render_session_state_packet(packet, token_budget=1024)
    if not rendered:
        return []

    lower_rendered = rendered.lower()
    query_terms = _extract_query_terms(query)
    if (
        query_terms
        and not any(term in lower_rendered for term in query_terms)
        and _resolve_time_window(query) is None
    ):
        return []

    updated_at = packet.get("updated_at") if isinstance(packet, dict) else None
    return [
        {
            "content": rendered,
            "score": 0.74 if query_terms else 0.68,
            "source_type": "session",
            "source_id": "session-state-packet",
            "metadata": {"updated_at": updated_at},
            "search_method": "session_state",
        }
    ]


async def _retrieve_interaction_context(
    query: str,
    session: AsyncSession,
    *,
    user_id: str,
) -> list[dict]:
    """Retrieve persisted interaction history as a memory fallback."""
    if not user_id:
        return []

    window = _resolve_time_window(query)
    settings = get_settings()
    records = await get_recent_interactions_for_user(
        session,
        user_id=user_id,
        start=window[0] if window else None,
        end=window[1] if window else None,
        limit=30 if window else 20,
    )
    if getattr(settings, "private_single_user_mode", True) and user_id != "owner":
        owner_records = await get_recent_interactions_for_user(
            session,
            user_id="owner",
            start=window[0] if window else None,
            end=window[1] if window else None,
            limit=30 if window else 20,
        )
        records = _merge_recent_interactions(records, owner_records)

    if not records:
        return []

    threshold = settings.relevance_threshold
    query_terms = _extract_query_terms(query)
    chunks: list[dict] = []

    for rank, record in enumerate(records):
        score = _score_interaction_record(
            query_terms=query_terms,
            user_message=record.user_message,
            response_content=record.response_content,
            specialist=record.specialist,
            rank=rank,
            temporal_query=window is not None,
        )
        if score < threshold:
            continue

        created_at = record.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)

        chunks.append(
            {
                "content": (
                    f"Interaction on {_format_interaction_timestamp(created_at)}. "
                    f"You asked: {_truncate_text(record.user_message, 220)} "
                    f"Assistant ({record.response_agent}) replied: "
                    f"{_truncate_text(_sanitize_interaction_excerpt(record.response_content), 260)}"
                ),
                "score": score,
                "source_type": "interaction",
                "source_id": str(record.id),
                "metadata": {
                    "created_at": created_at.isoformat(),
                    "specialist": record.specialist,
                    "source": record.source,
                },
                "search_method": "interaction_history",
            }
        )

    return chunks[:6]


def _merge_recent_interactions(primary: list, secondary: list) -> list:
    """Merge and de-duplicate interaction rows, newest first."""
    merged: dict[str, object] = {}
    for record in [*primary, *secondary]:
        record_id = getattr(record, "id", None)
        if record_id is None:
            continue
        merged[str(record_id)] = record

    return sorted(
        merged.values(),
        key=lambda item: getattr(item, "created_at", datetime.min.replace(tzinfo=UTC)),
        reverse=True,
    )


def _resolve_time_window(
    query: str,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime] | None:
    """Map simple natural-language time references onto UTC windows."""
    lower = query.lower()
    timezone = _get_user_timezone()
    now_local = (now or datetime.now(tz=UTC)).astimezone(timezone)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if "yesterday" in lower:
        start_local = today_start_local - timedelta(days=1)
        return start_local.astimezone(UTC), today_start_local.astimezone(UTC)
    if "today" in lower:
        return today_start_local.astimezone(UTC), now_local.astimezone(UTC)
    if "this morning" in lower:
        end_local = min(today_start_local + timedelta(hours=12), now_local)
        return today_start_local.astimezone(UTC), end_local.astimezone(UTC)
    if "this afternoon" in lower:
        start_local = today_start_local + timedelta(hours=12)
        end_local = min(today_start_local + timedelta(hours=18), now_local)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)
    if "tonight" in lower:
        start_local = today_start_local + timedelta(hours=18)
        return start_local.astimezone(UTC), now_local.astimezone(UTC)
    if "last night" in lower:
        start_local = today_start_local - timedelta(hours=6)
        end_local = today_start_local + timedelta(hours=6)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)
    if "this week" in lower:
        start_local = today_start_local - timedelta(days=today_start_local.weekday())
        return start_local.astimezone(UTC), now_local.astimezone(UTC)
    if "last week" in lower:
        end_local = today_start_local - timedelta(days=today_start_local.weekday())
        start_local = end_local - timedelta(days=7)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)
    return None


def _extract_query_terms(query: str) -> list[str]:
    """Extract simple lexical terms for fallback interaction matching."""
    return [
        term
        for term in re.findall(r"[a-z0-9']+", query.lower())
        if len(term) > 2 and term not in _QUERY_STOPWORDS
    ]


def _score_interaction_record(
    *,
    query_terms: list[str],
    user_message: str,
    response_content: str,
    specialist: str,
    rank: int,
    temporal_query: bool,
) -> float:
    """Score an interaction record for memory fallback retrieval."""
    combined = f"{user_message}\n{response_content}".lower()
    matches = sum(1 for term in query_terms if term in combined)

    if temporal_query:
        score = 0.78 - (rank * 0.04)
        if matches:
            score += min(0.14, matches * 0.07)
        if specialist in {"project", "tools", "research", "communications", "review"}:
            score += 0.04
        return max(0.3, min(score, 0.95))

    if matches == 0:
        return 0.0

    score = 0.42 + (matches * 0.16) - (rank * 0.03)
    return max(0.35, min(score, 0.92))


def _dedupe_chunks(chunks: list[dict]) -> list[dict]:
    """Keep the highest-scoring chunk per source identifier."""
    merged: dict[tuple[str, str], dict] = {}
    for chunk in chunks:
        key = (str(chunk.get("source_type", "")), str(chunk.get("source_id", "")))
        current = merged.get(key)
        if current is None or chunk.get("score", 0) > current.get("score", 0):
            merged[key] = chunk
    return sorted(merged.values(), key=lambda item: item.get("score", 0), reverse=True)


def _truncate_text(text: str, limit: int) -> str:
    """Trim long interaction text without markdown or JSON artifacts."""
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: max(limit - 3, 1)].rstrip() + "..."


def _get_user_timezone() -> ZoneInfo:
    """Return the configured user timezone, falling back to UTC."""
    timezone_name = get_settings().user_timezone
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        logger.warning("memory_invalid_timezone", timezone=timezone_name)
        return ZoneInfo("UTC")


def _format_interaction_timestamp(created_at: datetime) -> str:
    """Format interaction timestamps in the configured local timezone."""
    timezone = _get_user_timezone()
    return created_at.astimezone(timezone).strftime("%Y-%m-%d %H:%M %Z")


def _format_time_window(window: tuple[datetime, datetime]) -> str:
    """Render a human-readable local date or date range for memory misses."""
    timezone = _get_user_timezone()
    start_local = window[0].astimezone(timezone)
    end_local = window[1].astimezone(timezone) - timedelta(seconds=1)

    if start_local.date() == end_local.date():
        return f"{start_local.strftime('%A %B')} {start_local.day}, {start_local.year}"

    return (
        f"{start_local.strftime('%A %B')} {start_local.day}, {start_local.year}"
        f" to {end_local.strftime('%A %B')} {end_local.day}, {end_local.year}"
    )


def _sanitize_interaction_excerpt(text: str) -> str:
    """Strip internal error wrappers from interaction snippets before recall."""
    cleaned = " ".join(text.split())
    cleaned = re.sub(r"(?is)failed to parse [^:\n]+ response:\s*", "", cleaned).strip()
    cleaned = re.sub(r"(?is)failed to parse [^:\n]+:\s*", "", cleaned).strip()
    cleaned = re.sub(r"(?is)(?:^|\s)sources\s*\(\d+\):\s*", " ", cleaned).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if not cleaned:
        return "Response content unavailable."
    return cleaned


def _stabilize_memory_answer_text(answer_text: str, context_chunks: list[dict]) -> str:
    """Replace empty canned memory misses when retrieval context actually exists."""
    cleaned = answer_text.strip()
    if not context_chunks or not _looks_like_empty_memory_answer(cleaned):
        return cleaned

    snippets: list[str] = []
    for chunk in context_chunks[:3]:
        snippet = _truncate_text(
            _sanitize_interaction_excerpt(str(chunk.get("content", ""))),
            180,
        )
        if snippet:
            snippets.append(f"- {snippet}")

    if not snippets:
        return (
            "I found related context, but it wasn't cleanly structured. "
            "Ask a narrower question and I'll pull a tighter recall."
        )

    return "I do have related history. Here are the strongest matches:\n" + "\n".join(snippets)


def _looks_like_empty_memory_answer(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True
    return any(pattern.match(lowered) for pattern in _EMPTY_MEMORY_REPLY_PATTERNS)


async def _retrieve_context(
    query: str,
    session: AsyncSession,
    *,
    user_id: str | None = None,
    suppressed_sources: set[str] | None = None,
) -> list[dict]:
    """Retrieve context via unified cross-store search."""
    settings = get_settings()
    limit = settings.default_search_limit

    embedder = OllamaEmbeddings(
        host=settings.ollama_host,
        model=settings.ollama_embed_model,
    )
    try:
        query_embedding = await embedder.embed_single(query)
    finally:
        await embedder.close()

    results = await unified_search(
        session=session,
        query=query,
        user_id=user_id,
        embedding=query_embedding,
        limit=limit,
        suppressed_sources=suppressed_sources,
    )

    if not results:
        return []

    logger.info(
        "unified_retrieval_complete",
        results=len(results),
        source_types=[r.source_type for r in results],
    )

    return [
        {
            "content": r.content,
            "score": r.score,
            "source_type": r.source_type,
            "source_id": r.source_id,
            "metadata": r.metadata,
            "search_method": "unified",
        }
        for r in results
    ]


def _resolve_suppressed_sources(metadata: dict | None) -> set[str]:
    """Normalize per-request memory suppression flags carried in message metadata."""
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
