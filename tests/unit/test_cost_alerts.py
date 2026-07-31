"""Tests for cost-ceiling Telegram alert worker."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.app.workers import cost_alerts
from src.app.workers.cost_alerts import (
    _format_ceiling_alert,
    _format_eval_ceiling_alert,
    _format_rolling_alert,
    _fraction_of_day_elapsed,
    _p95,
    run_cost_alerts,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides) -> SimpleNamespace:
    redis_url = MagicMock()
    redis_url.get_secret_value.return_value = ""  # disable Redis dedup in tests
    base = {
        "cost_alerts_enabled": True,
        "cost_daily_ceiling_gbp": 5.0,
        "cost_rolling_multiplier": 1.5,
        "eval_daily_ceiling_gbp": 1.0,
        "user_timezone": "Europe/London",
        "allowed_user_ids": [12345],
        "redis_url": redis_url,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_session_factory() -> object:
    session = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield session

    return factory


def _synthetic_cost_map(
    *,
    today: date,
    today_gbp: float,
    baseline_gbp: list[float],
) -> dict[date, float]:
    """Build a local-day → GBP mapping for the fake fetcher."""
    mapping: dict[date, float] = {today: today_gbp}
    for idx, value in enumerate(baseline_gbp, start=1):
        mapping[today - timedelta(days=idx)] = value
    return mapping


def _patch_fetch(
    monkeypatch,
    gbp_by_day: dict[date, float],
    *,
    eval_gbp_by_day: dict[date, float] | None = None,
) -> None:
    """Stub the two cost fetchers — converts GBP maps back into USD.

    ``gbp_by_day`` is the total spend map used by ``_fetch_daily_costs_usd``.
    ``eval_gbp_by_day`` (optional, defaults to empty) is used by
    ``_fetch_eval_costs_usd`` for the P4.10 eval-cost split.
    """

    async def fake_total(session_factory, *, tz, start, end):
        # Return USD values; the worker converts using the price table rate.
        # With USD_PER_GBP = 0.79, GBP = USD * 0.79 → USD = GBP / 0.79.
        return {day: total / 0.79 for day, total in gbp_by_day.items()}

    eval_map = eval_gbp_by_day or {}

    async def fake_eval(session_factory, *, tz, start, end, eval_agent_names=None):
        return {day: total / 0.79 for day, total in eval_map.items()}

    monkeypatch.setattr(cost_alerts, "_fetch_daily_costs_usd", fake_total)
    monkeypatch.setattr(cost_alerts, "_fetch_eval_costs_usd", fake_eval)


def _patch_price_table(monkeypatch, *, rate: float = 0.79) -> None:
    monkeypatch.setattr(
        cost_alerts,
        "_latest_price_table",
        lambda: {
            "version": "2026-04-18",
            "currency_usd_per_gbp": rate,
            "models": {},
            "cache_multipliers": {"write_5m": 1.25, "write_1h": 2.0, "read": 0.1},
        },
    )


def _fixed_now(monkeypatch, *, hour_local: int, minute_local: int = 0) -> datetime:
    """Freeze ``datetime.now(UTC)`` so tests control time-of-day projections."""
    tz = ZoneInfo("Europe/London")
    local_today = datetime.now(tz).date()
    local_dt = datetime.combine(local_today, time(hour_local, minute_local), tzinfo=tz)
    fixed_utc = local_dt.astimezone(UTC)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz_arg=None):
            return fixed_utc.astimezone(tz_arg) if tz_arg else fixed_utc.replace(tzinfo=None)

    monkeypatch.setattr(cost_alerts, "datetime", _FrozenDatetime)
    return fixed_utc


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


def test_p95_of_short_sample_is_linear_interpolated() -> None:
    # p95 of [1..10] is 9.55 (rank = 0.95 * 9 = 8.55 → between idx 8 (9) and 9 (10)).
    assert _p95([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == pytest.approx(9.55)


def test_p95_empty_returns_zero() -> None:
    assert _p95([]) == 0.0


def test_p95_single_value() -> None:
    assert _p95([4.2]) == 4.2


def test_fraction_of_day_elapsed_at_noon() -> None:
    tz = ZoneInfo("Europe/London")
    noon = datetime.combine(date(2026, 4, 18), time(12, 0), tzinfo=tz)
    assert _fraction_of_day_elapsed(noon) == pytest.approx(0.5, abs=0.001)


def test_fraction_of_day_elapsed_clamped_near_midnight() -> None:
    tz = ZoneInfo("Europe/London")
    five_past = datetime.combine(date(2026, 4, 18), time(0, 5), tzinfo=tz)
    # Floored at 1/24 so projection doesn't explode.
    assert _fraction_of_day_elapsed(five_past) == pytest.approx(1.0 / 24.0)


def test_format_rolling_alert_mentions_pound_and_projection() -> None:
    msg = _format_rolling_alert(
        today_gbp=3.10,
        projected_gbp=6.20,
        p95_gbp=3.00,
        multiplier=1.5,
        fraction_elapsed=0.5,
    )
    assert "Cost alert" in msg
    assert "\u00a33.10" in msg
    assert "\u00a36.20" in msg
    assert "\u00a33.00" in msg
    assert "\u00a34.50" in msg  # 1.5x budget
    assert "Check recent traffic" in msg


def test_format_ceiling_alert_mentions_ceiling() -> None:
    msg = _format_ceiling_alert(today_gbp=7.50, ceiling_gbp=5.0)
    assert "ceiling breached" in msg
    assert "\u00a37.50" in msg
    assert "\u00a35.00" in msg


# ---------------------------------------------------------------------------
# Worker-level tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cost_alerts_skips_without_bot() -> None:
    ctx = {
        "settings": _make_settings(),
        "bot": None,
        "session_factory": _make_session_factory(),
    }
    # No bot → silent no-op.
    await run_cost_alerts(ctx)


@pytest.mark.asyncio
async def test_run_cost_alerts_skips_when_disabled() -> None:
    bot = AsyncMock()
    ctx = {
        "settings": _make_settings(cost_alerts_enabled=False),
        "bot": bot,
        "session_factory": _make_session_factory(),
    }
    await run_cost_alerts(ctx)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_cost_alerts_skips_without_price_table(monkeypatch) -> None:
    bot = AsyncMock()

    def _boom() -> dict:
        raise FileNotFoundError("no price tables")

    monkeypatch.setattr(cost_alerts, "_latest_price_table", _boom)
    ctx = {
        "settings": _make_settings(),
        "bot": bot,
        "session_factory": _make_session_factory(),
    }
    await run_cost_alerts(ctx)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_cost_alerts_skips_when_no_data(monkeypatch) -> None:
    bot = AsyncMock()
    _patch_price_table(monkeypatch)
    _patch_fetch(monkeypatch, {})
    ctx = {
        "settings": _make_settings(),
        "bot": bot,
        "session_factory": _make_session_factory(),
    }
    await run_cost_alerts(ctx)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_rolling_alert_fires_when_projected_exceeds_budget(monkeypatch) -> None:
    bot = AsyncMock()
    _patch_price_table(monkeypatch)
    _fixed_now(monkeypatch, hour_local=12)  # 50% through the day

    today = datetime.now(ZoneInfo("Europe/London")).date()
    # 30 days of ~£1/day baseline; today so far £1.20 at noon → projects to £2.40.
    # p95 ≈ £1.00, 1.5x = £1.50. £2.40 > £1.50 → should fire.
    baseline = [1.0] * 30
    gbp_by_day = _synthetic_cost_map(today=today, today_gbp=1.20, baseline_gbp=baseline)
    _patch_fetch(monkeypatch, gbp_by_day)

    ctx = {
        "settings": _make_settings(),
        "bot": bot,
        "session_factory": _make_session_factory(),
    }
    await run_cost_alerts(ctx)
    assert bot.send_message.await_count == 1
    sent = bot.send_message.await_args.kwargs["text"]
    assert "projected end-of-day spend over rolling p95" in sent
    assert "\u00a31.20" in sent


@pytest.mark.asyncio
async def test_rolling_alert_silent_within_budget(monkeypatch) -> None:
    bot = AsyncMock()
    _patch_price_table(monkeypatch)
    _fixed_now(monkeypatch, hour_local=12)

    today = datetime.now(ZoneInfo("Europe/London")).date()
    # Today tracks at ~baseline rate (£0.50 at noon → £1.00 projected == p95). Silent.
    baseline = [1.0] * 30
    gbp_by_day = _synthetic_cost_map(today=today, today_gbp=0.50, baseline_gbp=baseline)
    _patch_fetch(monkeypatch, gbp_by_day)

    ctx = {
        "settings": _make_settings(),
        "bot": bot,
        "session_factory": _make_session_factory(),
    }
    await run_cost_alerts(ctx)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_ceiling_alert_fires_even_without_baseline(monkeypatch) -> None:
    bot = AsyncMock()
    _patch_price_table(monkeypatch)
    _fixed_now(monkeypatch, hour_local=15)

    today = datetime.now(ZoneInfo("Europe/London")).date()
    # No baseline days — only today, but today has already blown the ceiling.
    gbp_by_day = {today: 7.50}
    _patch_fetch(monkeypatch, gbp_by_day)

    ctx = {
        "settings": _make_settings(cost_daily_ceiling_gbp=5.0),
        "bot": bot,
        "session_factory": _make_session_factory(),
    }
    await run_cost_alerts(ctx)
    assert bot.send_message.await_count == 1
    sent = bot.send_message.await_args.kwargs["text"]
    assert "ceiling breached" in sent
    assert "\u00a37.50" in sent


@pytest.mark.asyncio
async def test_both_alerts_can_fire_in_same_run(monkeypatch) -> None:
    bot = AsyncMock()
    _patch_price_table(monkeypatch)
    _fixed_now(monkeypatch, hour_local=12)

    today = datetime.now(ZoneInfo("Europe/London")).date()
    # Today £6.00 at noon → projects £12.00. p95 baseline £1.00 → both fire.
    baseline = [1.0] * 30
    gbp_by_day = _synthetic_cost_map(today=today, today_gbp=6.00, baseline_gbp=baseline)
    _patch_fetch(monkeypatch, gbp_by_day)

    ctx = {
        "settings": _make_settings(cost_daily_ceiling_gbp=5.0),
        "bot": bot,
        "session_factory": _make_session_factory(),
    }
    await run_cost_alerts(ctx)
    assert bot.send_message.await_count == 2
    texts = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert any("ceiling breached" in t for t in texts)
    assert any("rolling p95" in t for t in texts)


@pytest.mark.asyncio
async def test_no_user_ids_skips(monkeypatch) -> None:
    bot = AsyncMock()
    _patch_price_table(monkeypatch)
    ctx = {
        "settings": _make_settings(allowed_user_ids=[]),
        "bot": bot,
        "session_factory": _make_session_factory(),
    }
    await run_cost_alerts(ctx)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_rolling_alert_skipped_with_thin_baseline(monkeypatch) -> None:
    """Fewer than MIN_BASELINE_DAYS of history → no rolling alert (ceiling still works)."""
    bot = AsyncMock()
    _patch_price_table(monkeypatch)
    _fixed_now(monkeypatch, hour_local=12)

    today = datetime.now(ZoneInfo("Europe/London")).date()
    # Only 3 baseline days, huge spend today, but below ceiling → silent.
    baseline = [0.10, 0.12, 0.09]
    gbp_by_day = _synthetic_cost_map(today=today, today_gbp=2.00, baseline_gbp=baseline)
    _patch_fetch(monkeypatch, gbp_by_day)

    ctx = {
        "settings": _make_settings(cost_daily_ceiling_gbp=5.0),
        "bot": bot,
        "session_factory": _make_session_factory(),
    }
    await run_cost_alerts(ctx)
    bot.send_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# P4.10 — eval-purpose cost split tests
# ---------------------------------------------------------------------------


def test_format_eval_ceiling_alert_includes_eval_and_total() -> None:
    msg = _format_eval_ceiling_alert(
        today_eval_gbp=1.50,
        eval_ceiling_gbp=1.00,
        today_total_gbp=3.00,
    )
    assert "eval" in msg.lower()
    assert "\u00a31.50" in msg  # today eval spend
    assert "\u00a31.00" in msg  # ceiling
    assert "\u00a33.00" in msg  # total
    # Eval share: 1.5 / 3.0 = 50%.
    assert "50%" in msg
    # Copy must steer the reader toward A/B / auto-judge.
    assert "A/B" in msg or "auto-judge" in msg


@pytest.mark.asyncio
async def test_eval_ceiling_fires_independently_of_total_ceiling(monkeypatch) -> None:
    """Eval spend £1.50 > eval ceiling £1.00 while total £2.00 stays under £5.00.

    Expectation: exactly one alert (eval_ceiling), no regular ceiling alert,
    no rolling alert (no baseline).
    """
    bot = AsyncMock()
    _patch_price_table(monkeypatch)
    _fixed_now(monkeypatch, hour_local=15)

    today = datetime.now(ZoneInfo("Europe/London")).date()
    total_gbp_by_day = {today: 2.00}
    eval_gbp_by_day = {today: 1.50}
    _patch_fetch(monkeypatch, total_gbp_by_day, eval_gbp_by_day=eval_gbp_by_day)

    ctx = {
        "settings": _make_settings(
            cost_daily_ceiling_gbp=5.0,
            eval_daily_ceiling_gbp=1.0,
        ),
        "bot": bot,
        "session_factory": _make_session_factory(),
    }
    await run_cost_alerts(ctx)
    assert bot.send_message.await_count == 1
    sent = bot.send_message.await_args.kwargs["text"]
    assert "evaluation-purpose ceiling breached" in sent
    assert "\u00a31.50" in sent


@pytest.mark.asyncio
async def test_eval_and_regular_ceilings_can_both_fire(monkeypatch) -> None:
    """Today spends £6.00 total of which £2.00 is eval. Both ceilings breached.

    Expectation: two alerts — the absolute ceiling plus the eval ceiling.
    The rolling alert is silent (no baseline).
    """
    bot = AsyncMock()
    _patch_price_table(monkeypatch)
    _fixed_now(monkeypatch, hour_local=15)

    today = datetime.now(ZoneInfo("Europe/London")).date()
    total_gbp_by_day = {today: 6.00}
    eval_gbp_by_day = {today: 2.00}
    _patch_fetch(monkeypatch, total_gbp_by_day, eval_gbp_by_day=eval_gbp_by_day)

    ctx = {
        "settings": _make_settings(
            cost_daily_ceiling_gbp=5.0,
            eval_daily_ceiling_gbp=1.0,
        ),
        "bot": bot,
        "session_factory": _make_session_factory(),
    }
    await run_cost_alerts(ctx)
    assert bot.send_message.await_count == 2
    texts = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert any("ceiling breached" in t for t in texts)
    assert any("evaluation-purpose ceiling breached" in t for t in texts)
