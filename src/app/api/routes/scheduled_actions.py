"""Scheduled-action CRUD and run-now routes."""

from __future__ import annotations

import inspect
import uuid
from typing import Any

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import Principal, get_anthropic_client, get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.core.exceptions import NotFoundError
from src.app.domain.services.scheduled_actions_runtime import execute_scheduled_action
from src.app.persistence.models import AuditEvent, ScheduledAction, ScheduledActionRun
from src.app.persistence.repositories.scheduled_actions import (
    create_scheduled_action as repo_create_scheduled_action,
)
from src.app.persistence.repositories.scheduled_actions import (
    get_scheduled_action as repo_get_scheduled_action,
)
from src.app.persistence.repositories.scheduled_actions import (
    list_scheduled_action_runs as repo_list_scheduled_action_runs,
)
from src.app.persistence.repositories.scheduled_actions import (
    list_scheduled_actions as repo_list_scheduled_actions,
)
from src.app.persistence.repositories.scheduled_actions import (
    soft_delete_scheduled_action as repo_soft_delete_scheduled_action,
)
from src.app.persistence.repositories.scheduled_actions import (
    update_scheduled_action as repo_update_scheduled_action,
)

router = APIRouter()


class ScheduledActionDTO(BaseModel):
    id: str
    user_id: str
    title: str
    prompt: str
    schedule_type: str
    schedule_config: dict[str, Any]
    timezone: str
    status: str
    delivery_channel: str
    next_run_at: str | None
    last_run_at: str | None
    last_result_summary: str | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class ScheduledActionRunDTO(BaseModel):
    id: str
    action_id: str
    workflow_id: str | None
    status: str
    result_summary: str | None
    error_message: str | None
    payload: dict[str, Any]
    triggered_at: str
    completed_at: str | None
    created_at: str


class CreateScheduledActionBody(BaseModel):
    title: str
    prompt: str
    schedule_type: str
    schedule_config: dict[str, Any] = {}
    timezone: str = "Europe/London"
    delivery_channel: str = "web"
    status: str = "active"


class UpdateScheduledActionBody(BaseModel):
    title: str | None = None
    prompt: str | None = None
    schedule_type: str | None = None
    schedule_config: dict[str, Any] | None = None
    timezone: str | None = None
    delivery_channel: str | None = None
    status: str | None = None


def _action_to_dto(action: ScheduledAction) -> ScheduledActionDTO:
    return ScheduledActionDTO(
        id=str(action.id),
        user_id=action.user_id,
        title=action.title,
        prompt=action.prompt,
        schedule_type=action.schedule_type,
        schedule_config=action.schedule_config or {},
        timezone=action.timezone,
        status=action.status,
        delivery_channel=action.delivery_channel,
        next_run_at=action.next_run_at.isoformat() if action.next_run_at else None,
        last_run_at=action.last_run_at.isoformat() if action.last_run_at else None,
        last_result_summary=action.last_result_summary,
        metadata=action.metadata_ or {},
        created_at=action.created_at.isoformat(),
        updated_at=action.updated_at.isoformat(),
    )


def _run_to_dto(run: ScheduledActionRun) -> ScheduledActionRunDTO:
    return ScheduledActionRunDTO(
        id=str(run.id),
        action_id=str(run.action_id),
        workflow_id=str(run.workflow_id) if run.workflow_id else None,
        status=run.status,
        result_summary=run.result_summary,
        error_message=run.error_message,
        payload=run.payload or {},
        triggered_at=run.triggered_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        created_at=run.created_at.isoformat(),
    )


async def _session_add(session: AsyncSession, instance: object) -> None:
    result = session.add(instance)
    if inspect.isawaitable(result):
        await result


def _principal_user_ref(principal: Principal) -> str:
    return principal.external_subject or principal.subject


async def _record_scheduled_action_audit_event(
    session: AsyncSession,
    *,
    principal: Principal,
    event_type: str,
    action_id: uuid.UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    await _session_add(
        session,
        AuditEvent(
            account_id=principal.account_id,
            user_id=principal.user_id,
            event_type=event_type,
            actor_type="user",
            resource_type="scheduled_action",
            resource_id=str(action_id),
            metadata_=metadata or {},
        ),
    )


@router.get("/scheduled-actions", response_model=PaginatedResponse[ScheduledActionDTO])
async def list_scheduled_actions(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
) -> PaginatedResponse[ScheduledActionDTO]:
    """List proactive scheduled actions."""
    user_id = _principal_user_ref(principal)
    actions, total = await repo_list_scheduled_actions(
        session,
        user_id=user_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    return paginate(
        items=[_action_to_dto(action) for action in actions],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/scheduled-actions", response_model=ScheduledActionDTO, status_code=201)
async def create_scheduled_action(
    body: CreateScheduledActionBody,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ScheduledActionDTO:
    """Create one scheduled action."""
    user_id = _principal_user_ref(principal)
    action = await repo_create_scheduled_action(
        session,
        user_id=user_id,
        title=body.title,
        prompt=body.prompt,
        schedule_type=body.schedule_type,
        schedule_config=body.schedule_config,
        timezone=body.timezone,
        status=body.status,
        delivery_channel=body.delivery_channel,
    )
    await _record_scheduled_action_audit_event(
        session,
        principal=principal,
        event_type="scheduled_action.created",
        action_id=action.id,
        metadata={
            "schedule_type": body.schedule_type,
            "timezone": body.timezone,
            "delivery_channel": body.delivery_channel,
            "status": body.status,
        },
    )
    await session.commit()
    return _action_to_dto(action)


@router.patch("/scheduled-actions/{action_id}", response_model=ScheduledActionDTO)
async def update_scheduled_action(
    action_id: uuid.UUID,
    body: UpdateScheduledActionBody,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ScheduledActionDTO:
    """Update one scheduled action."""
    user_id = _principal_user_ref(principal)
    action = await repo_update_scheduled_action(
        session,
        action_id=action_id,
        user_id=user_id,
        title=body.title,
        prompt=body.prompt,
        schedule_type=body.schedule_type,
        schedule_config=body.schedule_config,
        timezone=body.timezone,
        delivery_channel=body.delivery_channel,
        status=body.status,
    )
    if action is None:
        raise NotFoundError(f"Scheduled action not found: {action_id}")
    fields_set: set[str] = set(
        getattr(body, "model_fields_set", getattr(body, "__fields_set__", set()))
    )
    await _record_scheduled_action_audit_event(
        session,
        principal=principal,
        event_type="scheduled_action.updated",
        action_id=action.id,
        metadata={
            "changed_fields": sorted(fields_set),
            "status": body.status,
            "delivery_channel": body.delivery_channel,
        },
    )
    await session.commit()
    return _action_to_dto(action)


@router.delete("/scheduled-actions/{action_id}", status_code=204)
async def delete_scheduled_action(
    action_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Delete one scheduled action."""
    user_id = _principal_user_ref(principal)
    deleted = await repo_soft_delete_scheduled_action(
        session,
        action_id=action_id,
        user_id=user_id,
    )
    if not deleted:
        raise NotFoundError(f"Scheduled action not found: {action_id}")
    await _record_scheduled_action_audit_event(
        session,
        principal=principal,
        event_type="scheduled_action.deleted",
        action_id=action_id,
    )
    await session.commit()
    return Response(status_code=204)


@router.post("/scheduled-actions/{action_id}/run", response_model=ScheduledActionRunDTO)
async def run_scheduled_action_now(
    action_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    client: AsyncAnthropic = Depends(get_anthropic_client),
) -> ScheduledActionRunDTO:
    """Execute a scheduled action immediately through the existing chat runtime."""
    user_id = _principal_user_ref(principal)
    action = await repo_get_scheduled_action(session, action_id=action_id, user_id=user_id)
    if action is None:
        raise NotFoundError(f"Scheduled action not found: {action_id}")
    await _record_scheduled_action_audit_event(
        session,
        principal=principal,
        event_type="scheduled_action.run_requested",
        action_id=action_id,
        metadata={"delivery_channel": action.delivery_channel},
    )
    await execute_scheduled_action(session, client=client, action=action)
    runs = await repo_list_scheduled_action_runs(
        session, user_id=user_id, action_id=action_id, limit=1
    )
    run = runs[0]
    return _run_to_dto(run)


@router.get("/scheduled-actions/runs", response_model=list[ScheduledActionRunDTO])
async def list_scheduled_action_runs(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    action_id: uuid.UUID | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
) -> list[ScheduledActionRunDTO]:
    """List scheduled action execution history."""
    user_id = _principal_user_ref(principal)
    runs = await repo_list_scheduled_action_runs(
        session,
        user_id=user_id,
        action_id=action_id,
        limit=limit,
    )
    return [_run_to_dto(run) for run in runs]
