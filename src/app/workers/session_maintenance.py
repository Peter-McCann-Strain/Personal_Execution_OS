"""Nightly session maintenance for transcript, artifact, and workflow hygiene."""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import delete, select

from src.app.core.async_utils import maybe_await
from src.app.persistence.models import ArtifactRecordModel, InteractionRecord, WorkflowCheckpoint

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_COMPACTED_PREFIX = "[session-maintenance-compacted]"
_COMPACTION_VERSION = "session_maintenance_v1"
_MAX_PRESERVED_PAYLOAD_KEYS = 25


def _truncate_preview(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(limit - 3, 1)].rstrip() + "..."


def _is_compacted_text(value: str) -> bool:
    return value.startswith(_COMPACTED_PREFIX)


def _compact_text(value: str, *, preview_chars: int) -> str:
    if _is_compacted_text(value):
        return value
    preview = _truncate_preview(value, preview_chars)
    if not preview:
        return _COMPACTED_PREFIX
    return f"{_COMPACTED_PREFIX} {preview}"


def _payload_size(payload: Any) -> int:
    try:
        return len(json.dumps(payload, sort_keys=True, default=str))
    except TypeError:
        return len(str(payload))


def _response_envelope_preview(payload: dict[str, Any], *, preview_chars: int) -> str | None:
    content_blocks = payload.get("content_blocks")
    if not isinstance(content_blocks, list):
        return None

    text_fragments: list[str] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type", "text")).strip().lower()
        title = str(block.get("title", "")).strip()
        text = str(block.get("text", "")).strip()
        items = (
            [str(item).strip() for item in block.get("items", []) if str(item).strip()]
            if isinstance(block.get("items"), list)
            else []
        )

        if block_type in {"field", "label_value"} and title and text:
            text_fragments.append(f"{title}: {text}")
            continue

        if text:
            text_fragments.append(text)
        elif title:
            text_fragments.append(title)

        if items:
            text_fragments.extend(items)

    preview = " ".join(fragment for fragment in text_fragments if fragment)
    if not preview:
        return None
    return _truncate_preview(preview, preview_chars)


def _compact_artifact_payload(
    record: ArtifactRecordModel,
    *,
    compacted_at: datetime,
    preview_chars: int,
) -> dict[str, Any]:
    payload = record.payload if isinstance(record.payload, dict) else {}
    preserved: dict[str, Any] = {}

    if record.artifact_type == "response_envelope":
        for key in ("response_id", "interaction_id", "trace_id", "workflow_id", "workflow_status"):
            value = payload.get(key)
            if value is not None:
                preserved[key] = value
        if isinstance(payload.get("safety_flags"), list):
            preserved["safety_flags"] = payload["safety_flags"][:10]
        if isinstance(payload.get("quality"), dict):
            preserved["quality"] = payload["quality"]
        if isinstance(payload.get("tool_events"), list):
            preserved["tool_event_count"] = len(payload["tool_events"])
            preserved["tool_names"] = [
                str(event.get("name", "unknown"))
                for event in payload["tool_events"][:10]
                if isinstance(event, dict)
            ]
            preserved["tool_statuses"] = [
                str(event.get("status", "planned"))
                for event in payload["tool_events"][:10]
                if isinstance(event, dict)
            ]
        citations = payload.get("citations")
        if isinstance(citations, list):
            preserved["citation_count"] = len(citations)
            preserved["citation_labels"] = [
                str(citation.get("label") or citation.get("source_id") or "")
                for citation in citations[:8]
                if isinstance(citation, dict)
            ]
        content_preview = _response_envelope_preview(payload, preview_chars=preview_chars)
        if content_preview:
            preserved["content_preview"] = content_preview
    elif record.artifact_type == "tool_summary":
        tool_calls = payload.get("tool_calls")
        if isinstance(tool_calls, list):
            preserved["tool_call_count"] = len(tool_calls)
            preserved["tool_names"] = [
                str(call.get("name", "unknown"))
                for call in tool_calls[:10]
                if isinstance(call, dict)
            ]
            preserved["tool_statuses"] = [
                str(call.get("status", "planned"))
                for call in tool_calls[:10]
                if isinstance(call, dict)
            ]
        tool_events = payload.get("tool_events")
        if isinstance(tool_events, list) and "tool_names" not in preserved:
            preserved["tool_names"] = [
                str(event.get("name", "unknown"))
                for event in tool_events[:10]
                if isinstance(event, dict)
            ]
            preserved["tool_statuses"] = [
                str(event.get("status", "planned"))
                for event in tool_events[:10]
                if isinstance(event, dict)
            ]
        if "tool_count" in payload:
            preserved["tool_count"] = payload.get("tool_count")
        if "errors" in payload:
            preserved["errors"] = payload.get("errors")
    elif record.artifact_type == "research_report":
        for key in ("title", "key_takeaway", "recommendation"):
            value = payload.get(key)
            if value:
                preserved[key] = value
        citations = payload.get("citations")
        if isinstance(citations, list):
            preserved["citation_count"] = len(citations)
            preserved["citation_labels"] = [
                str(citation.get("label") or citation.get("source_id") or "")
                for citation in citations[:8]
                if isinstance(citation, dict)
            ]
        if "safety_flags" in payload:
            preserved["safety_flags"] = payload.get("safety_flags")
    elif record.artifact_type == "email_triage":
        for key in (
            "classification",
            "sender",
            "subject_summary",
            "suggested_action",
            "response_deadline",
            "user_reply",
        ):
            value = payload.get(key)
            if value:
                preserved[key] = value
        if "safety_flags" in payload:
            preserved["safety_flags"] = payload.get("safety_flags")
    elif record.artifact_type == "email_draft":
        for key in ("subject", "tone", "body_preview", "user_reply"):
            value = payload.get(key)
            if value:
                preserved[key] = value
        if "safety_flags" in payload:
            preserved["safety_flags"] = payload.get("safety_flags")
    else:
        preserved["payload_keys"] = sorted(str(key) for key in payload)[
            :_MAX_PRESERVED_PAYLOAD_KEYS
        ]

    return {
        "_compacted_by": _COMPACTION_VERSION,
        "artifact_type": record.artifact_type,
        "original_size": _payload_size(payload),
        "compacted_at": compacted_at.isoformat(),
        "preserved": preserved,
    }


async def compact_stale_interaction_transcripts(
    session: AsyncSession,
    *,
    before: datetime,
    preview_chars: int,
) -> int:
    """Compact old raw interaction transcripts while preserving a preview."""
    stmt = select(InteractionRecord).where(InteractionRecord.created_at < before)
    result = await session.execute(stmt)
    scalars = await maybe_await(result.scalars())
    rows = await maybe_await(scalars.all())

    updated = 0
    for record in rows:
        changed = False
        if isinstance(record.user_message, str) and not _is_compacted_text(record.user_message):
            record.user_message = _compact_text(record.user_message, preview_chars=preview_chars)
            changed = True
        if isinstance(record.response_content, str) and not _is_compacted_text(
            record.response_content
        ):
            record.response_content = _compact_text(
                record.response_content,
                preview_chars=preview_chars,
            )
            changed = True
        if changed:
            updated += 1

    if updated:
        await maybe_await(session.flush())
    return updated


async def compact_stale_artifact_payloads(
    session: AsyncSession,
    *,
    before: datetime,
    payload_char_threshold: int,
    preview_chars: int,
) -> int:
    """Replace oversized historical artifact payloads with compact preserved summaries."""
    stmt = select(ArtifactRecordModel).where(ArtifactRecordModel.created_at < before)
    result = await session.execute(stmt)
    scalars = await maybe_await(result.scalars())
    rows = await maybe_await(scalars.all())

    compacted_at = datetime.now(UTC)
    updated = 0
    for record in rows:
        payload = record.payload
        if not isinstance(payload, dict) or not payload:
            continue
        if payload.get("_compacted_by") == _COMPACTION_VERSION:
            continue
        if _payload_size(payload) < payload_char_threshold:
            continue

        record.payload = _compact_artifact_payload(
            record,
            compacted_at=compacted_at,
            preview_chars=preview_chars,
        )
        updated += 1

    if updated:
        await maybe_await(session.flush())
    return updated


async def delete_resolved_workflow_checkpoints(
    session: AsyncSession,
    *,
    before: datetime,
) -> int:
    """Delete old resolved workflow checkpoints once they are no longer resumable."""
    stmt = delete(WorkflowCheckpoint).where(
        WorkflowCheckpoint.created_at < before,
        WorkflowCheckpoint.status != "pending",
    )
    result = await session.execute(stmt)
    return int(result.rowcount or 0)


async def run_session_maintenance(ctx: dict) -> dict[str, Any]:
    """Nightly maintenance job for persisted workflow/session residue."""
    logger.info("session_maintenance_started")

    session_factory = ctx.get("session_factory")
    settings = ctx.get("settings")

    if not session_factory:
        raise RuntimeError("session_maintenance_missing_session_factory")
    if not settings:
        raise RuntimeError("session_maintenance_missing_settings")
    if not settings.session_maintenance_enabled:
        logger.info("session_maintenance_disabled")
        return {"status": "disabled"}

    now = datetime.now(UTC)
    transcript_cutoff = now - timedelta(days=settings.session_maintenance_transcript_retention_days)
    artifact_cutoff = now - timedelta(days=settings.session_maintenance_artifact_compaction_days)
    checkpoint_cutoff = now - timedelta(days=settings.session_maintenance_checkpoint_retention_days)

    async with session_factory() as session:
        try:
            transcripts_compacted = await compact_stale_interaction_transcripts(
                session,
                before=transcript_cutoff,
                preview_chars=settings.session_maintenance_transcript_preview_chars,
            )
            artifacts_compacted = await compact_stale_artifact_payloads(
                session,
                before=artifact_cutoff,
                payload_char_threshold=settings.session_maintenance_payload_char_threshold,
                preview_chars=settings.session_maintenance_transcript_preview_chars,
            )
            checkpoints_deleted = await delete_resolved_workflow_checkpoints(
                session,
                before=checkpoint_cutoff,
            )
            await session.commit()
        except Exception:
            with suppress(Exception):
                await session.rollback()
            logger.exception("session_maintenance_failed")
            raise

    result = {
        "status": "completed",
        "transcripts_compacted": transcripts_compacted,
        "artifacts_compacted": artifacts_compacted,
        "checkpoints_deleted": checkpoints_deleted,
    }
    logger.info("session_maintenance_completed", **result)
    return result
