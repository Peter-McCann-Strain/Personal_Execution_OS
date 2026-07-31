"""Communications handler — email triage and drafting."""

from __future__ import annotations

import uuid

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.specialists.communications import (
    draft_reply,
    triage_email,
)
from src.app.domain.constants import EpisodeType, ParaCategory
from src.app.domain.models import ArtifactRecord, ChatResponse, Intent, MessageInput
from src.app.domain.services.handlers._common import (
    enqueue_entity_extraction,
    enqueue_reflection_pack_refresh,
)
from src.app.persistence.repositories.episodes import create_episode
from src.app.persistence.repositories.runtime_records import create_artifact_record

logger = structlog.get_logger()

_TRIAGE_HINTS = ("classify", "triage", "category", "label", "urgent", "fyi", "archive")


def _coerce_safety_flags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [flag for flag in value if isinstance(flag, str) and flag]


async def handle_communications(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    _intent: Intent,
) -> ChatResponse:
    """Handle email triage and drafting requests.

    Detects draft/reply requests vs. triage/classify requests based on keywords.
    """
    content_lower = message.content.lower()
    draft_keywords = {"draft", "reply", "respond", "write back", "compose"}
    is_draft = any(kw in content_lower for kw in draft_keywords)

    if is_draft:
        return await _handle_email_draft(message, client, session)

    return await _handle_email_triage(message, client, session)


async def _handle_email_triage(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
) -> ChatResponse:
    """Classify an email using the communications agent."""
    classification = await triage_email(message.content, client)
    safety_flags = _coerce_safety_flags(getattr(classification, "safety_flags", None))
    logger.info(
        "email_triaged",
        classification=classification.classification,
        sender_present=bool(classification.sender),
        subject_summary_length=len(classification.subject_summary or ""),
        safety_flags=safety_flags,
    )

    response_content = _build_triage_reply(message, classification)
    content_blocks = _build_triage_content_blocks(
        message,
        classification,
    )

    try:
        await enqueue_entity_extraction(
            episode_id=str(uuid.uuid4()),
            text_content=response_content,
        )
    except Exception as exc:
        logger.warning(
            "communications_triage_entity_extraction_degraded",
            error=str(exc),
            exc_info=True,
        )

    await _persist_communications_artifact(
        session,
        user_id=message.user_id,
        artifact_type="email_triage",
        summary=response_content,
        payload={
            "classification": classification.classification,
            "sender": classification.sender,
            "subject_summary": classification.subject_summary,
            "suggested_action": classification.suggested_action,
            "response_deadline": classification.response_deadline,
            "user_reply": classification.user_reply,
            "safety_flags": safety_flags,
        },
    )

    return ChatResponse(
        content=response_content,
        agent="communications",
        metadata={
            "classification": classification.classification,
            "sender": classification.sender,
            "subject_summary": classification.subject_summary,
            "suggested_action": classification.suggested_action,
            "urgency_reason": classification.urgency_reason,
            "response_deadline": classification.response_deadline,
            "user_reply": classification.user_reply,
            "safety_flags": safety_flags,
            "content_blocks": content_blocks,
        },
    )


async def _handle_email_draft(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
) -> ChatResponse:
    """Draft an email reply using the communications agent.

    Expects the message to contain the original email and optional context.
    The whole message is passed as both original_email and context since the user
    provides everything in natural language.
    """
    email_draft = await draft_reply(
        original_email=message.content,
        context="User requested a draft reply via the assistant.",
        channel=message.source,
        client=client,
    )
    safety_flags = _coerce_safety_flags(getattr(email_draft, "safety_flags", None))

    logger.info(
        "email_draft_generated",
        subject_length=len(email_draft.subject),
        tone=email_draft.tone,
        safety_flags=safety_flags,
    )

    # Store the draft as an episode for future reference
    episode = await create_episode(
        session,
        content=f"Subject: {email_draft.subject}\n\n{email_draft.body}",
        summary=f"Email draft: {email_draft.subject}",
        episode_type=EpisodeType.COMMUNICATION,
        source=message.source,
        para_category=ParaCategory.AREA,
        tags=["email", "draft"],
    )
    await session.commit()

    try:
        await enqueue_reflection_pack_refresh("episode_communications_saved")
    except Exception as exc:
        logger.warning(
            "communications_reflection_pack_refresh_degraded",
            episode_id=str(episode.id),
            error=str(exc),
            exc_info=True,
        )

    preamble = _draft_preamble(message.source, email_draft.user_reply)
    response_content = f"{preamble}Subject: {email_draft.subject}\n\n{email_draft.body}"
    content_blocks = _build_draft_content_blocks(
        preamble=preamble,
        subject=email_draft.subject,
        body=email_draft.body,
    )

    try:
        await enqueue_entity_extraction(
            episode_id=str(episode.id),
            text_content=response_content,
        )
    except Exception as exc:
        logger.warning(
            "communications_draft_entity_extraction_degraded",
            episode_id=str(episode.id),
            error=str(exc),
            exc_info=True,
        )

    await _persist_communications_artifact(
        session,
        user_id=message.user_id,
        artifact_type="email_draft",
        summary=f"{email_draft.subject}: {email_draft.body}",
        source_id=str(episode.id),
        payload={
            "subject": email_draft.subject,
            "tone": email_draft.tone,
            "body_preview": email_draft.body[:500],
            "user_reply": email_draft.user_reply,
            "safety_flags": safety_flags,
        },
    )

    return ChatResponse(
        content=response_content,
        agent="communications",
        metadata={
            "episode_id": str(episode.id),
            "subject": email_draft.subject,
            "tone": email_draft.tone,
            "user_reply": email_draft.user_reply,
            "safety_flags": safety_flags,
            "content_blocks": content_blocks,
        },
    )


def _build_triage_reply(message: MessageInput, classification) -> str:
    user_reply = classification.user_reply if isinstance(classification.user_reply, str) else ""
    if user_reply:
        reply = user_reply.strip()
    else:
        sender = classification.sender or "This email"
        if classification.subject_summary:
            reply = f"{sender} is asking about {classification.subject_summary}."
        else:
            reply = f"{sender} needs attention."
        if classification.urgency_reason:
            reply = f"{reply} {classification.urgency_reason.rstrip('.')}."
        elif classification.suggested_action:
            reply = f"{reply} Next step: {classification.suggested_action}."

    if _wants_triage_labels(message.content):
        details: list[str] = [f"Category: {classification.classification}."]
        if classification.suggested_action:
            details.append(f"Next step: {classification.suggested_action}.")
        if isinstance(classification.response_deadline, str) and classification.response_deadline:
            details.append(f"Deadline: {classification.response_deadline}.")
        reply = "\n\n".join([reply, " ".join(details)])

    return reply


def _build_triage_content_blocks(
    message: MessageInput,
    classification,
) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    user_reply = classification.user_reply if isinstance(classification.user_reply, str) else ""
    if user_reply.strip():
        summary = user_reply.strip()
    else:
        sender = classification.sender or "This email"
        if classification.subject_summary:
            summary = f"{sender} is asking about {classification.subject_summary}."
        else:
            summary = f"{sender} needs attention."
        if isinstance(classification.urgency_reason, str) and classification.urgency_reason.strip():
            summary = f"{summary} {classification.urgency_reason.rstrip('.')}."
        elif (
            isinstance(classification.suggested_action, str)
            and classification.suggested_action.strip()
        ):
            summary = f"{summary} Next step: {classification.suggested_action.strip()}."

    if summary:
        blocks.append({"type": "text", "text": summary})

    if not _wants_triage_labels(message.content):
        return blocks

    details: list[str] = []
    if isinstance(classification.classification, str) and classification.classification.strip():
        details.append(f"Category: {classification.classification.strip()}")
    if isinstance(classification.suggested_action, str) and classification.suggested_action.strip():
        details.append(f"Next step: {classification.suggested_action.strip()}")
    if (
        isinstance(classification.response_deadline, str)
        and classification.response_deadline.strip()
    ):
        details.append(f"Deadline: {classification.response_deadline.strip()}")
    elif isinstance(classification.urgency_reason, str) and classification.urgency_reason.strip():
        details.append(f"Why it matters: {classification.urgency_reason.strip()}")

    if details:
        blocks = [{"type": "text", "text": summary}]
        blocks.append({"type": "bullet_list", "title": "Details", "items": details})

    return blocks


def _wants_triage_labels(content: str) -> bool:
    lower = content.lower()
    return any(hint in lower for hint in _TRIAGE_HINTS)


def _draft_preamble(source: str, user_reply: str) -> str:
    if user_reply:
        return f"{user_reply.strip()}\n\n"
    if source == "telegram":
        return "Draft ready.\n\n"
    if source == "voice":
        return "Here's the draft.\n\n"
    return "Here's a clean draft.\n\n"


def _build_draft_content_blocks(
    *,
    preamble: str,
    subject: str,
    body: str,
) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    preamble_text = preamble.strip()
    if preamble_text:
        blocks.append({"type": "text", "text": preamble_text})
    if subject.strip():
        blocks.append({"type": "field", "title": "Subject", "text": subject.strip()})
    if body.strip():
        blocks.append({"type": "text", "text": body.strip()})
    return blocks


async def _persist_communications_artifact(
    session: AsyncSession,
    *,
    user_id: str,
    artifact_type: str,
    summary: str,
    payload: dict,
    source_id: str | None = None,
) -> None:
    try:
        await create_artifact_record(
            session,
            user_id=user_id,
            artifact=ArtifactRecord(
                artifact_type=artifact_type,
                summary=summary[:500],
                source_id=source_id,
                payload=payload,
            ),
        )
        await session.commit()
    except Exception:
        logger.warning(
            "communications_artifact_persist_failed",
            artifact_type=artifact_type,
            exc_info=True,
        )
        try:
            await session.rollback()
        except Exception:
            logger.warning("communications_artifact_rollback_failed", exc_info=True)
