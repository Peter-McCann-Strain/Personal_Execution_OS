"""Tests for quality-gate alert worker."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.workers.quality_gates_alerts import run_quality_gates_alerts


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.quality_gates_alerts_enabled = True
    settings.quality_gates_alert_window_days = 7
    settings.quality_gates_alert_limit = 2000
    settings.quality_gates_alert_min_interactions = 2
    settings.quality_gates_security_max_mutating_without_confirmation = 0
    settings.quality_gates_security_max_duplicate_idempotency = 0
    settings.quality_gates_security_max_instruction_risk_decisions = 5
    settings.quality_gates_security_max_trust_boundary_denies = 10
    settings.quality_gate_route_accuracy_target = 0.95
    settings.quality_gate_channel_style_pass_rate_target = 0.95
    settings.quality_gate_channel_style_score_threshold = 0.95
    settings.quality_gate_final_response_quality_pass_rate_target = 0.90
    settings.quality_gate_final_response_quality_score_threshold = 0.90
    settings.quality_gate_renderer_pass_rate_target = 0.95
    settings.quality_gate_trace_coverage_target = 1.0
    settings.quality_gate_tool_execution_success_rate_target = 0.90
    settings.quality_gate_confirmation_coverage_target = 1.0
    settings.workflow_live_runtime_enabled = True
    settings.auto_judge_enabled = True
    settings.session_maintenance_enabled = True
    settings.assistant_native_replay_eval_enabled = True
    settings.assistant_native_replay_pass_rate_target = 1.0
    settings.assistant_native_replay_baseline_lift_target = 0.5
    settings.sentry_configured = True
    settings.posthog_configured = True
    settings.allowed_user_ids = [12345]
    return settings


def _make_session_factory(session: AsyncMock):
    @asynccontextmanager
    async def factory():
        yield session

    return factory


@pytest.mark.asyncio
async def test_quality_gates_alerts_skips_without_bot() -> None:
    ctx = {
        "settings": _make_settings(),
        "bot": None,
        "session_factory": AsyncMock(),
    }

    await run_quality_gates_alerts(ctx)


@pytest.mark.asyncio
async def test_quality_gates_alerts_sends_alert_for_failed_gates() -> None:
    bot = AsyncMock()
    session = AsyncMock()
    ctx = {
        "settings": _make_settings(),
        "bot": bot,
        "session_factory": _make_session_factory(session),
    }

    interactions = [
        SimpleNamespace(
            created_at=datetime.now(UTC),
            trace_id="trace-1",
            quality_scores={
                "route_quality": 0.4,
                "channel_style": 0.5,
                "final_response_quality": 0.6,
            },
            channel_metrics={"render_passed": False},
        ),
        SimpleNamespace(
            created_at=datetime.now(UTC),
            trace_id="",
            quality_scores={
                "route_quality": 0.5,
                "channel_style": 0.4,
                "final_response_quality": 0.5,
            },
            channel_metrics={"render_passed": False},
        ),
    ]
    receipts = [
        SimpleNamespace(
            created_at=datetime.now(UTC),
            status="failed",
            mutation_class="mutating",
            audit_metadata={"confirmation_required": False},
        )
    ]

    interactions_result = MagicMock()
    interactions_result.scalars.return_value.all.return_value = interactions
    tool_result = MagicMock()
    tool_result.scalars.return_value.all.return_value = receipts
    policy_result = MagicMock()
    policy_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(side_effect=[interactions_result, tool_result, policy_result])

    await run_quality_gates_alerts(ctx)

    bot.send_message.assert_awaited_once()
    sent_text = bot.send_message.call_args.kwargs["text"]
    assert "Quality Gate Alert" in sent_text
    assert "Failed gates:" in sent_text
    assert "route_accuracy" in sent_text


@pytest.mark.asyncio
async def test_quality_gates_alerts_skips_when_no_failures() -> None:
    bot = AsyncMock()
    session = AsyncMock()
    ctx = {
        "settings": _make_settings(),
        "bot": bot,
        "session_factory": _make_session_factory(session),
    }

    interactions = [
        SimpleNamespace(
            created_at=datetime.now(UTC),
            trace_id="trace-1",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 1.0,
                "final_response_quality": 1.0,
            },
            channel_metrics={"render_passed": True},
        ),
        SimpleNamespace(
            created_at=datetime.now(UTC),
            trace_id="trace-2",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 1.0,
                "final_response_quality": 1.0,
            },
            channel_metrics={"render_passed": True},
        ),
    ]
    receipts = [
        SimpleNamespace(
            created_at=datetime.now(UTC),
            status="executed",
            mutation_class="mutating",
            audit_metadata={"confirmation_required": True},
        )
    ]

    interactions_result = MagicMock()
    interactions_result.scalars.return_value.all.return_value = interactions
    tool_result = MagicMock()
    tool_result.scalars.return_value.all.return_value = receipts
    policy_result = MagicMock()
    policy_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(side_effect=[interactions_result, tool_result, policy_result])

    await run_quality_gates_alerts(ctx)

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_quality_gates_alerts_reports_readiness_failures_even_when_gates_pass() -> None:
    bot = AsyncMock()
    session = AsyncMock()
    settings = _make_settings()
    settings.workflow_live_runtime_enabled = False
    ctx = {
        "settings": settings,
        "bot": bot,
        "session_factory": _make_session_factory(session),
    }

    interactions = [
        SimpleNamespace(
            created_at=datetime.now(UTC),
            trace_id="trace-1",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 1.0,
                "final_response_quality": 1.0,
            },
            channel_metrics={"render_passed": True},
        ),
        SimpleNamespace(
            created_at=datetime.now(UTC),
            trace_id="trace-2",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 1.0,
                "final_response_quality": 1.0,
            },
            channel_metrics={"render_passed": True},
        ),
    ]
    receipts = [
        SimpleNamespace(
            created_at=datetime.now(UTC),
            status="executed",
            mutation_class="mutating",
            audit_metadata={"confirmation_required": True},
        )
    ]

    interactions_result = MagicMock()
    interactions_result.scalars.return_value.all.return_value = interactions
    tool_result = MagicMock()
    tool_result.scalars.return_value.all.return_value = receipts
    policy_result = MagicMock()
    policy_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(side_effect=[interactions_result, tool_result, policy_result])

    await run_quality_gates_alerts(ctx)

    bot.send_message.assert_awaited_once()
    text = bot.send_message.call_args.kwargs["text"]
    assert "Readiness checks failing:" in text
    assert "workflow_live_runtime_disabled" in text


@pytest.mark.asyncio
async def test_quality_gates_alerts_reports_security_failures_when_quality_passes() -> None:
    bot = AsyncMock()
    session = AsyncMock()
    settings = _make_settings()
    settings.quality_gates_security_max_instruction_risk_decisions = 0
    ctx = {
        "settings": settings,
        "bot": bot,
        "session_factory": _make_session_factory(session),
    }

    interactions = [
        SimpleNamespace(
            created_at=datetime.now(UTC),
            trace_id="trace-1",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 1.0,
                "final_response_quality": 1.0,
            },
            channel_metrics={"render_passed": True},
        ),
        SimpleNamespace(
            created_at=datetime.now(UTC),
            trace_id="trace-2",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 1.0,
                "final_response_quality": 1.0,
            },
            channel_metrics={"render_passed": True},
        ),
    ]
    receipts = [
        SimpleNamespace(
            created_at=datetime.now(UTC),
            status="executed",
            mutation_class="mutating",
            idempotency_key="idem-1",
            audit_metadata={"confirmation_required": True},
        )
    ]
    decisions = [
        SimpleNamespace(
            created_at=datetime.now(UTC),
            policy_name="instruction_like_content",
            decision="degraded",
        )
    ]

    interactions_result = MagicMock()
    interactions_result.scalars.return_value.all.return_value = interactions
    tool_result = MagicMock()
    tool_result.scalars.return_value.all.return_value = receipts
    policy_result = MagicMock()
    policy_result.scalars.return_value.all.return_value = decisions
    session.execute = AsyncMock(side_effect=[interactions_result, tool_result, policy_result])

    await run_quality_gates_alerts(ctx)

    bot.send_message.assert_awaited_once()
    text = bot.send_message.call_args.kwargs["text"]
    assert "Security checks failing:" in text
    assert "instruction_risk_decisions=1>0" in text


@pytest.mark.asyncio
async def test_quality_gates_alerts_reports_assistant_native_replay_failures() -> None:
    bot = AsyncMock()
    session = AsyncMock()
    ctx = {
        "settings": _make_settings(),
        "bot": bot,
        "session_factory": _make_session_factory(session),
    }

    interactions = [
        SimpleNamespace(
            created_at=datetime.now(UTC),
            trace_id="trace-1",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 1.0,
                "final_response_quality": 1.0,
            },
            channel_metrics={"render_passed": True},
        ),
        SimpleNamespace(
            created_at=datetime.now(UTC),
            trace_id="trace-2",
            quality_scores={
                "route_quality": 1.0,
                "channel_style": 1.0,
                "final_response_quality": 1.0,
            },
            channel_metrics={"render_passed": True},
        ),
    ]
    receipts = [
        SimpleNamespace(
            created_at=datetime.now(UTC),
            status="executed",
            mutation_class="mutating",
            audit_metadata={"confirmation_required": True},
        )
    ]

    interactions_result = MagicMock()
    interactions_result.scalars.return_value.all.return_value = interactions
    tool_result = MagicMock()
    tool_result.scalars.return_value.all.return_value = receipts
    policy_result = MagicMock()
    policy_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(side_effect=[interactions_result, tool_result, policy_result])

    with (
        pytest.MonkeyPatch.context() as mp,
    ):
        mp.setattr(
            "src.app.workers.quality_gates_alerts.validate_assistant_native_eval_assets",
            list,
        )
        mp.setattr(
            "src.app.workers.quality_gates_alerts.evaluate_assistant_native_replays",
            lambda: SimpleNamespace(
                pass_rate=0.5,
                baseline_lift=0.1,
                pass_count=3,
                case_count=6,
            ),
        )
        await run_quality_gates_alerts(ctx)

    bot.send_message.assert_awaited_once()
    text = bot.send_message.call_args.kwargs["text"]
    assert "Assistant-native replays:" in text
    assert "assistant_native_replay_pass_rate=0.50<1.00" in text
