"""Tests for SLO computation + alert worker + API route (P3.6)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.app.core.slo import (
    DEFAULT_BURN_RATE_ALERT,
    SLOReport,
    SLOValue,
    burn_rate,
    compute_cost_slo,
    compute_error_slo,
    compute_goodput_slo,
    compute_latency_slo,
    compute_quality_slo,
    percentile,
)
from src.app.workers import slo_alerts
from src.app.workers.slo_alerts import format_alert_message, run_slo_alerts

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides) -> SimpleNamespace:
    base = {
        "slo_latency_p95_seconds": 5.0,
        "slo_latency_p99_seconds": 12.0,
        "slo_error_rate_max": 0.005,
        "slo_quality_p10_min": 4.0,
        "slo_goodput_target": 0.99,
        "slo_alert_burn_rate_threshold": 2.0,
        "slo_alerts_enabled": True,
        "cost_daily_ceiling_gbp": 5.0,
        "allowed_user_ids": [12345],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _session_factory() -> object:
    session = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield session

    return factory


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------


def test_percentile_linear_interpolation() -> None:
    # p95 of [1..10] = 9.55 (same math as the cost-alerts p95).
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == pytest.approx(9.55)


def test_percentile_empty_returns_zero() -> None:
    assert percentile([], 0.5) == 0.0


def test_percentile_p10() -> None:
    # p10 of [1..10] = 1.9 (rank 0.9 → between idx 0 and 1).
    assert percentile(list(range(1, 11)), 0.1) == pytest.approx(1.9)


def test_burn_rate_zero_when_no_bad() -> None:
    assert burn_rate(bad_fraction=0.0, target=0.99) == 0.0


def test_burn_rate_double() -> None:
    # 2% bad against a 1% budget = 2.0 burn
    assert burn_rate(bad_fraction=0.02, target=0.99) == pytest.approx(2.0)


def test_burn_rate_infinite_when_budget_zero() -> None:
    assert burn_rate(bad_fraction=0.1, target=1.0) == float("inf")


# ---------------------------------------------------------------------------
# Per-SLO computation
# ---------------------------------------------------------------------------


def test_latency_slo_passes_when_p95_under_target() -> None:
    # All 100 samples at 2s — well under 5s target.
    latencies = [2000] * 100
    slo = compute_latency_slo(
        latencies_ms=latencies,
        p95_seconds_target=5.0,
        p99_seconds_target=12.0,
        goodput_target=0.99,
    )
    assert slo.meets_target is True
    assert slo.burn_rate == 0.0
    assert slo.details["p95_seconds"] == 2.0


def test_latency_slo_fails_when_p95_over_target() -> None:
    # 10 of 100 samples over 5s → p95 exceeds target, 10% bad fraction
    # against a 1% budget = burn_rate 10.
    latencies = [2000] * 90 + [7000] * 10
    slo = compute_latency_slo(
        latencies_ms=latencies,
        p95_seconds_target=5.0,
        p99_seconds_target=12.0,
        goodput_target=0.99,
    )
    assert slo.meets_target is False
    assert slo.burn_rate == pytest.approx(10.0)
    assert slo.sample_size == 100


def test_latency_slo_empty_returns_pass() -> None:
    slo = compute_latency_slo(
        latencies_ms=[],
        p95_seconds_target=5.0,
        p99_seconds_target=12.0,
        goodput_target=0.99,
    )
    assert slo.meets_target is True
    assert slo.sample_size == 0


def test_error_slo_passes_under_budget() -> None:
    slo = compute_error_slo(total=1000, errors=2, max_error_rate=0.005)
    assert slo.meets_target is True
    assert slo.burn_rate < DEFAULT_BURN_RATE_ALERT


def test_error_slo_fails_over_budget() -> None:
    # 20 errors / 1000 = 2% error rate → vs availability 0.995 target,
    # budget = 0.005, burn = 0.02/0.005 = 4.0
    slo = compute_error_slo(total=1000, errors=20, max_error_rate=0.005)
    assert slo.meets_target is False
    assert slo.burn_rate == pytest.approx(4.0)


def test_error_slo_no_requests_is_pass() -> None:
    slo = compute_error_slo(total=0, errors=0, max_error_rate=0.005)
    assert slo.meets_target is True
    assert slo.sample_size == 0


def test_quality_slo_passes_when_p10_above_threshold() -> None:
    rows = [
        {
            "specialist": "diary",
            "score_relevance": 5,
            "score_actionability": 5,
            "score_tone": 5,
            "score_conciseness": 5,
        }
        for _ in range(10)
    ]
    slo = compute_quality_slo(rows=rows, p10_min=4.0, goodput_target=0.99)
    assert slo.meets_target is True
    assert slo.details["breaches"] == []


def test_quality_slo_fails_when_one_agent_dimension_low() -> None:
    rows = [
        {
            "specialist": "diary",
            "score_relevance": 5,
            "score_actionability": 5,
            "score_tone": 5,
            "score_conciseness": 5,
        }
        for _ in range(10)
    ]
    # Push "tone" low for memory agent — p10 of [2,2,2,5,5,5] is 2.0
    rows.extend(
        [
            {
                "specialist": "memory",
                "score_relevance": 5,
                "score_actionability": 5,
                "score_tone": 2,
                "score_conciseness": 5,
            }
            for _ in range(3)
        ]
        + [
            {
                "specialist": "memory",
                "score_relevance": 5,
                "score_actionability": 5,
                "score_tone": 5,
                "score_conciseness": 5,
            }
            for _ in range(3)
        ]
    )
    slo = compute_quality_slo(rows=rows, p10_min=4.0, goodput_target=0.99)
    assert slo.meets_target is False
    breaches = slo.details["breaches"]
    assert any(b["specialist"] == "memory" and b["dimension"] == "score_tone" for b in breaches)


def test_quality_slo_skips_agents_with_few_samples() -> None:
    rows = [
        {
            "specialist": "tools",
            "score_relevance": 2,
            "score_actionability": 2,
            "score_tone": 2,
            "score_conciseness": 2,
        }
        for _ in range(2)  # < 3 samples, should be ignored
    ]
    slo = compute_quality_slo(rows=rows, p10_min=4.0, goodput_target=0.99)
    # Even though scores are low, too few samples to trust p10.
    assert slo.meets_target is True


def test_goodput_slo_passes_when_good_fraction_over_target() -> None:
    slo = compute_goodput_slo(total=1000, good=995, target=0.99)
    assert slo.meets_target is True
    assert slo.current == pytest.approx(0.995)
    assert slo.burn_rate < DEFAULT_BURN_RATE_ALERT


def test_goodput_slo_fails_when_good_fraction_under_target() -> None:
    # 97% good vs 99% target → 3% bad / 1% budget = 3.0 burn
    slo = compute_goodput_slo(total=1000, good=970, target=0.99)
    assert slo.meets_target is False
    assert slo.burn_rate == pytest.approx(3.0)


def test_cost_slo_within_ceiling_pass() -> None:
    slo = compute_cost_slo(spend_gbp=3.0, ceiling_gbp=5.0)
    assert slo.meets_target is True
    assert slo.burn_rate == 0.0


def test_cost_slo_over_ceiling_fails() -> None:
    slo = compute_cost_slo(spend_gbp=7.5, ceiling_gbp=5.0)
    assert slo.meets_target is False
    assert slo.burn_rate == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# Collect report — validates wiring via monkeypatching the DB helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_slo_report_builds_five_slos(monkeypatch) -> None:
    from src.app.core import slo as slo_module

    async def _latencies(session, *, start, end, span_kinds=...):
        return [1000, 2000, 3000, 4000, 4500]

    async def _statuses(session, *, start, end, span_kinds=...):
        return (1000, 2)

    async def _quality(session, *, start, end):
        return [
            {
                "specialist": "diary",
                "score_relevance": 5,
                "score_actionability": 5,
                "score_tone": 5,
                "score_conciseness": 5,
            }
            for _ in range(5)
        ]

    async def _goodput(session, *, start, end, latency_threshold_ms, quality_threshold):
        return (100, 99)

    async def _cost(session, *, start_utc, end_utc):
        return 3.5

    monkeypatch.setattr(slo_module, "fetch_request_latencies_ms", _latencies)
    monkeypatch.setattr(slo_module, "fetch_request_statuses", _statuses)
    monkeypatch.setattr(slo_module, "fetch_quality_dimensions", _quality)
    monkeypatch.setattr(slo_module, "fetch_goodput_rows", _goodput)
    monkeypatch.setattr(slo_module, "fetch_daily_cost_gbp", _cost)

    session = AsyncMock()
    settings = _settings()

    report = await slo_module.collect_slo_report(session, settings)

    assert isinstance(report, SLOReport)
    names = [slo.name for slo in report.slos]
    assert names == ["latency", "error", "quality", "goodput", "cost"]
    # All should pass under the stubbed numbers.
    assert all(s.meets_target for s in report.slos)


# ---------------------------------------------------------------------------
# Alert worker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slo_alerts_skips_without_bot() -> None:
    ctx = {
        "settings": _settings(),
        "bot": None,
        "session_factory": _session_factory(),
    }
    await run_slo_alerts(ctx)  # silent no-op


@pytest.mark.asyncio
async def test_slo_alerts_no_fire_when_all_healthy(monkeypatch) -> None:
    bot = AsyncMock()

    healthy_report = SLOReport(
        window_hours=24,
        generated_at=datetime.now(UTC),
        slos=[
            SLOValue(
                name="latency",
                current=1.5,
                target=5.0,
                unit="seconds",
                meets_target=True,
                burn_rate=0.0,
                sample_size=100,
            ),
            SLOValue(
                name="error",
                current=0.001,
                target=0.005,
                unit="ratio",
                meets_target=True,
                burn_rate=0.2,
                sample_size=100,
            ),
        ],
    )

    async def _stub(*args, **kwargs):
        return healthy_report

    monkeypatch.setattr(slo_alerts, "collect_slo_report", _stub)

    ctx = {
        "settings": _settings(),
        "bot": bot,
        "session_factory": _session_factory(),
    }
    await run_slo_alerts(ctx)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_slo_alerts_fires_on_burn_rate_breach(monkeypatch) -> None:
    bot = AsyncMock()

    breaching_report = SLOReport(
        window_hours=24,
        generated_at=datetime.now(UTC),
        slos=[
            SLOValue(
                name="latency",
                current=6.2,
                target=5.0,
                unit="seconds",
                meets_target=False,
                burn_rate=3.5,
                sample_size=500,
            ),
            SLOValue(
                name="error",
                current=0.001,
                target=0.005,
                unit="ratio",
                meets_target=True,
                burn_rate=0.2,
                sample_size=500,
            ),
        ],
    )

    async def _stub(*args, **kwargs):
        return breaching_report

    monkeypatch.setattr(slo_alerts, "collect_slo_report", _stub)

    ctx = {
        "settings": _settings(),
        "bot": bot,
        "session_factory": _session_factory(),
    }
    await run_slo_alerts(ctx)

    bot.send_message.assert_awaited_once()
    args, kwargs = bot.send_message.call_args
    text = kwargs.get("text") or (args[1] if len(args) > 1 else "")
    assert "SLO Burn-Rate Alert" in text
    assert "latency" in text
    assert "burn_rate=3.50x" in text
    # Healthy SLO must NOT be in the alert
    assert "error:" not in text.split("\nInvestigate")[0]


def test_format_alert_message_includes_breach_counts() -> None:
    report = SLOReport(
        window_hours=24,
        generated_at=datetime(2026, 4, 18, 9, 15, tzinfo=UTC),
        slos=[
            SLOValue(
                name="cost",
                current=7.5,
                target=5.0,
                unit="gbp",
                meets_target=False,
                burn_rate=1.5,
                sample_size=1,
            ),
        ],
    )
    breaches = report.breaches(threshold=1.0)
    msg = format_alert_message(report, breaches)
    assert "1 SLO(s)" in msg
    assert "cost" in msg
    assert "7.5" in msg


# ---------------------------------------------------------------------------
# API route — returns correct shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slo_route_returns_expected_shape(monkeypatch) -> None:
    """Call the route handler directly with a stubbed collector."""
    from src.app.api.routes import monitoring as monitoring_route

    sample_report = SLOReport(
        window_hours=24,
        generated_at=datetime(2026, 4, 18, 9, 0, tzinfo=UTC),
        slos=[
            SLOValue(
                name="latency",
                current=3.2,
                target=5.0,
                unit="seconds",
                meets_target=True,
                burn_rate=0.0,
                sample_size=42,
                details={"p95_seconds": 3.2, "p99_seconds": 4.9},
            ),
        ],
    )

    async def _stub(session, settings, *, window_hours=24):
        return sample_report

    monkeypatch.setattr(monitoring_route, "collect_slo_report", _stub)

    response = await monitoring_route.slo_report(session=AsyncMock(), window_hours=24)

    payload = response.model_dump()
    assert payload["window_hours"] == 24
    assert payload["generated_at"] == "2026-04-18T09:00:00+00:00"
    assert len(payload["slos"]) == 1
    slo = payload["slos"][0]
    assert slo["name"] == "latency"
    assert slo["current"] == 3.2
    assert slo["target"] == 5.0
    assert slo["unit"] == "seconds"
    assert slo["meets_target"] is True
    assert slo["burn_rate"] == 0.0
    assert slo["sample_size"] == 42
    assert slo["details"]["p95_seconds"] == 3.2
