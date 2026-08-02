"""Replay evaluation and production-readiness operator routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_db
from src.app.core.assistant_native_evals import ASSISTANT_NATIVE_EVAL_DATASET_PATH

from .monitoring_models import (
    AssistantNativeEvalCaseDTO,
    AssistantNativeEvalSummaryDTO,
    QualityGatesDTO,
    ReleaseReadinessCheckDTO,
    ReleaseReadinessDTO,
)
from .monitoring_runtime import _evaluate_quality_gates_for_window

router = APIRouter()


@router.get("/ops/assistant-native-evals", response_model=AssistantNativeEvalSummaryDTO)
async def assistant_native_evals() -> AssistantNativeEvalSummaryDTO:
    """Return deterministic replay coverage for assistant-native continuity behavior."""
    from src.app.api.routes import monitoring as monitoring_facade

    asset_errors = monitoring_facade.validate_assistant_native_eval_assets()
    if asset_errors:
        return AssistantNativeEvalSummaryDTO(
            generated_at=datetime.now(UTC).isoformat(),
            dataset_id="assistant_native_continuity.v1",
            version="unknown",
            dataset_path=ASSISTANT_NATIVE_EVAL_DATASET_PATH.as_posix(),
            passing=False,
            case_count=0,
            pass_count=0,
            pass_rate=0.0,
            baseline_pass_count=0,
            baseline_pass_rate=0.0,
            baseline_lift=0.0,
            minimum_pass_rate_target=1.0,
            minimum_baseline_lift_target=0.0,
            minimum_case_count_target=1,
            failing_case_ids=[],
            asset_errors=asset_errors,
            cases=[],
        )

    result = monitoring_facade.evaluate_assistant_native_replays()
    return AssistantNativeEvalSummaryDTO(
        generated_at=result.generated_at.isoformat(),
        dataset_id=result.dataset_id,
        version=result.version,
        dataset_path=ASSISTANT_NATIVE_EVAL_DATASET_PATH.as_posix(),
        passing=result.passing,
        case_count=result.case_count,
        pass_count=result.pass_count,
        pass_rate=result.pass_rate,
        baseline_pass_count=result.baseline_pass_count,
        baseline_pass_rate=result.baseline_pass_rate,
        baseline_lift=result.baseline_lift,
        minimum_pass_rate_target=result.minimum_pass_rate_target,
        minimum_baseline_lift_target=result.minimum_baseline_lift_target,
        minimum_case_count_target=result.minimum_case_count_target,
        failing_case_ids=result.failing_case_ids,
        asset_errors=[],
        cases=[
            AssistantNativeEvalCaseDTO(
                id=case.id,
                description=case.description,
                passed=case.passed,
                baseline_passed=case.baseline_passed,
                current_resolution_type=case.current_resolution_type,
                baseline_resolution_type=case.baseline_resolution_type,
                current_forced_specialist=case.current_forced_specialist,
                failures=case.failures,
            )
            for case in result.cases
        ],
    )


@router.get("/ops/release-readiness", response_model=ReleaseReadinessDTO)
async def release_readiness(
    request: Request,
    session: AsyncSession = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
    limit: int = Query(2000, ge=100, le=10000),
) -> ReleaseReadinessDTO:
    """Return production-readiness status against runtime quality and ops gates."""
    from src.app.api.routes import monitoring as monitoring_facade

    settings = monitoring_facade.get_settings()
    assistant_native_asset_errors = monitoring_facade.validate_assistant_native_eval_assets()
    assistant_native_eval = (
        monitoring_facade.evaluate_assistant_native_replays()
        if not assistant_native_asset_errors
        else None
    )
    evaluation, thresholds = await _evaluate_quality_gates_for_window(
        session=session,
        settings=settings,
        window_days=window_days,
        limit=limit,
    )

    quality = QualityGatesDTO(
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

    preflight_report = getattr(request.app.state, "preflight_report", None)
    if preflight_report is None:
        preflight_report = getattr(request.app.state, "startup_preflight_report", None)
    preflight_status = None
    if preflight_report is not None:
        preflight_status = getattr(preflight_report, "status", None)
        if preflight_status is None and isinstance(preflight_report, dict):
            preflight_status = preflight_report.get("status")

    minimum_interactions = int(getattr(settings, "quality_gates_alert_min_interactions", 25))
    interaction_count = int(quality.sample_sizes.get("interactions", 0))

    checks = [
        ReleaseReadinessCheckDTO(
            name="quality_gates_pass",
            passed=len(quality.failing_gates) == 0,
            value=len(quality.failing_gates) == 0,
            target=True,
            detail=(
                ", ".join(quality.failing_gates)
                if quality.failing_gates
                else "all quality gates passing"
            ),
        ),
        ReleaseReadinessCheckDTO(
            name="quality_gate_sample_size",
            passed=interaction_count >= minimum_interactions,
            value=interaction_count,
            target=minimum_interactions,
            detail="minimum recent interactions required for reliable gate scoring",
        ),
        ReleaseReadinessCheckDTO(
            name="workflow_live_runtime_enabled",
            passed=bool(settings.workflow_live_runtime_enabled),
            value=bool(settings.workflow_live_runtime_enabled),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="auto_judge_enabled",
            passed=bool(settings.auto_judge_enabled),
            value=bool(settings.auto_judge_enabled),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="quality_gates_alerts_enabled",
            passed=bool(settings.quality_gates_alerts_enabled),
            value=bool(settings.quality_gates_alerts_enabled),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="session_maintenance_enabled",
            passed=bool(settings.session_maintenance_enabled),
            value=bool(settings.session_maintenance_enabled),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="continuity_runtime_enabled",
            passed=bool(getattr(settings, "continuity_runtime_enabled", True)),
            value=bool(getattr(settings, "continuity_runtime_enabled", True)),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="project_draft_runtime_enabled",
            passed=bool(getattr(settings, "project_draft_runtime_enabled", True)),
            value=bool(getattr(settings, "project_draft_runtime_enabled", True)),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="notes_workspace_enabled",
            passed=bool(getattr(settings, "notes_workspace_enabled", True)),
            value=bool(getattr(settings, "notes_workspace_enabled", True)),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="content_factory_enabled",
            passed=bool(getattr(settings, "content_factory_enabled", True)),
            value=bool(getattr(settings, "content_factory_enabled", True)),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="assistant_native_replay_eval_enabled",
            passed=bool(getattr(settings, "assistant_native_replay_eval_enabled", True)),
            value=bool(getattr(settings, "assistant_native_replay_eval_enabled", True)),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="assistant_native_replay_assets",
            passed=not assistant_native_asset_errors,
            value="ok" if not assistant_native_asset_errors else "invalid",
            target="ok",
            detail=", ".join(assistant_native_asset_errors[:3]) or None,
        ),
        ReleaseReadinessCheckDTO(
            name="assistant_native_replay_pass_rate",
            passed=assistant_native_eval is not None
            and assistant_native_eval.pass_rate
            >= float(getattr(settings, "assistant_native_replay_pass_rate_target", 1.0)),
            value=(
                round(assistant_native_eval.pass_rate, 4)
                if assistant_native_eval is not None
                else None
            ),
            target=float(getattr(settings, "assistant_native_replay_pass_rate_target", 1.0)),
            detail=(
                ", ".join(assistant_native_eval.failing_case_ids)
                if assistant_native_eval is not None and assistant_native_eval.failing_case_ids
                else ("all replay cases passing" if assistant_native_eval is not None else None)
            ),
        ),
        ReleaseReadinessCheckDTO(
            name="assistant_native_replay_baseline_lift",
            passed=(
                assistant_native_eval is not None
                and assistant_native_eval.baseline_lift
                >= float(getattr(settings, "assistant_native_replay_baseline_lift_target", 0.5))
            ),
            value=(
                round(assistant_native_eval.baseline_lift, 4)
                if assistant_native_eval is not None
                else None
            ),
            target=float(getattr(settings, "assistant_native_replay_baseline_lift_target", 0.5)),
        ),
        ReleaseReadinessCheckDTO(
            name="sentry_configured",
            passed=bool(settings.sentry_configured),
            value=bool(settings.sentry_configured),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="posthog_configured",
            passed=bool(settings.posthog_configured),
            value=bool(settings.posthog_configured),
            target=True,
        ),
        ReleaseReadinessCheckDTO(
            name="startup_preflight",
            passed=preflight_status in {"ok", "warn"},
            value=preflight_status or "missing",
            target="ok|warn",
            detail="startup preflight report should be present and non-failing",
        ),
    ]

    failing_checks = [check.name for check in checks if not check.passed]
    ready = len(failing_checks) == 0

    return ReleaseReadinessDTO(
        generated_at=datetime.now(UTC).isoformat(),
        ready=ready,
        failing_checks=failing_checks,
        gate_failures=quality.failing_gates,
        checks=checks,
        quality_gates=quality,
    )
