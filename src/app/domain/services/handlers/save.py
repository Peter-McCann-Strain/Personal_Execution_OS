"""Save handler — capture URLs and explicit note-save requests into storage."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import anthropic
import httpx
import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import get_settings
from src.app.core.conversation_actions import conversation_action_idempotency_key
from src.app.core.exceptions import LLMError
from src.app.core.llm_helpers import call_and_parse_with_retry
from src.app.core.url_extractor import extract_url_content
from src.app.domain.constants import EpisodeType
from src.app.domain.models import (
    ArtifactRecord,
    ChatResponse,
    Intent,
    MessageInput,
    PendingConversationAction,
)
from src.app.domain.services.handlers._common import (
    enqueue_entity_extraction,
    enqueue_reflection_pack_refresh,
)
from src.app.domain.services.message_utils import extract_current_message
from src.app.persistence.repositories.episodes import create_episode
from src.app.persistence.repositories.notes import create_note
from src.app.persistence.repositories.runtime_records import create_artifact_record

logger = structlog.get_logger()


class SaveSummary(BaseModel):
    """Structured summary of saved web content."""

    title: str = Field(description="Concise title for the saved content")
    summary: str = Field(description="2-3 sentence summary of the key points")
    tags: list[str] = Field(default_factory=list, description="Relevant tags")
    para_category: str = Field(default="resource", description="PARA category")
    user_reply: str = Field(default="", description="1-2 sentence Telegram reply")


class NoteCaptureDecision(BaseModel):
    """Structured decision for plain-text note capture requests."""

    should_save: bool = Field(description="Whether we have enough signal to save now")
    confidence: float = Field(ge=0.0, le=1.0)
    title: str = Field(default="", description="Clean, short note title")
    normalized_note: str = Field(
        default="",
        description="Edited note content with corrected spelling and tightened phrasing",
    )
    tags: list[str] = Field(default_factory=list)
    para_category: str = Field(default="resource")
    note_type: str = Field(default="fleeting")
    missing_details: list[str] = Field(
        default_factory=list,
        description="Any details still needed before saving",
    )
    clarification_question: str = Field(
        default="",
        description="Direct follow-up question when not confident enough to save",
    )
    user_reply: str = Field(
        default="",
        description="Natural confirmation reply when saved",
    )

    @field_validator(
        "title",
        "normalized_note",
        "para_category",
        "note_type",
        "clarification_question",
        "user_reply",
        mode="before",
    )
    @classmethod
    def _coerce_optional_strings(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value)

    @field_validator("tags", "missing_details", mode="before")
    @classmethod
    def _coerce_optional_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if item is not None and str(item).strip()]


_SUMMARISE_SYSTEM = """\
Summarise the following web page content for a personal knowledge management system.
Return JSON with fields: title, summary (2-3 sentences), tags (list), \
para_category (project/area/resource/archive), user_reply (string).

For user_reply: 1-2 sentences for Telegram. Say something about the content, not just \
confirmation it was saved. Connect it to likely interests if you can. \
Example: "Good find on the RAG precision metrics — connects to the search quality work \
you've been thinking about." Do NOT start with "Saved" or "Captured".
Be concise. Focus on the key takeaways."""

_NOTE_CAPTURE_SYSTEM = """\
You convert natural-language "save this to notes" requests into a clean stored note.
Return strict JSON with fields:
- should_save: boolean
- confidence: number 0..1
- title: short title
- normalized_note: polished note text
- tags: string array
- para_category: one of project/area/resource/archive
- note_type: one of fleeting/permanent/literature
- missing_details: string array
- clarification_question: string
- user_reply: string

Rules:
1. Correct obvious spelling/grammar issues in normalized_note.
2. Preserve user intent; do not invent factual details.
3. Add minimal useful structure when clear from context (e.g., likely project angle).
4. If the request is ambiguous or missing critical details, set should_save=false and ask
   one concrete clarification question in clarification_question.
5. If confident enough, set should_save=true and provide user_reply confirming what was saved.
6. Keep user_reply plain, natural, and concise.
"""

_NOTE_CAPTURE_PATTERNS = (
    "add this to notes",
    "add this to note",
    "add to notes",
    "save this to notes",
    "save to notes",
    "note this",
    "make a note",
    "jot this down",
    "put this in notes",
    "add this to nots",
    "add to nots",
    "add this to nltes",
    "add to nltes",
)
_GENERIC_NOTE_PLACEHOLDERS = {
    "",
    "this",
    "that",
    "it",
    "this please",
    "that please",
    "it please",
    "please",
}
_NOTE_CAPTURE_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?"
    r"(?:"
    r"add\s+(?:this|that|it)?\s*(?:to|in)?\s*(?:my\s+)?(?:notes?|nots?)"
    r"|save\s+(?:this|that|it)?\s*(?:to|in)?\s*(?:my\s+)?(?:notes?|nots?)"
    r"|put\s+this\s+in\s+(?:my\s+)?(?:notes?|nots?)"
    r"|note\s+this"
    r"|make\s+(?:a\s+)?note"
    r"|jot\s+this\s+down"
    r")"
    r"(?:\s*[:\-]\s*|\s+)?",
    flags=re.IGNORECASE,
)


async def handle_save(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    _intent: Intent,
) -> ChatResponse:
    """Handle save requests for URLs and explicit note captures."""
    pending_action = _load_pending_conversation_action(message)
    if pending_action is not None and pending_action.retryable:
        resumed = await _resume_pending_save_action(
            message=message,
            client=client,
            session=session,
            action=pending_action,
        )
        if resumed is not None:
            return resumed

    current_content = extract_current_message(message.content)

    # URL capture path
    url_match = re.search(r"https?://\S+", current_content)
    if url_match:
        return await _handle_url_save(
            client=client,
            session=session,
            url_match=url_match,
            message=message,
        )

    # Text-note capture path
    note_payload = _extract_note_capture_payload(current_content)
    if note_payload is not None:
        if not note_payload:
            return ChatResponse(
                content=(
                    "I can save that. What should the note actually say? "
                    "Share the main point and any key details."
                ),
                agent="save",
                metadata={
                    "clarification_requested": True,
                    "error": "missing_note_content",
                    "missing_details": ["note_content"],
                },
            )
        return await _handle_text_note_capture(
            client=client,
            session=session,
            note_payload=note_payload,
            original_text=current_content,
            message=message,
        )

    # Fallback clarification
    return ChatResponse(
        content=(
            "Do you want me to save a URL or capture a note? "
            "If it's a note, send the note text and I'll structure it."
        ),
        agent="save",
        metadata={"clarification_requested": True, "error": "missing_save_target"},
    )


def _looks_like_note_capture_request(content: str) -> bool:
    lowered = content.lower()
    if any(pattern in lowered for pattern in _NOTE_CAPTURE_PATTERNS):
        return True
    if _matches_fuzzy_note_command(lowered):
        return True
    return lowered.startswith("save ") and "http://" not in lowered and "https://" not in lowered


def _extract_note_capture_payload(content: str) -> str | None:
    """Return extracted note text for note-capture commands.

    Returns:
        - None when this does not look like a note capture request.
        - Empty string when it is a note capture request with no real content.
        - Non-empty cleaned note payload otherwise.
    """
    stripped = content.strip()
    lowered = stripped.lower()
    if not _looks_like_note_capture_request(stripped):
        return None

    remainder = stripped
    prefix_match = _NOTE_CAPTURE_PREFIX_RE.match(stripped)
    if prefix_match:
        remainder = stripped[prefix_match.end() :]
    elif lowered.startswith("save "):
        remainder = stripped[5:]
    elif _matches_fuzzy_note_command(lowered):
        remainder = _strip_fuzzy_note_prefix(stripped)

    remainder = remainder.strip(" \t\n:;,-.")
    if remainder.casefold() in _GENERIC_NOTE_PLACEHOLDERS:
        return ""
    return remainder


def _load_pending_conversation_action(message: MessageInput) -> PendingConversationAction | None:
    raw_action = message.metadata.get("pending_conversation_action")
    if isinstance(raw_action, PendingConversationAction):
        return raw_action
    if isinstance(raw_action, dict):
        return PendingConversationAction.model_validate(raw_action)
    return None


def _build_pending_action(
    *,
    action_type: str,
    human_summary: str,
    normalized_payload: dict,
    retryable: bool,
    specialist: str = "save",
    last_error: str | None = None,
    status: str = "failed",
    receipt_text: str | None = None,
    source_message: str | None = None,
) -> PendingConversationAction:
    failed_at = datetime.now(UTC) if status == "failed" else None
    return PendingConversationAction(
        action_id=str(uuid.uuid4()),
        action_type=action_type,
        status=status,
        human_summary=human_summary,
        normalized_payload=normalized_payload,
        idempotency_key=conversation_action_idempotency_key(action_type, normalized_payload),
        retryable=retryable,
        failed_at=failed_at,
        last_error=last_error,
        specialist=specialist,
        receipt_text=receipt_text,
        source_message=source_message,
    )


async def _persist_conversation_action_artifact(
    session: AsyncSession,
    *,
    user_id: str,
    action: PendingConversationAction,
    workflow_id: str | None,
    trace_id: str | None,
) -> None:
    try:
        await create_artifact_record(
            session,
            user_id=user_id,
            artifact=ArtifactRecord(
                artifact_type="conversation_action",
                summary=action.human_summary[:500],
                source_id=action.action_id,
                trace_id=trace_id,
                workflow_id=workflow_id,
                payload=action.model_dump(mode="json"),
            ),
        )
    except Exception:
        logger.warning("conversation_action_artifact_persist_failed", exc_info=True)


def _note_receipt(
    *,
    title: str,
    note_content: str,
    para_category: str,
    tags: list[str],
) -> str:
    summary = note_content.strip().replace("\n", " ")
    if len(summary) > 160:
        summary = f"{summary[:157].rstrip()}..."
    tag_text = ", ".join(tags) if tags else "none"
    return (
        f'Saved note "{title}" in {para_category} notes. '
        f"Content: {summary} Tags: {tag_text}. Links created: 0."
    )


def _url_receipt(
    *,
    title: str,
    summary: str,
    tags: list[str],
) -> str:
    tag_text = ", ".join(tags) if tags else "none"
    return f'Saved "{title}". Summary: {summary.strip()} Tags: {tag_text}.'


def _matches_fuzzy_note_command(lowered: str) -> bool:
    tokens = re.findall(r"[a-z]+", lowered)
    if not tokens:
        return False
    has_verb = any(
        _edit_distance(token, target) <= 1
        for token in tokens[:5]
        for target in (
            "add",
            "save",
            "put",
            "note",
            "jot",
            "capture",
        )
    )
    has_noteish = any(
        _edit_distance(token, target) <= 2
        for token in tokens[:8]
        for target in (
            "note",
            "notes",
        )
    )
    return has_verb and has_noteish


def _strip_fuzzy_note_prefix(content: str) -> str:
    words = content.split()
    cut_index = 0
    for idx, word in enumerate(words[:8]):
        clean = re.sub(r"[^a-z]", "", word.casefold())
        if clean and min(_edit_distance(clean, "note"), _edit_distance(clean, "notes")) <= 2:
            cut_index = idx + 1
            break
    if cut_index <= 0:
        return content
    return " ".join(words[cut_index:])


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for i, lch in enumerate(left, start=1):
        current = [i]
        for j, rch in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (0 if lch == rch else 1)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


async def _handle_text_note_capture(
    *,
    client: AsyncAnthropic,
    session: AsyncSession,
    note_payload: str,
    original_text: str,
    message: MessageInput | None = None,
    action_id: str | None = None,
) -> ChatResponse:
    """Parse and store a cleaned note from plain text save commands."""
    settings = get_settings()
    try:
        decision = await call_and_parse_with_retry(
            client,
            model=settings.summary_model,
            max_tokens=settings.summary_max_tokens,
            system=_NOTE_CAPTURE_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Original request:\n"
                        f"{original_text.strip()}\n\n"
                        "Candidate note content:\n"
                        f"{note_payload}"
                    ),
                }
            ],
            response_model=NoteCaptureDecision,
            error_context="save_note_capture",
        )
    except LLMError:
        logger.exception("save_note_capture_failed")
        pending_action = _build_pending_action(
            action_type="save_note",
            human_summary=f"Retry save note: {note_payload[:120]}",
            normalized_payload={
                "note_payload": note_payload,
                "original_text": original_text,
            },
            retryable=bool(note_payload.strip()),
            last_error="note_capture_parse_failed",
            source_message=original_text,
        )
        if message is not None:
            await _persist_conversation_action_artifact(
                session,
                user_id=message.user_id,
                action=pending_action,
                workflow_id=str(message.metadata.get("workflow_id") or ""),
                trace_id=str(message.metadata.get("trace_id") or ""),
            )
        return ChatResponse(
            content=(
                "I hit an internal save error before storing that note. "
                "Say 'try again' and I'll retry this exact note."
            ),
            agent="save",
            metadata={
                "error": "note_capture_parse_failed",
                "pending_conversation_action": pending_action.model_dump(mode="json"),
            },
        )
    except anthropic.APIError as exc:
        logger.exception("save_note_capture_failed")
        pending_action = _build_pending_action(
            action_type="save_note",
            human_summary=f"Retry save note: {note_payload[:120]}",
            normalized_payload={
                "note_payload": note_payload,
                "original_text": original_text,
            },
            retryable=bool(note_payload.strip()),
            last_error=type(exc).__name__,
            source_message=original_text,
        )
        if message is not None:
            await _persist_conversation_action_artifact(
                session,
                user_id=message.user_id,
                action=pending_action,
                workflow_id=str(message.metadata.get("workflow_id") or ""),
                trace_id=str(message.metadata.get("trace_id") or ""),
            )
        return ChatResponse(
            content=(
                "I couldn't complete that save because the note-processing "
                "request failed upstream. "
                "Say 'try again' and I'll retry this exact note."
            ),
            agent="save",
            metadata={
                "error": "note_capture_upstream_failed",
                "error_type": type(exc).__name__,
                "pending_conversation_action": pending_action.model_dump(mode="json"),
            },
        )

    if not decision.should_save or decision.confidence < 0.72:
        question = decision.clarification_question.strip() or (
            "What exactly should I capture as the note title and key outcome?"
        )
        return ChatResponse(
            content=question,
            agent="save",
            metadata={
                "clarification_requested": True,
                "confidence": decision.confidence,
                "missing_details": decision.missing_details,
            },
        )

    title = decision.title.strip() or "Captured note"
    note_content = decision.normalized_note.strip() or note_payload
    note_type = (
        decision.note_type
        if decision.note_type in {"fleeting", "permanent", "literature"}
        else "fleeting"
    )
    para_category = (
        decision.para_category
        if decision.para_category in {"project", "area", "resource", "archive"}
        else "resource"
    )
    tags = [tag.strip() for tag in decision.tags if tag.strip()]

    note = await create_note(
        session,
        title=title,
        content=note_content,
        note_type=note_type,
        para_category=para_category,
        tags=tags or None,
        source_url=None,
    )
    receipt = _note_receipt(
        title=title,
        note_content=note_content,
        para_category=para_category,
        tags=tags,
    )
    completed_action = _build_pending_action(
        action_type="save_note",
        human_summary=receipt,
        normalized_payload={
            "title": title,
            "note_payload": note_content,
            "original_text": original_text,
            "tags": tags,
            "para_category": para_category,
            "note_type": note_type,
        },
        retryable=True,
        status="succeeded",
        receipt_text=receipt,
        source_message=original_text,
    )
    if action_id is not None:
        completed_action = completed_action.model_copy(update={"action_id": action_id})
    if message is not None:
        await _persist_conversation_action_artifact(
            session,
            user_id=message.user_id,
            action=completed_action,
            workflow_id=str(message.metadata.get("workflow_id") or ""),
            trace_id=str(message.metadata.get("trace_id") or ""),
        )
    await session.commit()

    reply = receipt
    return ChatResponse(
        content=reply,
        agent="save",
        metadata={
            "note_id": str(note.id),
            "title": title,
            "tags": tags,
            "para_category": para_category,
            "note_type": note_type,
            "normalized_note": note_content,
            "pending_conversation_action_cleared": True,
            "receipt_text": receipt,
        },
    )


async def _resume_pending_save_action(
    *,
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    action: PendingConversationAction,
) -> ChatResponse | None:
    payload = action.normalized_payload
    if action.action_type == "save_note":
        note_payload = str(payload.get("note_payload", "")).strip()
        original_text = str(payload.get("original_text", "")).strip() or note_payload
        if not note_payload:
            return None
        return await _handle_text_note_capture(
            client=client,
            session=session,
            note_payload=note_payload,
            original_text=original_text,
            message=message,
            action_id=action.action_id,
        )
    if action.action_type == "save_url":
        url = str(payload.get("url", "")).strip()
        if not url:
            return None
        retry_message = message.model_copy(update={"content": f"save {url}"})
        return await _handle_url_save(
            client=client,
            session=session,
            url_match=re.search(r"https?://\S+", retry_message.content),
            message=retry_message,
            action_id=action.action_id,
        )
    return None


async def _handle_url_save(
    *,
    client: AsyncAnthropic,
    session: AsyncSession,
    url_match: re.Match[str],
    message: MessageInput | None = None,
    action_id: str | None = None,
) -> ChatResponse:
    """Extract URL content, summarize, and store as saved content episode."""

    if url_match is None:
        return ChatResponse(
            content="I couldn't determine which URL to retry.",
            agent="save",
            metadata={"error": "missing_url"},
        )

    url = url_match.group(0).rstrip(".,;:!?)")

    try:
        extracted = await extract_url_content(url)
    except httpx.HTTPError as e:
        logger.error(
            "save_extraction_failed",
            url_length=len(url),
            error_class=type(e).__name__,
        )
        pending_action = _build_pending_action(
            action_type="save_url",
            human_summary=f"Retry saved URL {url}",
            normalized_payload={"url": url},
            retryable=True,
            last_error=type(e).__name__,
            source_message=url,
        )
        if message is not None:
            await _persist_conversation_action_artifact(
                session,
                user_id=message.user_id,
                action=pending_action,
                workflow_id=str(message.metadata.get("workflow_id") or ""),
                trace_id=str(message.metadata.get("trace_id") or ""),
            )
        return ChatResponse(
            content=(
                f"I couldn't fetch {url} just now. Say 'try again' and I'll retry this exact save."
            ),
            agent="save",
            metadata={
                "error": "extraction_failed",
                "pending_conversation_action": pending_action.model_dump(mode="json"),
            },
        )

    if not extracted.text:
        return ChatResponse(
            content=f"Couldn't extract readable content from {url}.",
            agent="save",
            metadata={"error": "no_content"},
        )

    settings = get_settings()
    try:
        summary_result = await call_and_parse_with_retry(
            client,
            model=settings.summary_model,
            max_tokens=settings.summary_max_tokens,
            system=_SUMMARISE_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (f"URL: {url}\n\nContent:\n{extracted.text[:5000]}"),
                }
            ],
            response_model=SaveSummary,
            error_context="save_summarise",
        )
    except LLMError:
        logger.exception("save_summarise_failed")
        pending_action = _build_pending_action(
            action_type="save_url",
            human_summary=f"Retry saved URL {url}",
            normalized_payload={"url": url},
            retryable=True,
            last_error="save_summarise_failed",
            source_message=url,
        )
        if message is not None:
            await _persist_conversation_action_artifact(
                session,
                user_id=message.user_id,
                action=pending_action,
                workflow_id=str(message.metadata.get("workflow_id") or ""),
                trace_id=str(message.metadata.get("trace_id") or ""),
            )
        return ChatResponse(
            content=(
                f"I fetched {url} but hit an internal summarisation error before saving it. "
                "Say 'try again' and I'll retry this exact save."
            ),
            agent="save",
            metadata={
                "error": "save_summarise_failed",
                "pending_conversation_action": pending_action.model_dump(mode="json"),
            },
        )
    except anthropic.APIError as exc:
        logger.exception("save_summarise_failed")
        pending_action = _build_pending_action(
            action_type="save_url",
            human_summary=f"Retry saved URL {url}",
            normalized_payload={"url": url},
            retryable=True,
            last_error=type(exc).__name__,
            source_message=url,
        )
        if message is not None:
            await _persist_conversation_action_artifact(
                session,
                user_id=message.user_id,
                action=pending_action,
                workflow_id=str(message.metadata.get("workflow_id") or ""),
                trace_id=str(message.metadata.get("trace_id") or ""),
            )
        return ChatResponse(
            content=(
                f"I fetched {url} but the summarisation request failed upstream "
                "before I could save it. "
                "Say 'try again' and I'll retry this exact save."
            ),
            agent="save",
            metadata={
                "error": "save_summarise_upstream_failed",
                "pending_conversation_action": pending_action.model_dump(mode="json"),
            },
        )

    full_content = (
        f"# {summary_result.title}\n\n"
        f"Source: {url}\n\n"
        f"{summary_result.summary}\n\n"
        f"---\n\n"
        f"{extracted.text[:3000]}"
    )

    episode = await create_episode(
        session,
        content=full_content,
        summary=summary_result.summary,
        episode_type=EpisodeType.SAVED_CONTENT,
        source="save",
        para_category=summary_result.para_category,
        tags=summary_result.tags,
        metadata={"url": url, "word_count": extracted.word_count},
    )
    receipt = _url_receipt(
        title=summary_result.title,
        summary=summary_result.summary,
        tags=summary_result.tags,
    )
    completed_action = _build_pending_action(
        action_type="save_url",
        human_summary=receipt,
        normalized_payload={"url": url, "title": summary_result.title},
        retryable=True,
        status="succeeded",
        receipt_text=receipt,
        source_message=url,
    )
    if action_id is not None:
        completed_action = completed_action.model_copy(update={"action_id": action_id})
    if message is not None:
        await _persist_conversation_action_artifact(
            session,
            user_id=message.user_id,
            action=completed_action,
            workflow_id=str(message.metadata.get("workflow_id") or ""),
            trace_id=str(message.metadata.get("trace_id") or ""),
        )
    await session.commit()

    try:
        await enqueue_reflection_pack_refresh("episode_saved_content_saved")
    except Exception as exc:
        logger.warning(
            "save_reflection_pack_refresh_degraded",
            episode_id=str(episode.id),
            error=str(exc),
            exc_info=True,
        )

    try:
        await enqueue_entity_extraction(
            episode_id=str(episode.id),
            text_content=full_content,
        )
    except Exception as exc:
        logger.warning(
            "save_entity_extraction_degraded",
            episode_id=str(episode.id),
            error=str(exc),
            exc_info=True,
        )

    reply = receipt
    return ChatResponse(
        content=reply,
        agent="save",
        metadata={
            "episode_id": str(episode.id),
            "url": url,
            "title": summary_result.title,
            "tags": summary_result.tags,
            "pending_conversation_action_cleared": True,
            "receipt_text": receipt,
        },
    )
