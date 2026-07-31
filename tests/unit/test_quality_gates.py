"""Tests for core quality-gate evaluation."""

from __future__ import annotations

from types import SimpleNamespace

from src.app.core.quality_gates import QualityGateThresholds, evaluate_quality_gates


def test_evaluate_quality_gates_detects_failing_metrics() -> None:
    interactions = [
        SimpleNamespace(
            trace_id="trace-1",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 0.96,
                "final_response_quality": 0.92,
            },
            channel_metrics={"render_passed": True},
        ),
        SimpleNamespace(
            trace_id="",
            quality_scores={
                "route_quality": 0.6,
                "channel_style": 0.70,
                "final_response_quality": 0.65,
            },
            channel_metrics={"render_passed": False},
        ),
    ]
    tool_receipts = [
        SimpleNamespace(
            status="executed",
            mutation_class="mutating",
            audit_metadata={"confirmation_required": True},
        ),
        SimpleNamespace(
            status="failed",
            mutation_class="mutating",
            audit_metadata={"confirmation_required": False},
        ),
    ]

    evaluation = evaluate_quality_gates(interactions, tool_receipts)

    assert evaluation.sample_sizes["interactions"] == 2
    assert evaluation.route_accuracy == 0.8
    assert evaluation.tool_execution_success_rate == 0.5
    assert evaluation.confirmation_coverage == 0.5
    assert "route_accuracy" in evaluation.failing_gates
    assert "tool_execution_success_rate" in evaluation.failing_gates
    assert "confirmation_coverage" in evaluation.failing_gates


def test_evaluate_quality_gates_empty_inputs() -> None:
    evaluation = evaluate_quality_gates([], [])

    assert evaluation.route_accuracy is None
    assert evaluation.renderer_pass_rate is None
    assert evaluation.trace_coverage is None
    assert evaluation.failing_gates == []
    assert evaluation.sample_sizes["interactions"] == 0


def test_evaluate_quality_gates_respects_custom_thresholds() -> None:
    interactions = [
        SimpleNamespace(
            trace_id="trace-1",
            quality_scores={
                "route_quality": 0.9,
                "channel_style": 0.90,
                "final_response_quality": 0.88,
            },
            channel_metrics={"render_passed": True},
        )
    ]
    thresholds = QualityGateThresholds(
        route_accuracy_target=0.85,
        channel_style_pass_rate_target=0.8,
        channel_style_score_threshold=0.85,
        final_response_quality_pass_rate_target=0.8,
        final_response_quality_score_threshold=0.85,
        renderer_pass_rate_target=0.9,
        trace_coverage_target=1.0,
        tool_execution_success_rate_target=0.9,
        confirmation_coverage_target=1.0,
    )

    evaluation = evaluate_quality_gates(interactions, [], thresholds=thresholds)

    assert evaluation.route_accuracy == 0.9
    assert evaluation.channel_style_pass_rate == 1.0
    assert evaluation.final_response_quality_pass_rate == 1.0
    assert evaluation.renderer_pass_rate == 1.0
    assert evaluation.failing_gates == []
