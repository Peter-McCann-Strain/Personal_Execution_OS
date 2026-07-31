"""Runtime quality-gate evaluation shared by API monitoring and workers."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field


class QualityGateThresholds(BaseModel):
    """Thresholds and score cutoffs for world-class quality gates."""

    route_accuracy_target: float = 0.95
    channel_style_pass_rate_target: float = 0.95
    channel_style_score_threshold: float = 0.95
    final_response_quality_pass_rate_target: float = 0.90
    final_response_quality_score_threshold: float = 0.90
    renderer_pass_rate_target: float = 0.95
    trace_coverage_target: float = 1.0
    tool_execution_success_rate_target: float = 0.90
    confirmation_coverage_target: float = 1.0


class QualityGateEvaluation(BaseModel):
    """Computed quality-gate metrics over one observation window."""

    route_accuracy: float | None = None
    channel_style_pass_rate: float | None = None
    final_response_quality_pass_rate: float | None = None
    renderer_pass_rate: float | None = None
    trace_coverage: float | None = None
    tool_execution_success_rate: float | None = None
    confirmation_coverage: float | None = None
    sample_sizes: dict[str, int] = Field(default_factory=dict)
    failing_gates: list[str] = Field(default_factory=list)


def evaluate_quality_gates(
    interactions: Sequence[object],
    tool_receipts: Sequence[object],
    *,
    thresholds: QualityGateThresholds | None = None,
) -> QualityGateEvaluation:
    """Evaluate quality-gate metrics for recent interactions and tool receipts."""
    thresholds = thresholds or QualityGateThresholds()

    route_scores: list[float] = []
    channel_style_values: list[float] = []
    final_quality_values: list[float] = []
    render_pass_values: list[bool] = []
    trace_count = 0

    for record in interactions:
        trace_id = _as_str(getattr(record, "trace_id", None))
        if trace_id:
            trace_count += 1

        quality_scores = _as_dict(getattr(record, "quality_scores", None))
        channel_metrics = _as_dict(getattr(record, "channel_metrics", None))

        route_quality = _as_float(quality_scores.get("route_quality"))
        if route_quality is not None:
            route_scores.append(route_quality)

        channel_style = _as_float(quality_scores.get("channel_style"))
        if channel_style is not None:
            channel_style_values.append(channel_style)

        final_quality = _as_float(quality_scores.get("final_response_quality"))
        if final_quality is not None:
            final_quality_values.append(final_quality)

        render_passed = channel_metrics.get("render_passed")
        if isinstance(render_passed, bool):
            render_pass_values.append(render_passed)

    tool_success_values: list[bool] = []
    confirmation_values: list[bool] = []
    for receipt in tool_receipts:
        status = _as_str(getattr(receipt, "status", None))
        if status in {"executed", "failed"}:
            tool_success_values.append(status == "executed")

        mutation_class = _as_str(getattr(receipt, "mutation_class", None))
        audit_metadata = _as_dict(getattr(receipt, "audit_metadata", None))
        if mutation_class == "mutating":
            confirmation_values.append(audit_metadata.get("confirmation_required") is True)

    route_accuracy = _mean(route_scores)
    channel_style_pass_rate = (
        _pass_rate(
            [value >= thresholds.channel_style_score_threshold for value in channel_style_values]
        )
        if channel_style_values
        else None
    )
    final_response_quality_pass_rate = (
        _pass_rate(
            [
                value >= thresholds.final_response_quality_score_threshold
                for value in final_quality_values
            ]
        )
        if final_quality_values
        else None
    )
    renderer_pass_rate = _pass_rate(render_pass_values)
    trace_coverage = trace_count / len(interactions) if interactions else None
    tool_execution_success_rate = _pass_rate(tool_success_values)
    confirmation_coverage = _pass_rate(confirmation_values)

    failing_gates: list[str] = []
    if route_accuracy is not None and route_accuracy < thresholds.route_accuracy_target:
        failing_gates.append("route_accuracy")
    if (
        channel_style_pass_rate is not None
        and channel_style_pass_rate < thresholds.channel_style_pass_rate_target
    ):
        failing_gates.append("channel_style_pass_rate")
    if (
        final_response_quality_pass_rate is not None
        and final_response_quality_pass_rate < thresholds.final_response_quality_pass_rate_target
    ):
        failing_gates.append("final_response_quality_pass_rate")
    if renderer_pass_rate is not None and renderer_pass_rate < thresholds.renderer_pass_rate_target:
        failing_gates.append("renderer_pass_rate")
    if trace_coverage is not None and trace_coverage < thresholds.trace_coverage_target:
        failing_gates.append("trace_coverage")
    if (
        tool_execution_success_rate is not None
        and tool_execution_success_rate < thresholds.tool_execution_success_rate_target
    ):
        failing_gates.append("tool_execution_success_rate")
    if (
        confirmation_coverage is not None
        and confirmation_coverage < thresholds.confirmation_coverage_target
    ):
        failing_gates.append("confirmation_coverage")

    return QualityGateEvaluation(
        route_accuracy=route_accuracy,
        channel_style_pass_rate=channel_style_pass_rate,
        final_response_quality_pass_rate=final_response_quality_pass_rate,
        renderer_pass_rate=renderer_pass_rate,
        trace_coverage=trace_coverage,
        tool_execution_success_rate=tool_execution_success_rate,
        confirmation_coverage=confirmation_coverage,
        sample_sizes={
            "interactions": len(interactions),
            "route_scores": len(route_scores),
            "channel_style_scores": len(channel_style_values),
            "final_response_quality_scores": len(final_quality_values),
            "renderer_records": len(render_pass_values),
            "tool_receipts": len(tool_receipts),
            "tool_execution_records": len(tool_success_values),
            "mutating_tool_receipts": len(confirmation_values),
        },
        failing_gates=failing_gates,
    )


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _as_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _pass_rate(values: list[bool]) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value) / len(values)
