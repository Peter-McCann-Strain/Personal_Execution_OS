"""Agent-run inspection and approval routes."""

from __future__ import annotations

import inspect
import uuid
from typing import Any

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import (
    Principal,
    get_anthropic_client,
    get_current_principal,
    get_db,
    get_mcp_manager,
)
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.core.exceptions import NotFoundError
from src.app.domain.constants import WorkflowStatus
from src.app.domain.models import MessageInput, PendingToolPlan
from src.app.domain.services.chat import _get_conversation_context
from src.app.domain.services.handlers.tools import _handle_tools_with_mcp
from src.app.persistence.models import (
    ApprovalRequest,
    ArtifactRecordModel,
    AuditEvent,
    BrowserSession,
    ToolReceipt,
    WorkflowRun,
    WorkflowRunStep,
)
from src.app.persistence.repositories.runtime_records import (
    create_workflow_run_step,
    get_approval_request_by_id,
    get_workflow_checkpoint_by_id,
    get_workflow_run_by_id,
    list_approval_requests,
    list_artifacts_for_workflow,
    list_browser_sessions,
    list_tool_receipts,
    list_workflow_run_steps,
    list_workflow_runs_for_user,
    resolve_approval_request,
    update_workflow_run,
    update_workflow_run_step,
)

router = APIRouter()


class WorkflowRunStepDTO(BaseModel):
    id: str
    workflow_id: str
    step_type: str
    title: str
    status: str
    details: dict[str, Any]
    created_at: str
    updated_at: str


class ApprovalRequestDTO(BaseModel):
    id: str
    workflow_id: str
    checkpoint_id: str | None
    request_kind: str
    title: str
    description: str | None
    status: str
    payload: dict[str, Any]
    created_at: str
    resolved_at: str | None
    updated_at: str


class BrowserSessionDTO(BaseModel):
    id: str
    workflow_id: str
    status: str
    start_url: str | None
    current_url: str | None
    timeline: list[dict[str, Any]]
    screenshot_artifacts: list[dict[str, Any]]
    risk_flags: list[str]
    created_at: str
    updated_at: str


class ToolReceiptDTO(BaseModel):
    id: str
    workflow_id: str | None
    tool_name: str
    server_name: str | None
    mutation_class: str
    status: str
    result_summary: str | None
    error_message: str | None
    created_at: str


class ArtifactRecordDTO(BaseModel):
    id: str
    artifact_type: str
    scope: str
    summary: str
    source_id: str | None
    created_at: str
    payload: dict[str, Any]


class AgentRunSummaryDTO(BaseModel):
    id: str
    source: str
    status: str
    specialist: str | None
    request_excerpt: str | None
    pending_approvals: int
    created_at: str
    updated_at: str


class AgentRunDetailDTO(AgentRunSummaryDTO):
    trace_id: str | None
    response_id: str | None
    metadata: dict[str, Any]
    steps: list[WorkflowRunStepDTO]
    approvals: list[ApprovalRequestDTO]
    browser_sessions: list[BrowserSessionDTO]
    tool_receipts: list[ToolReceiptDTO]
    artifacts: list[ArtifactRecordDTO]


class ApprovalActionResponse(BaseModel):
    status: str
    response_content: str
    workflow_status: str


def _step_to_dto(step: WorkflowRunStep) -> WorkflowRunStepDTO:
    return WorkflowRunStepDTO(
        id=str(step.id),
        workflow_id=str(step.workflow_id),
        step_type=step.step_type,
        title=step.title,
        status=step.status,
        details=step.details or {},
        created_at=step.created_at.isoformat(),
        updated_at=step.updated_at.isoformat(),
    )


def _approval_to_dto(approval: ApprovalRequest) -> ApprovalRequestDTO:
    return ApprovalRequestDTO(
        id=str(approval.id),
        workflow_id=str(approval.workflow_id),
        checkpoint_id=str(approval.checkpoint_id) if approval.checkpoint_id else None,
        request_kind=approval.request_kind,
        title=approval.title,
        description=approval.description,
        status=approval.status,
        payload=approval.payload or {},
        created_at=approval.created_at.isoformat(),
        resolved_at=approval.resolved_at.isoformat() if approval.resolved_at else None,
        updated_at=approval.updated_at.isoformat(),
    )


def _browser_session_to_dto(session: BrowserSession) -> BrowserSessionDTO:
    return BrowserSessionDTO(
        id=str(session.id),
        workflow_id=str(session.workflow_id),
        status=session.status,
        start_url=session.start_url,
        current_url=session.current_url,
        timeline=session.timeline or [],
        screenshot_artifacts=session.screenshot_artifacts or [],
        risk_flags=[str(flag) for flag in session.risk_flags or []],
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )


def _tool_receipt_to_dto(receipt: ToolReceipt) -> ToolReceiptDTO:
    return ToolReceiptDTO(
        id=str(receipt.id),
        workflow_id=receipt.workflow_id,
        tool_name=receipt.tool_name,
        server_name=receipt.server_name,
        mutation_class=receipt.mutation_class,
        status=receipt.status,
        result_summary=receipt.result_summary,
        error_message=receipt.error_message,
        created_at=receipt.created_at.isoformat(),
    )


def _artifact_to_dto(artifact: ArtifactRecordModel) -> ArtifactRecordDTO:
    return ArtifactRecordDTO(
        id=str(artifact.id),
        artifact_type=artifact.artifact_type,
        scope=artifact.scope,
        summary=artifact.summary,
        source_id=artifact.source_id,
        created_at=artifact.created_at.isoformat(),
        payload=artifact.payload or {},
    )


async def _session_add(session: AsyncSession, instance: object) -> None:
    result = session.add(instance)
    if inspect.isawaitable(result):
        await result


def _principal_user_ref(principal: Principal) -> str:
    return principal.external_subject or principal.subject


async def _record_approval_audit_event(
    session: AsyncSession,
    *,
    principal: Principal,
    event_type: str,
    workflow_id: uuid.UUID,
    approval_id: uuid.UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    await _session_add(
        session,
        AuditEvent(
            account_id=principal.account_id,
            user_id=principal.user_id,
            event_type=event_type,
            actor_type="user",
            resource_type="approval_request",
            resource_id=str(approval_id),
            metadata_={"workflow_id": str(workflow_id), **(metadata or {})},
        ),
    )


async def _build_run_detail(run: WorkflowRun, session: AsyncSession) -> AgentRunDetailDTO:
    steps = await list_workflow_run_steps(session, workflow_id=str(run.id))
    approvals = await list_approval_requests(session, workflow_id=str(run.id), limit=25)
    browser_sessions = await list_browser_sessions(session, workflow_id=str(run.id))
    tool_receipts = await list_tool_receipts(session, workflow_id=str(run.id), limit=25)
    artifacts = await list_artifacts_for_workflow(session, workflow_id=str(run.id), limit=25)
    return AgentRunDetailDTO(
        id=str(run.id),
        source=run.source,
        status=run.status,
        specialist=run.specialist,
        request_excerpt=run.request_excerpt,
        pending_approvals=sum(1 for approval in approvals if approval.status == "pending"),
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
        trace_id=run.trace_id,
        response_id=run.response_id,
        metadata=run.metadata_ or {},
        steps=[_step_to_dto(step) for step in steps],
        approvals=[_approval_to_dto(approval) for approval in approvals],
        browser_sessions=[_browser_session_to_dto(item) for item in browser_sessions],
        tool_receipts=[_tool_receipt_to_dto(item) for item in tool_receipts],
        artifacts=[_artifact_to_dto(item) for item in artifacts],
    )


@router.get("/agent-runs", response_model=PaginatedResponse[AgentRunSummaryDTO])
async def list_agent_runs(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    limit: int = 25,
    offset: int = 0,
    status: str | None = None,
) -> PaginatedResponse[AgentRunSummaryDTO]:
    """List workflow-backed agent runs."""
    user_id = _principal_user_ref(principal)
    runs, total = await list_workflow_runs_for_user(
        session,
        user_id=user_id,
        limit=limit,
        offset=offset,
        statuses=[status] if status else None,
    )
    approval_counts: dict[str, int] = {}
    for approval in await list_approval_requests(session, limit=200):
        key = str(approval.workflow_id)
        approval_counts[key] = approval_counts.get(key, 0) + (
            1 if approval.status == "pending" else 0
        )
    return paginate(
        items=[
            AgentRunSummaryDTO(
                id=str(run.id),
                source=run.source,
                status=run.status,
                specialist=run.specialist,
                request_excerpt=run.request_excerpt,
                pending_approvals=approval_counts.get(str(run.id), 0),
                created_at=run.created_at.isoformat(),
                updated_at=run.updated_at.isoformat(),
            )
            for run in runs
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/agent-runs/{workflow_id}", response_model=AgentRunDetailDTO)
async def get_agent_run(
    workflow_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> AgentRunDetailDTO:
    """Return one workflow-backed agent run."""
    user_id = _principal_user_ref(principal)
    run = await get_workflow_run_by_id(session, workflow_id)
    if run is None or run.user_id != user_id:
        raise NotFoundError(f"Agent run not found: {workflow_id}")
    return await _build_run_detail(run, session)


async def _execute_approval_action(
    *,
    workflow_id: uuid.UUID,
    approval_id: uuid.UUID,
    action_text: str,
    resolved_status: str,
    session: AsyncSession,
    client: AsyncAnthropic,
    manager: Any,
    principal: Principal,
    user_id: str,
) -> ApprovalActionResponse:
    run = await get_workflow_run_by_id(session, workflow_id)
    if run is None or run.user_id != user_id:
        raise NotFoundError(f"Agent run not found: {workflow_id}")
    approval = await get_approval_request_by_id(session, approval_id)
    if approval is None or approval.workflow_id != workflow_id:
        raise NotFoundError(f"Approval request not found: {approval_id}")
    if approval.status != "pending":
        return ApprovalActionResponse(
            status=approval.status,
            response_content="Approval request already resolved.",
            workflow_status=run.status,
        )
    if approval.checkpoint_id is None:
        raise NotFoundError(f"Approval checkpoint missing: {approval_id}")

    checkpoint = await get_workflow_checkpoint_by_id(session, approval.checkpoint_id)
    if checkpoint is None or not isinstance(checkpoint.payload, dict):
        raise NotFoundError(f"Approval checkpoint not found: {approval.checkpoint_id}")
    pending_plan = PendingToolPlan.model_validate(checkpoint.payload)

    step = await create_workflow_run_step(
        session,
        workflow_id=str(workflow_id),
        step_type="approval",
        title=f"{resolved_status.title()} approval",
        status="running",
        details={"approval_id": str(approval_id)},
    )
    message = MessageInput(
        content=action_text,
        source="api",
        user_id=user_id,
        metadata={
            "workflow_id": str(workflow_id),
            "trace_id": run.trace_id,
            "pending_tool_plan": pending_plan.model_dump(mode="json"),
        },
    )
    response = await _handle_tools_with_mcp(message, client, session, manager)
    await resolve_approval_request(
        session,
        approval_id=str(approval_id),
        status=resolved_status,
        payload={
            **(approval.payload or {}),
            "resolved_via": "agent_run_api",
            "response_metadata": response.metadata,
        },
    )
    conv_ctx = _get_conversation_context()
    if conv_ctx is not None:
        await conv_ctx.clear_pending_tool_plan(user_id)

    workflow_status = (
        str(WorkflowStatus.INTERRUPTED)
        if response.metadata.get("confirmation_required")
        else str(WorkflowStatus.COMPLETED)
    )
    await _record_approval_audit_event(
        session,
        principal=principal,
        event_type=f"approval_request.{resolved_status}",
        workflow_id=workflow_id,
        approval_id=approval_id,
        metadata={
            "request_kind": approval.request_kind,
            "checkpoint_id": str(approval.checkpoint_id),
            "workflow_status": workflow_status,
            "confirmation_required": bool(response.metadata.get("confirmation_required")),
        },
    )
    await update_workflow_run(
        session,
        str(workflow_id),
        status=workflow_status,
        specialist=run.specialist,
        trace_id=run.trace_id,
        response_id=run.response_id,
        details={**(run.metadata_ or {}), "approval_response": response.metadata},
    )
    await update_workflow_run_step(
        session,
        step_id=str(step.id),
        status="completed",
        details={
            "approval_id": str(approval_id),
            "resolved_status": resolved_status,
            "response_excerpt": response.content[:300],
        },
    )
    await session.commit()
    return ApprovalActionResponse(
        status=resolved_status,
        response_content=response.content,
        workflow_status=workflow_status,
    )


@router.post(
    "/agent-runs/{workflow_id}/approvals/{approval_id}/approve",
    response_model=ApprovalActionResponse,
)
async def approve_agent_run_request(
    workflow_id: uuid.UUID,
    approval_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    client: AsyncAnthropic = Depends(get_anthropic_client),
    manager: Any = Depends(get_mcp_manager),
) -> ApprovalActionResponse:
    """Approve and resume a pending tool confirmation."""
    user_id = _principal_user_ref(principal)
    return await _execute_approval_action(
        workflow_id=workflow_id,
        approval_id=approval_id,
        action_text="yes",
        resolved_status="approved",
        session=session,
        client=client,
        manager=manager,
        principal=principal,
        user_id=user_id,
    )


@router.post(
    "/agent-runs/{workflow_id}/approvals/{approval_id}/reject",
    response_model=ApprovalActionResponse,
)
async def reject_agent_run_request(
    workflow_id: uuid.UUID,
    approval_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    client: AsyncAnthropic = Depends(get_anthropic_client),
    manager: Any = Depends(get_mcp_manager),
) -> ApprovalActionResponse:
    """Reject and cancel a pending tool confirmation."""
    user_id = _principal_user_ref(principal)
    return await _execute_approval_action(
        workflow_id=workflow_id,
        approval_id=approval_id,
        action_text="cancel",
        resolved_status="rejected",
        session=session,
        client=client,
        manager=manager,
        principal=principal,
        user_id=user_id,
    )


@router.delete("/agent-runs/{workflow_id}/approvals/{approval_id}", status_code=204)
async def cancel_agent_run_request(
    workflow_id: uuid.UUID,
    approval_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Cancel an approval request without resuming the workflow."""
    user_id = _principal_user_ref(principal)
    run = await get_workflow_run_by_id(session, workflow_id)
    if run is None or run.user_id != user_id:
        raise NotFoundError(f"Agent run not found: {workflow_id}")
    approval = await get_approval_request_by_id(session, approval_id)
    if approval is None or approval.workflow_id != workflow_id:
        raise NotFoundError(f"Approval request not found: {approval_id}")
    await resolve_approval_request(
        session,
        approval_id=str(approval_id),
        status="cancelled",
        payload={**(approval.payload or {}), "resolved_via": "agent_run_api"},
    )
    await _record_approval_audit_event(
        session,
        principal=principal,
        event_type="approval_request.cancelled",
        workflow_id=workflow_id,
        approval_id=approval_id,
        metadata={
            "request_kind": approval.request_kind,
            "checkpoint_id": str(approval.checkpoint_id),
        },
    )
    await session.commit()
    return Response(status_code=204)
