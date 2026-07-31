"""Persistence helpers for workflow, policy, tool, and artifact records."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from inspect import isawaitable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.async_utils import maybe_await
from src.app.domain.models import ArtifactRecord, PolicyDecision, ToolInvocationPlan, WorkflowState
from src.app.persistence.models import (
    ApprovalRequest,
    ArtifactRecordModel,
    BrowserSession,
    PolicyDecisionRecord,
    ToolReceipt,
    WorkflowCheckpoint,
    WorkflowRun,
    WorkflowRunStep,
)


async def create_workflow_run(
    session: AsyncSession,
    workflow_state: WorkflowState,
) -> WorkflowRun:
    """Persist a workflow run summary."""
    record = WorkflowRun(
        id=uuid.UUID(workflow_state.workflow_id),
        user_id=workflow_state.user_id,
        source=workflow_state.source,
        status=workflow_state.status,
        request_excerpt=workflow_state.message_content[:500],
        specialist=workflow_state.specialist,
        trace_id=workflow_state.trace_id,
        metadata_=workflow_state.details,
    )
    add_result = session.add(record)
    if isawaitable(add_result):
        await add_result
    await session.flush()
    return record


async def update_workflow_run(
    session: AsyncSession,
    workflow_id: str,
    *,
    status: str,
    specialist: str | None = None,
    trace_id: str | None = None,
    response_id: str | None = None,
    details: dict | None = None,
) -> bool:
    """Update one workflow run."""
    stmt = (
        update(WorkflowRun)
        .where(WorkflowRun.id == uuid.UUID(workflow_id))
        .values(
            status=status,
            specialist=specialist,
            trace_id=trace_id,
            response_id=response_id,
            metadata_=details or {},
            updated_at=datetime.now(UTC),
        )
    )
    result = await session.execute(stmt)
    rowcount = getattr(result, "rowcount", 0)
    return isinstance(rowcount, int) and rowcount > 0


async def create_workflow_checkpoint(
    session: AsyncSession,
    *,
    workflow_id: str,
    checkpoint_kind: str,
    status: str,
    payload: dict,
) -> WorkflowCheckpoint:
    """Persist one workflow checkpoint."""
    record = WorkflowCheckpoint(
        workflow_id=uuid.UUID(workflow_id),
        checkpoint_kind=checkpoint_kind,
        status=status,
        payload=payload,
    )
    add_result = session.add(record)
    if isawaitable(add_result):
        await add_result
    await session.flush()
    return record


async def update_workflow_checkpoint(
    session: AsyncSession,
    *,
    status: str,
    checkpoint_id: str | None = None,
    workflow_id: str | None = None,
    checkpoint_kind: str | None = None,
    from_status: str | None = None,
    payload: dict | None = None,
) -> bool:
    """Update one or more workflow checkpoints."""
    stmt = update(WorkflowCheckpoint)

    if checkpoint_id is not None:
        stmt = stmt.where(WorkflowCheckpoint.id == uuid.UUID(checkpoint_id))
    elif workflow_id is not None:
        stmt = stmt.where(WorkflowCheckpoint.workflow_id == uuid.UUID(workflow_id))
    else:
        raise ValueError("checkpoint_id or workflow_id is required")

    if checkpoint_kind is not None:
        stmt = stmt.where(WorkflowCheckpoint.checkpoint_kind == checkpoint_kind)
    if from_status is not None:
        stmt = stmt.where(WorkflowCheckpoint.status == from_status)

    values: dict[str, object] = {
        "status": status,
        "updated_at": datetime.now(UTC),
    }
    if payload is not None:
        values["payload"] = payload

    result = await session.execute(stmt.values(**values))
    rowcount = getattr(result, "rowcount", 0)
    return isinstance(rowcount, int) and rowcount > 0


async def get_latest_pending_workflow_checkpoint_for_user(
    session: AsyncSession,
    *,
    user_id: str,
    checkpoint_kind: str = "tool_confirmation",
) -> WorkflowCheckpoint | None:
    """Return the newest pending checkpoint for a user, if any."""
    stmt = (
        select(WorkflowCheckpoint)
        .join(WorkflowRun, WorkflowCheckpoint.workflow_id == WorkflowRun.id)
        .where(
            WorkflowRun.user_id == user_id,
            WorkflowCheckpoint.checkpoint_kind == checkpoint_kind,
            WorkflowCheckpoint.status == "pending",
        )
        .order_by(WorkflowCheckpoint.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    value = result.scalar_one_or_none()
    return await maybe_await(value)


async def create_policy_decision(
    session: AsyncSession,
    decision: PolicyDecision,
    *,
    workflow_id: str | None,
    trace_id: str | None,
    specialist: str | None,
) -> PolicyDecisionRecord:
    """Persist one runtime policy decision."""
    record = PolicyDecisionRecord(
        workflow_id=workflow_id,
        trace_id=trace_id,
        specialist=specialist,
        policy_name=decision.policy_name,
        decision=decision.decision,
        reason=decision.reason,
        subject_type=decision.subject_type,
        subject_id=decision.subject_id,
        metadata_=decision.metadata,
    )
    add_result = session.add(record)
    if isawaitable(add_result):
        await add_result
    await session.flush()
    return record


async def create_tool_receipt(
    session: AsyncSession,
    *,
    plan: ToolInvocationPlan,
    status: str,
    trace_id: str | None,
    interaction_id: str | None,
    result_summary: str | None = None,
    error_message: str | None = None,
) -> ToolReceipt:
    """Persist one tool execution receipt."""
    record = ToolReceipt(
        workflow_id=plan.workflow_id,
        trace_id=trace_id,
        interaction_id=interaction_id,
        idempotency_key=plan.idempotency_key,
        tool_name=plan.public_name,
        server_name=plan.server_name,
        mutation_class=plan.mutation_class,
        status=status,
        argument_hash=plan.argument_hash,
        arguments=plan.arguments,
        audit_metadata=plan.audit_metadata,
        result_summary=result_summary,
        error_message=error_message,
    )
    add_result = session.add(record)
    if isawaitable(add_result):
        await add_result
    await session.flush()
    return record


async def get_tool_receipt_by_idempotency_key(
    session: AsyncSession,
    idempotency_key: str,
) -> ToolReceipt | None:
    """Return a prior tool receipt for idempotent replay protection."""
    stmt = select(ToolReceipt).where(ToolReceipt.idempotency_key == idempotency_key)
    result = await session.execute(stmt)
    value = result.scalar_one_or_none()
    return await maybe_await(value)


async def create_artifact_record(
    session: AsyncSession,
    *,
    user_id: str,
    artifact: ArtifactRecord,
) -> ArtifactRecordModel:
    """Persist one typed artifact."""
    record = ArtifactRecordModel(
        user_id=user_id,
        workflow_id=artifact.workflow_id,
        trace_id=artifact.trace_id,
        source_id=artifact.source_id,
        artifact_type=artifact.artifact_type,
        scope=artifact.scope,
        summary=artifact.summary,
        payload=artifact.payload,
    )
    add_result = session.add(record)
    if isawaitable(add_result):
        await add_result
    await session.flush()
    return record


async def get_artifact_record_by_id(
    session: AsyncSession,
    artifact_id: uuid.UUID | str,
) -> ArtifactRecordModel | None:
    """Fetch one typed artifact by id."""
    if isinstance(artifact_id, str):
        artifact_id = uuid.UUID(artifact_id)
    return await session.get(ArtifactRecordModel, artifact_id)


async def get_workflow_run_by_id(
    session: AsyncSession,
    workflow_id: str | uuid.UUID,
) -> WorkflowRun | None:
    """Fetch one workflow run by id."""
    if isinstance(workflow_id, str):
        workflow_id = uuid.UUID(workflow_id)
    return await session.get(WorkflowRun, workflow_id)


async def list_workflow_runs_for_user(
    session: AsyncSession,
    *,
    user_id: str,
    limit: int = 25,
    offset: int = 0,
    statuses: Sequence[str] | None = None,
) -> tuple[list[WorkflowRun], int]:
    """List workflow runs for one user, newest first."""
    count_stmt = select(WorkflowRun).where(WorkflowRun.user_id == user_id)
    if statuses:
        count_stmt = count_stmt.where(WorkflowRun.status.in_(tuple(statuses)))

    count_result = await session.execute(select(func.count()).select_from(count_stmt.subquery()))
    total = int(count_result.scalar_one())

    stmt = count_stmt.order_by(WorkflowRun.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    return rows, total


async def create_workflow_run_step(
    session: AsyncSession,
    *,
    workflow_id: str,
    step_type: str,
    title: str,
    status: str = "pending",
    details: dict | None = None,
) -> WorkflowRunStep:
    """Persist one workflow timeline step."""
    record = WorkflowRunStep(
        workflow_id=uuid.UUID(workflow_id),
        step_type=step_type,
        title=title,
        status=status,
        details=details or {},
    )
    add_result = session.add(record)
    if isawaitable(add_result):
        await add_result
    await session.flush()
    return record


async def update_workflow_run_step(
    session: AsyncSession,
    *,
    step_id: str,
    status: str | None = None,
    details: dict | None = None,
    title: str | None = None,
) -> bool:
    """Update one workflow timeline step."""
    values: dict[str, object] = {"updated_at": datetime.now(UTC)}
    if status is not None:
        values["status"] = status
    if details is not None:
        values["details"] = details
    if title is not None:
        values["title"] = title

    result = await session.execute(
        update(WorkflowRunStep).where(WorkflowRunStep.id == uuid.UUID(step_id)).values(**values)
    )
    rowcount = getattr(result, "rowcount", 0)
    return isinstance(rowcount, int) and rowcount > 0


async def list_workflow_run_steps(
    session: AsyncSession,
    *,
    workflow_id: str,
) -> Sequence[WorkflowRunStep]:
    """List timeline steps for one workflow."""
    stmt = (
        select(WorkflowRunStep)
        .where(WorkflowRunStep.workflow_id == uuid.UUID(workflow_id))
        .order_by(WorkflowRunStep.created_at.asc())
    )
    result = await session.execute(stmt)
    scalars = await maybe_await(result.scalars())
    rows = await maybe_await(scalars.all())
    return list(rows)


async def get_workflow_checkpoint_by_id(
    session: AsyncSession,
    checkpoint_id: str | uuid.UUID,
) -> WorkflowCheckpoint | None:
    """Fetch one workflow checkpoint by id."""
    if isinstance(checkpoint_id, str):
        checkpoint_id = uuid.UUID(checkpoint_id)
    return await session.get(WorkflowCheckpoint, checkpoint_id)


async def create_approval_request(
    session: AsyncSession,
    *,
    workflow_id: str,
    title: str,
    description: str | None = None,
    request_kind: str = "tool_confirmation",
    payload: dict | None = None,
    checkpoint_id: str | None = None,
) -> ApprovalRequest:
    """Persist one approval request."""
    record = ApprovalRequest(
        workflow_id=uuid.UUID(workflow_id),
        checkpoint_id=uuid.UUID(checkpoint_id) if checkpoint_id else None,
        request_kind=request_kind,
        title=title,
        description=description,
        payload=payload or {},
    )
    add_result = session.add(record)
    if isawaitable(add_result):
        await add_result
    await session.flush()
    return record


async def get_approval_request_by_id(
    session: AsyncSession,
    approval_id: str | uuid.UUID,
) -> ApprovalRequest | None:
    """Fetch one approval request."""
    if isinstance(approval_id, str):
        approval_id = uuid.UUID(approval_id)
    return await session.get(ApprovalRequest, approval_id)


async def get_pending_approval_request_for_checkpoint(
    session: AsyncSession,
    *,
    workflow_id: str,
    checkpoint_id: str | None = None,
) -> ApprovalRequest | None:
    """Fetch the newest pending approval request for a workflow/checkpoint pair."""
    stmt = select(ApprovalRequest).where(
        ApprovalRequest.workflow_id == uuid.UUID(workflow_id),
        ApprovalRequest.status == "pending",
    )
    if checkpoint_id is not None:
        stmt = stmt.where(ApprovalRequest.checkpoint_id == uuid.UUID(checkpoint_id))
    stmt = stmt.order_by(ApprovalRequest.created_at.desc()).limit(1)
    result = await session.execute(stmt)
    value = result.scalar_one_or_none()
    return await maybe_await(value)


async def resolve_approval_request(
    session: AsyncSession,
    *,
    approval_id: str,
    status: str,
    payload: dict | None = None,
) -> bool:
    """Resolve one approval request."""
    values: dict[str, object] = {
        "status": status,
        "resolved_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    if payload is not None:
        values["payload"] = payload
    result = await session.execute(
        update(ApprovalRequest).where(ApprovalRequest.id == uuid.UUID(approval_id)).values(**values)
    )
    rowcount = getattr(result, "rowcount", 0)
    return isinstance(rowcount, int) and rowcount > 0


async def list_approval_requests(
    session: AsyncSession,
    *,
    workflow_id: str | None = None,
    limit: int = 25,
    status: str | None = None,
) -> Sequence[ApprovalRequest]:
    """List approval requests, optionally scoped to one workflow."""
    stmt = select(ApprovalRequest)
    if workflow_id is not None:
        stmt = stmt.where(ApprovalRequest.workflow_id == uuid.UUID(workflow_id))
    if status is not None:
        stmt = stmt.where(ApprovalRequest.status == status)
    stmt = stmt.order_by(ApprovalRequest.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    scalars = await maybe_await(result.scalars())
    rows = await maybe_await(scalars.all())
    return list(rows)


async def create_browser_session(
    session: AsyncSession,
    *,
    workflow_id: str,
    status: str = "planned",
    start_url: str | None = None,
    current_url: str | None = None,
    timeline: list[dict] | None = None,
    screenshot_artifacts: list[dict] | None = None,
    risk_flags: list[str] | None = None,
) -> BrowserSession:
    """Persist one browser fallback session."""
    record = BrowserSession(
        workflow_id=uuid.UUID(workflow_id),
        status=status,
        start_url=start_url,
        current_url=current_url,
        timeline=timeline or [],
        screenshot_artifacts=screenshot_artifacts or [],
        risk_flags=risk_flags,
    )
    add_result = session.add(record)
    if isawaitable(add_result):
        await add_result
    await session.flush()
    return record


async def list_browser_sessions(
    session: AsyncSession,
    *,
    workflow_id: str,
) -> Sequence[BrowserSession]:
    """List browser fallback sessions for one workflow."""
    stmt = (
        select(BrowserSession)
        .where(BrowserSession.workflow_id == uuid.UUID(workflow_id))
        .order_by(BrowserSession.created_at.asc())
    )
    result = await session.execute(stmt)
    scalars = await maybe_await(result.scalars())
    rows = await maybe_await(scalars.all())
    return list(rows)


async def list_recent_artifacts_for_user(
    session: AsyncSession,
    *,
    user_id: str,
    limit: int = 8,
    artifact_types: Sequence[str] | None = None,
) -> Sequence[ArtifactRecordModel]:
    """List recent persisted artifacts for one user.

    Returns an empty list for non-SQLAlchemy test doubles that do not produce
    a concrete row list.
    """
    stmt = (
        select(ArtifactRecordModel)
        .where(ArtifactRecordModel.user_id == user_id)
        .order_by(ArtifactRecordModel.created_at.desc())
        .limit(limit)
    )
    if artifact_types:
        stmt = stmt.where(ArtifactRecordModel.artifact_type.in_(tuple(artifact_types)))

    result = await session.execute(stmt)
    scalars = await maybe_await(result.scalars())
    rows = await maybe_await(scalars.all())
    if not isinstance(rows, (list, tuple)):
        return []
    return [row for row in rows if hasattr(row, "summary") and hasattr(row, "artifact_type")]


async def list_artifacts_for_workflow(
    session: AsyncSession,
    *,
    workflow_id: str,
    limit: int = 25,
) -> Sequence[ArtifactRecordModel]:
    """List persisted artifacts for one workflow."""
    stmt = (
        select(ArtifactRecordModel)
        .where(ArtifactRecordModel.workflow_id == workflow_id)
        .order_by(ArtifactRecordModel.created_at.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    scalars = await maybe_await(result.scalars())
    rows = await maybe_await(scalars.all())
    return list(rows)


async def list_tool_receipts(
    session: AsyncSession,
    *,
    limit: int = 50,
    workflow_id: str | None = None,
) -> Sequence[ToolReceipt]:
    """List recent tool receipts."""
    stmt = select(ToolReceipt)
    if workflow_id is not None:
        stmt = stmt.where(ToolReceipt.workflow_id == workflow_id)
    stmt = stmt.order_by(ToolReceipt.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    scalars = await maybe_await(result.scalars())
    rows = await maybe_await(scalars.all())
    return list(rows)


async def list_policy_decisions(
    session: AsyncSession,
    *,
    limit: int = 50,
) -> Sequence[PolicyDecisionRecord]:
    """List recent policy decisions."""
    stmt = (
        select(PolicyDecisionRecord).order_by(PolicyDecisionRecord.created_at.desc()).limit(limit)
    )
    result = await session.execute(stmt)
    scalars = await maybe_await(result.scalars())
    rows = await maybe_await(scalars.all())
    return list(rows)
