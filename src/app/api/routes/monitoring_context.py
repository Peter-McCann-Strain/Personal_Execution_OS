"""Operator inspection of stored conversation context."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_db
from src.app.domain.models import PendingToolPlan

from .monitoring_models import ContextSnapshotDTO

logger = structlog.get_logger()
router = APIRouter()


@router.get("/ops/context/{session_id}", response_model=ContextSnapshotDTO)
async def context_snapshot(
    session_id: str,
    session: AsyncSession = Depends(get_db),
) -> ContextSnapshotDTO:
    """Return the currently stored conversation context for one session/user."""
    from src.app.api.routes import monitoring as monitoring_facade

    conv_ctx = monitoring_facade._get_conversation_context()
    if conv_ctx is None:
        return ContextSnapshotDTO(
            session_id=session_id,
            configured=False,
            message_count=0,
            messages=[],
            summary="",
            state_packet=None,
            pending_tool_plan=None,
        )

    messages = await conv_ctx.get_context(session_id)
    summary = await conv_ctx.get_summary(session_id)
    state_packet = await conv_ctx.get_state_packet(session_id)
    pending_tool_plan = await conv_ctx.get_pending_tool_plan(session_id)
    if pending_tool_plan is None:
        checkpoint = await monitoring_facade.get_latest_pending_workflow_checkpoint_for_user(
            session,
            user_id=session_id,
        )
        checkpoint_payload = getattr(checkpoint, "payload", None)
        if checkpoint is not None and isinstance(checkpoint_payload, dict):
            payload = dict(checkpoint_payload)
            payload.setdefault("workflow_id", str(getattr(checkpoint, "workflow_id", "")))
            payload.setdefault("checkpoint_id", str(getattr(checkpoint, "id", "")))
            try:
                pending_tool_plan = PendingToolPlan.model_validate(payload)
            except Exception:
                logger.warning("monitoring_pending_tool_plan_checkpoint_invalid", exc_info=True)

    return ContextSnapshotDTO(
        session_id=session_id,
        configured=True,
        message_count=len(messages),
        messages=[message.to_dict() for message in messages],
        summary=summary,
        state_packet=(state_packet.model_dump(mode="json") if state_packet is not None else None),
        pending_tool_plan=(
            pending_tool_plan.model_dump(mode="json") if pending_tool_plan is not None else None
        ),
    )
