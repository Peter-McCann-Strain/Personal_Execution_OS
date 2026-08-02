"""Workflow, policy, receipt, and quality-gate operator routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_db
from src.app.core.quality_gates import QualityGateThresholds, evaluate_quality_gates
from src.app.domain.constants import WorkflowStatus
from src.app.persistence.models import InteractionRecord, ToolReceipt, WorkflowRun

from .monitoring_common import (
    _optional_bool_field,
    _optional_dict_field,
    _optional_float_field,
    _optional_int_field,
    _optional_string_field,
    _policy_decision_to_dto,
    _tool_receipt_to_dto,
)
from .monitoring_models import (
    PolicyDecisionDTO,
    QualityGatesDTO,
    ToolReceiptDTO,
    WorkflowRuntimeDTO,
    WorkflowShadowDTO,
)

router = APIRouter()


def _quality_gate_thresholds_from_settings(settings) -> QualityGateThresholds:
    """Build quality-gate threshold settings used across ops endpoints."""
    return QualityGateThresholds(
        route_accuracy_target=settings.quality_gate_route_accuracy_target,
        channel_style_pass_rate_target=settings.quality_gate_channel_style_pass_rate_target,
        channel_style_score_threshold=settings.quality_gate_channel_style_score_threshold,
        final_response_quality_pass_rate_target=(
            settings.quality_gate_final_response_quality_pass_rate_target
        ),
        final_response_quality_score_threshold=(
            settings.quality_gate_final_response_quality_score_threshold
        ),
        renderer_pass_rate_target=settings.quality_gate_renderer_pass_rate_target,
        trace_coverage_target=settings.quality_gate_trace_coverage_target,
        tool_execution_success_rate_target=settings.quality_gate_tool_execution_success_rate_target,
        confirmation_coverage_target=settings.quality_gate_confirmation_coverage_target,
    )


async def _evaluate_quality_gates_for_window(
    *,
    session: AsyncSession,
    settings,
    window_days: int,
    limit: int,
):
    """Load recent records and evaluate quality gates for a time window."""
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    thresholds = _quality_gate_thresholds_from_settings(settings)

    interaction_stmt = (
        select(InteractionRecord)
        .where(InteractionRecord.created_at >= cutoff)
        .order_by(InteractionRecord.created_at.desc())
        .limit(limit)
    )
    interaction_result = await session.execute(interaction_stmt)
    interactions = list(interaction_result.scalars().all())

    tool_stmt = (
        select(ToolReceipt)
        .where(ToolReceipt.created_at >= cutoff)
        .order_by(ToolReceipt.created_at.desc())
        .limit(limit)
    )
    tool_result = await session.execute(tool_stmt)
    tool_receipts = list(tool_result.scalars().all())

    evaluation = evaluate_quality_gates(
        interactions,
        tool_receipts,
        thresholds=thresholds,
    )
    return evaluation, thresholds


@router.get("/ops/tool-receipts", response_model=list[ToolReceiptDTO])
async def tool_receipts(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=250),
) -> list[ToolReceiptDTO]:
    """List recent tool receipts for operator inspection."""
    from src.app.api.routes import monitoring as monitoring_facade

    records = await monitoring_facade.list_tool_receipts(session, limit=limit)
    return [_tool_receipt_to_dto(record) for record in records]


@router.get("/ops/policy-decisions", response_model=list[PolicyDecisionDTO])
async def policy_decisions(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=250),
) -> list[PolicyDecisionDTO]:
    """List recent runtime policy decisions."""
    from src.app.api.routes import monitoring as monitoring_facade

    records = await monitoring_facade.list_policy_decisions(session, limit=limit)
    return [_policy_decision_to_dto(record) for record in records]


@router.get("/ops/workflow-shadows", response_model=list[WorkflowShadowDTO])
async def workflow_shadows(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=250),
) -> list[WorkflowShadowDTO]:
    """List recent shadow workflow comparisons."""
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.status == str(WorkflowStatus.SHADOW))
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    records = list(result.scalars().all())

    shadows: list[WorkflowShadowDTO] = []
    for record in records:
        metadata = _optional_dict_field(getattr(record, "metadata_", None)) or {}
        shadows.append(
            WorkflowShadowDTO(
                workflow_id=str(record.id),
                live_workflow_id=_optional_string_field(metadata.get("live_workflow_id")),
                trace_id=_optional_string_field(getattr(record, "trace_id", None)),
                source=record.source,
                live_specialist=_optional_string_field(metadata.get("live_specialist")),
                shadow_specialist=_optional_string_field(getattr(record, "specialist", None))
                or _optional_string_field(metadata.get("shadow_specialist")),
                route_match=_optional_bool_field(metadata.get("route_match")),
                shadow_status=_optional_string_field(metadata.get("shadow_status")),
                executed=bool(metadata.get("executed", False)),
                skipped_reason=_optional_string_field(metadata.get("skipped_reason")),
                confidence=_optional_float_field(metadata.get("confidence")),
                latency_ms=_optional_int_field(metadata.get("latency_ms")),
                result_preview=_optional_string_field(metadata.get("result_preview")),
                created_at=record.created_at.isoformat(),
            )
        )
    return shadows


@router.get("/ops/workflow-runtimes", response_model=list[WorkflowRuntimeDTO])
async def workflow_runtimes(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=250),
) -> list[WorkflowRuntimeDTO]:
    """List recent live workflow-runtime execution outcomes."""
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.status != str(WorkflowStatus.SHADOW))
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    records = list(result.scalars().all())

    runtimes: list[WorkflowRuntimeDTO] = []
    for record in records:
        metadata = _optional_dict_field(getattr(record, "metadata_", None)) or {}
        runtime = _optional_dict_field(metadata.get("workflow_runtime"))
        if not runtime:
            continue
        runtimes.append(
            WorkflowRuntimeDTO(
                workflow_id=str(record.id),
                trace_id=_optional_string_field(getattr(record, "trace_id", None)),
                response_id=_optional_string_field(getattr(record, "response_id", None)),
                source=record.source,
                specialist=_optional_string_field(getattr(record, "specialist", None)),
                workflow_status=record.status,
                runtime_mode=_optional_string_field(runtime.get("mode")),
                runtime_status=_optional_string_field(runtime.get("status")),
                executed=_optional_bool_field(runtime.get("executed")),
                fallback_used=_optional_bool_field(runtime.get("fallback_used")),
                reason=_optional_string_field(runtime.get("reason")),
                latency_ms=_optional_int_field(runtime.get("latency_ms")),
                response_agent=_optional_string_field(runtime.get("response_agent")),
                response_preview=_optional_string_field(runtime.get("response_preview")),
                created_at=record.created_at.isoformat(),
            )
        )

    return runtimes


@router.get("/ops/quality-gates", response_model=QualityGatesDTO)
async def quality_gates(
    session: AsyncSession = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
    limit: int = Query(2000, ge=100, le=10000),
) -> QualityGatesDTO:
    """Return measured quality-gate performance over a recent window."""
    from src.app.api.routes import monitoring as monitoring_facade

    settings = monitoring_facade.get_settings()
    evaluation, thresholds = await _evaluate_quality_gates_for_window(
        session=session,
        settings=settings,
        window_days=window_days,
        limit=limit,
    )

    return QualityGatesDTO(
        generated_at=datetime.now(UTC).isoformat(),
        route_accuracy=(
            round(evaluation.route_accuracy, 4) if evaluation.route_accuracy is not None else None
        ),
        route_accuracy_target=thresholds.route_accuracy_target,
        channel_style_pass_rate=(
            round(evaluation.channel_style_pass_rate, 4)
            if evaluation.channel_style_pass_rate is not None
            else None
        ),
        channel_style_target=thresholds.channel_style_pass_rate_target,
        final_response_quality_pass_rate=(
            round(evaluation.final_response_quality_pass_rate, 4)
            if evaluation.final_response_quality_pass_rate is not None
            else None
        ),
        final_response_quality_target=thresholds.final_response_quality_pass_rate_target,
        renderer_pass_rate=(
            round(evaluation.renderer_pass_rate, 4)
            if evaluation.renderer_pass_rate is not None
            else None
        ),
        renderer_pass_rate_target=thresholds.renderer_pass_rate_target,
        trace_coverage=(
            round(evaluation.trace_coverage, 4) if evaluation.trace_coverage is not None else None
        ),
        trace_coverage_target=thresholds.trace_coverage_target,
        tool_execution_success_rate=(
            round(evaluation.tool_execution_success_rate, 4)
            if evaluation.tool_execution_success_rate is not None
            else None
        ),
        tool_execution_success_rate_target=thresholds.tool_execution_success_rate_target,
        confirmation_coverage=(
            round(evaluation.confirmation_coverage, 4)
            if evaluation.confirmation_coverage is not None
            else None
        ),
        confirmation_coverage_target=thresholds.confirmation_coverage_target,
        sample_sizes=evaluation.sample_sizes,
        failing_gates=evaluation.failing_gates,
    )
