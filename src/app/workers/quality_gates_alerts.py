"""Quality-gate alerts — checks multidimensional runtime gates and notifies Telegram."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from aiogram import Bot
from sqlalchemy import select

from src.app.config import Settings
from src.app.core.assistant_native_evals import (
    evaluate_assistant_native_replays,
    validate_assistant_native_eval_assets,
)
from src.app.core.quality_gates import QualityGateThresholds, evaluate_quality_gates
from src.app.persistence.models import InteractionRecord, PolicyDecisionRecord, ToolReceipt
from src.app.workers.github_filer import AlertRecord, file_github_issue

logger = structlog.get_logger()


def _format_metric(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


async def run_quality_gates_alerts(ctx: dict) -> None:
    """Evaluate world-class quality gates and alert if any fail."""
    settings: Settings = ctx["settings"]
    bot: Bot | None = ctx.get("bot")
    session_factory = ctx["session_factory"]

    if not settings.quality_gates_alerts_enabled:
        logger.info("quality_gates_alerts_disabled")
        return
    if bot is None:
        logger.warning("quality_gates_alerts_no_bot", hint="Telegram not configured")
        return

    thresholds = QualityGateThresholds(
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

    cutoff = datetime.now(UTC) - timedelta(days=settings.quality_gates_alert_window_days)
    async with session_factory() as session:
        interaction_stmt = (
            select(InteractionRecord)
            .where(InteractionRecord.created_at >= cutoff)
            .order_by(InteractionRecord.created_at.desc())
            .limit(settings.quality_gates_alert_limit)
        )
        interaction_result = await session.execute(interaction_stmt)
        interactions = list(interaction_result.scalars().all())

        tool_stmt = (
            select(ToolReceipt)
            .where(ToolReceipt.created_at >= cutoff)
            .order_by(ToolReceipt.created_at.desc())
            .limit(settings.quality_gates_alert_limit)
        )
        tool_result = await session.execute(tool_stmt)
        tool_receipts = list(tool_result.scalars().all())

        policy_stmt = (
            select(PolicyDecisionRecord)
            .where(PolicyDecisionRecord.created_at >= cutoff)
            .order_by(PolicyDecisionRecord.created_at.desc())
            .limit(settings.quality_gates_alert_limit)
        )
        policy_result = await session.execute(policy_stmt)
        policy_decisions = list(policy_result.scalars().all())

    evaluation = evaluate_quality_gates(
        interactions,
        tool_receipts,
        thresholds=thresholds,
    )

    readiness_failures: list[str] = []
    if not bool(getattr(settings, "workflow_live_runtime_enabled", False)):
        readiness_failures.append("workflow_live_runtime_disabled")
    if not bool(getattr(settings, "auto_judge_enabled", False)):
        readiness_failures.append("auto_judge_disabled")
    if not bool(getattr(settings, "session_maintenance_enabled", False)):
        readiness_failures.append("session_maintenance_disabled")
    if not bool(getattr(settings, "sentry_configured", False)):
        readiness_failures.append("sentry_not_configured")
    if not bool(getattr(settings, "posthog_configured", False)):
        readiness_failures.append("posthog_not_configured")
    if not bool(getattr(settings, "assistant_native_replay_eval_enabled", True)):
        readiness_failures.append("assistant_native_replay_eval_disabled")

    assistant_native_asset_errors = validate_assistant_native_eval_assets()
    assistant_native_eval = (
        evaluate_assistant_native_replays() if not assistant_native_asset_errors else None
    )
    if assistant_native_asset_errors:
        readiness_failures.append(
            "assistant_native_replay_assets_invalid=" + "|".join(assistant_native_asset_errors[:2])
        )
    elif assistant_native_eval is not None:
        pass_rate_target = float(getattr(settings, "assistant_native_replay_pass_rate_target", 1.0))
        baseline_lift_target = float(
            getattr(settings, "assistant_native_replay_baseline_lift_target", 0.5)
        )
        if assistant_native_eval.pass_rate < pass_rate_target:
            readiness_failures.append(
                "assistant_native_replay_pass_rate="
                f"{assistant_native_eval.pass_rate:.2f}<{pass_rate_target:.2f}"
            )
        if assistant_native_eval.baseline_lift < baseline_lift_target:
            readiness_failures.append(
                "assistant_native_replay_baseline_lift="
                f"{assistant_native_eval.baseline_lift:.2f}<{baseline_lift_target:.2f}"
            )

    mutating_without_confirmation = sum(
        1
        for receipt in tool_receipts
        if str(getattr(receipt, "mutation_class", "")) == "mutating"
        and not bool(
            (getattr(receipt, "audit_metadata", None) or {}).get(
                "confirmation_required",
                False,
            )
        )
    )
    idempotency_counts: dict[str, int] = {}
    for receipt in tool_receipts:
        key = str(getattr(receipt, "idempotency_key", "") or "")
        if key:
            idempotency_counts[key] = idempotency_counts.get(key, 0) + 1
    duplicate_idempotency = sum(count - 1 for count in idempotency_counts.values() if count > 1)
    instruction_risk_decisions = sum(
        1
        for decision in policy_decisions
        if str(getattr(decision, "policy_name", "")) == "instruction_like_content"
    )
    trust_boundary_denies = sum(
        1
        for decision in policy_decisions
        if str(getattr(decision, "policy_name", "")) == "tool_trust_boundary"
        and str(getattr(decision, "decision", "")) == "deny"
    )

    security_failures: list[str] = []
    if (
        mutating_without_confirmation
        > settings.quality_gates_security_max_mutating_without_confirmation
    ):
        security_failures.append(
            "mutating_without_confirmation="
            f"{mutating_without_confirmation}>{settings.quality_gates_security_max_mutating_without_confirmation}"
        )
    if duplicate_idempotency > settings.quality_gates_security_max_duplicate_idempotency:
        security_failures.append(
            "duplicate_idempotency="
            f"{duplicate_idempotency}>{settings.quality_gates_security_max_duplicate_idempotency}"
        )
    if instruction_risk_decisions > settings.quality_gates_security_max_instruction_risk_decisions:
        security_failures.append(
            "instruction_risk_decisions="
            f"{instruction_risk_decisions}>{settings.quality_gates_security_max_instruction_risk_decisions}"
        )
    if trust_boundary_denies > settings.quality_gates_security_max_trust_boundary_denies:
        security_failures.append(
            "trust_boundary_denies="
            f"{trust_boundary_denies}>{settings.quality_gates_security_max_trust_boundary_denies}"
        )

    if (
        evaluation.sample_sizes.get("interactions", 0)
        < settings.quality_gates_alert_min_interactions
    ):
        logger.info(
            "quality_gates_alerts_insufficient_samples",
            interactions=evaluation.sample_sizes.get("interactions", 0),
            min_required=settings.quality_gates_alert_min_interactions,
        )
        return

    if not evaluation.failing_gates and not readiness_failures and not security_failures:
        logger.info("quality_gates_alerts_none")
        return

    user_ids = settings.allowed_user_ids
    if not user_ids:
        logger.warning("quality_gates_alerts_no_user_ids")
        return

    metric_lines = [
        "Route accuracy: "
        f"{_format_metric(evaluation.route_accuracy)} "
        f"(target {thresholds.route_accuracy_target:.0%})",
        (
            "Channel style pass rate: "
            f"{_format_metric(evaluation.channel_style_pass_rate)} "
            f"(target {thresholds.channel_style_pass_rate_target:.0%})"
        ),
        (
            "Final response pass rate: "
            f"{_format_metric(evaluation.final_response_quality_pass_rate)} "
            f"(target {thresholds.final_response_quality_pass_rate_target:.0%})"
        ),
        (
            "Renderer pass rate: "
            f"{_format_metric(evaluation.renderer_pass_rate)} "
            f"(target {thresholds.renderer_pass_rate_target:.0%})"
        ),
        (
            "Trace coverage: "
            f"{_format_metric(evaluation.trace_coverage)} "
            f"(target {thresholds.trace_coverage_target:.0%})"
        ),
        (
            "Tool execution success: "
            f"{_format_metric(evaluation.tool_execution_success_rate)} "
            f"(target {thresholds.tool_execution_success_rate_target:.0%})"
        ),
        (
            "Confirmation coverage: "
            f"{_format_metric(evaluation.confirmation_coverage)} "
            f"(target {thresholds.confirmation_coverage_target:.0%})"
        ),
    ]

    message = (
        "Quality Gate Alert\n\n"
        f"Window: last {settings.quality_gates_alert_window_days} day(s)\n"
        f"Failed gates: {', '.join(evaluation.failing_gates)}\n\n"
        + "\n".join(metric_lines)
        + "\n\n"
        f"Samples: {evaluation.sample_sizes}"
    )
    if assistant_native_eval is not None:
        message += (
            "\n\nAssistant-native replays: "
            f"{assistant_native_eval.pass_count}/{assistant_native_eval.case_count} passing "
            f"(baseline lift {assistant_native_eval.baseline_lift:.2f})"
        )
    if readiness_failures:
        message += "\n\nReadiness checks failing: " + ", ".join(readiness_failures)
    if security_failures:
        message += "\n\nSecurity checks failing: " + ", ".join(security_failures)

    try:
        await bot.send_message(chat_id=user_ids[0], text=message)
        logger.info(
            "quality_gates_alert_sent",
            failing_gates=evaluation.failing_gates,
            readiness_failures=readiness_failures,
            security_failures=security_failures,
            interactions=evaluation.sample_sizes.get("interactions", 0),
        )
    except Exception:
        logger.exception("quality_gates_alert_send_failed")
        raise

    # --- Secondary fan-out: GitHub issue (Phase 3.9) ----------------------
    try:
        alert = AlertRecord(
            category="quality_gates",
            title=(
                "Quality gate failure: "
                + ", ".join(evaluation.failing_gates[:3])
                + (" + more" if len(evaluation.failing_gates) > 3 else "")
            )[:120],
            summary=(
                f"{len(evaluation.failing_gates)} gate(s) failing in the "
                f"last {settings.quality_gates_alert_window_days} day(s). "
                f"Readiness failures: {len(readiness_failures)}, "
                f"security failures: {len(security_failures)}."
            ),
            key_fields={
                "failing_gates": "|".join(sorted(evaluation.failing_gates)),
                "readiness_failures": "|".join(sorted(readiness_failures)),
                "security_failures": "|".join(sorted(security_failures)),
            },
            context={"Detail": message},
        )
        await file_github_issue(
            alert,
            settings=settings,
            session_factory=session_factory,
        )
    except Exception:
        logger.warning("quality_gates_alert_github_filer_failed", exc_info=True)
