"""Assistant-native continuity and workspace metric routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_db
from src.app.persistence.models import (
    ApprovalRequest,
    BrowserSession,
    ConnectorAccount,
    ConnectorDocument,
    ContentAsset,
    InteractionRecord,
    Note,
    NoteCanvas,
    NoteLink,
    ProjectDraft,
    SavedMemory,
    ScheduledAction,
    ScheduledActionRun,
)

from .monitoring_common import _result_rows, _result_scalar_values
from .monitoring_models import AssistantNativeMetricsDTO

router = APIRouter()


@router.get("/ops/assistant-native-metrics", response_model=AssistantNativeMetricsDTO)
async def assistant_native_metrics(
    session: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=90),
    limit: int = Query(2000, ge=100, le=10000),
) -> AssistantNativeMetricsDTO:
    """Aggregate continuity, second-brain, project draft, and content-factory signals."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    interactions_result = await session.execute(
        select(InteractionRecord.channel_metrics)
        .where(InteractionRecord.created_at >= cutoff)
        .order_by(InteractionRecord.created_at.desc())
        .limit(limit)
    )
    interaction_metrics = [
        metrics
        for metrics in await _result_scalar_values(interactions_result)
        if isinstance(metrics, dict)
    ]

    note_kinds_result = await session.execute(select(Note.kind).where(Note.deleted_at.is_(None)))
    note_kinds = [
        value
        for value in await _result_scalar_values(note_kinds_result)
        if isinstance(value, str) or value is None
    ]

    canvas_ids_result = await session.execute(
        select(NoteCanvas.id).where(NoteCanvas.deleted_at.is_(None))
    )
    canvas_ids = await _result_scalar_values(canvas_ids_result)

    note_link_types_result = await session.execute(select(NoteLink.link_type))
    note_link_types = [
        value
        for value in await _result_scalar_values(note_link_types_result)
        if isinstance(value, str)
    ]

    project_drafts_result = await session.execute(
        select(ProjectDraft.status, ProjectDraft.applied_project_id)
    )
    project_draft_rows = await _result_rows(project_drafts_result)

    content_assets_result = await session.execute(
        select(ContentAsset.status, ContentAsset.asset_type).where(
            ContentAsset.deleted_at.is_(None)
        )
    )
    content_asset_rows = await _result_rows(content_assets_result)

    saved_memories_result = await session.execute(
        select(SavedMemory.pinned).where(SavedMemory.deleted_at.is_(None))
    )
    saved_memory_pins = await _result_scalar_values(saved_memories_result)

    connector_accounts_result = await session.execute(
        select(ConnectorAccount.id).where(ConnectorAccount.deleted_at.is_(None))
    )
    connector_account_ids = await _result_scalar_values(connector_accounts_result)

    connector_documents_result = await session.execute(
        select(ConnectorDocument.id).where(ConnectorDocument.deleted_at.is_(None))
    )
    connector_document_ids = await _result_scalar_values(connector_documents_result)

    scheduled_actions_result = await session.execute(
        select(ScheduledAction.status).where(ScheduledAction.deleted_at.is_(None))
    )
    scheduled_action_statuses = await _result_scalar_values(scheduled_actions_result)

    scheduled_action_runs_result = await session.execute(select(ScheduledActionRun.id))
    scheduled_action_run_ids = await _result_scalar_values(scheduled_action_runs_result)

    approval_requests_result = await session.execute(select(ApprovalRequest.status))
    approval_request_statuses = await _result_scalar_values(approval_requests_result)

    browser_sessions_result = await session.execute(select(BrowserSession.id))
    browser_session_ids = await _result_scalar_values(browser_sessions_result)

    continuity_resolution_count = sum(
        1
        for metrics in interaction_metrics
        if isinstance(metrics.get("continuity_resolution_type"), str)
    )
    continuity_retry_replayed_count = sum(
        1 for metrics in interaction_metrics if bool(metrics.get("continuity_retry_replayed"))
    )
    continuity_duplicate_prevented_count = sum(
        1 for metrics in interaction_metrics if bool(metrics.get("continuity_duplicate_prevented"))
    )
    continuity_note_reference_resolved_count = sum(
        1
        for metrics in interaction_metrics
        if bool(metrics.get("continuity_note_reference_resolved"))
    )
    assistant_receipt_count = sum(
        1 for metrics in interaction_metrics if bool(metrics.get("assistant_receipt_present"))
    )
    pending_action_cleared_count = sum(
        1 for metrics in interaction_metrics if bool(metrics.get("pending_action_cleared"))
    )
    project_draft_created_interaction_count = sum(
        1 for metrics in interaction_metrics if bool(metrics.get("project_draft_created"))
    )

    project_drafts_total = len(project_draft_rows)
    project_drafts_applied = sum(
        1
        for row in project_draft_rows
        if (isinstance(row, tuple) and len(row) >= 2 and row[0] == "applied" and row[1] is not None)
    )

    content_assets_total = len(content_asset_rows)
    content_assets_ready_total = sum(
        1
        for row in content_asset_rows
        if isinstance(row, tuple) and len(row) >= 1 and row[0] == "ready"
    )
    content_assets_in_progress_total = sum(
        1
        for row in content_asset_rows
        if isinstance(row, tuple) and len(row) >= 1 and row[0] == "in_progress"
    )
    content_assets_needs_review_total = sum(
        1
        for row in content_asset_rows
        if isinstance(row, tuple) and len(row) >= 1 and row[0] == "needs_review"
    )
    content_assets_done_total = sum(
        1
        for row in content_asset_rows
        if isinstance(row, tuple) and len(row) >= 1 and row[0] == "done"
    )
    notebooklm_podcast_total = sum(
        1
        for row in content_asset_rows
        if isinstance(row, tuple) and len(row) >= 2 and row[1] == "notebooklm_podcast"
    )

    return AssistantNativeMetricsDTO(
        generated_at=datetime.now(UTC).isoformat(),
        interaction_sample_size=len(interaction_metrics),
        continuity_resolution_count=continuity_resolution_count,
        continuity_retry_replayed_count=continuity_retry_replayed_count,
        continuity_duplicate_prevented_count=continuity_duplicate_prevented_count,
        continuity_note_reference_resolved_count=continuity_note_reference_resolved_count,
        assistant_receipt_count=assistant_receipt_count,
        pending_action_cleared_count=pending_action_cleared_count,
        project_draft_created_interaction_count=project_draft_created_interaction_count,
        project_drafts_total=project_drafts_total,
        project_drafts_applied=project_drafts_applied,
        notes_total=len(note_kinds),
        daily_notes_total=sum(1 for kind in note_kinds if kind == "daily"),
        moc_notes_total=sum(1 for kind in note_kinds if kind == "moc"),
        canvases_total=len(canvas_ids),
        note_links_total=len(note_link_types),
        wiki_links_total=sum(1 for link_type in note_link_types if link_type == "wiki"),
        manual_links_total=sum(1 for link_type in note_link_types if link_type == "manual"),
        semantic_links_total=sum(1 for link_type in note_link_types if link_type == "semantic"),
        content_assets_total=content_assets_total,
        content_assets_ready_total=content_assets_ready_total,
        content_assets_in_progress_total=content_assets_in_progress_total,
        content_assets_needs_review_total=content_assets_needs_review_total,
        content_assets_done_total=content_assets_done_total,
        notebooklm_podcast_total=notebooklm_podcast_total,
        saved_memories_total=len(saved_memory_pins),
        pinned_memories_total=sum(1 for value in saved_memory_pins if bool(value)),
        connector_accounts_total=len(connector_account_ids),
        connector_documents_total=len(connector_document_ids),
        scheduled_actions_total=len(scheduled_action_statuses),
        scheduled_actions_active_total=sum(
            1 for value in scheduled_action_statuses if value == "active"
        ),
        scheduled_action_runs_total=len(scheduled_action_run_ids),
        approval_requests_pending_total=sum(
            1 for value in approval_request_statuses if value == "pending"
        ),
        browser_sessions_total=len(browser_session_ids),
    )
