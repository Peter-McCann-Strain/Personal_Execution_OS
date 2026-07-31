"""Cost-ceiling Telegram alerts — catch silent spend escalations early.

Runs hourly (ARQ cron at :25, avoiding collision with other alert jobs).

Three alert categories, deduped per-day:

* ``rolling`` — projected end-of-day spend > ``cost_rolling_multiplier`` x
  the 30-day rolling p95 of daily cost. Catches "today is 1.5x worse than
  a bad day in the last month" before the damage compounds.
* ``ceiling`` — *actual* cumulative daily spend exceeds the hard
  ``cost_daily_ceiling_gbp`` ceiling. No projection, no mercy — this is
  the absolute upper bound and should fire before you blow a monthly
  budget in a single afternoon.
* ``eval_ceiling`` (P4.10) — eval-purpose spend (auto-judge, A/B test,
  jury ensemble, quick_eval) exceeds ``eval_daily_ceiling_gbp``. Splits
  eval cost from product cost so an A/B run overnight doesn't mask a
  regression in product spend (or vice versa). Eval rows are identified
  by ``agent_name`` matching ``_EVAL_AGENT_NAMES``.

Designed after the March-2026 Anthropic cache-TTL flip (1h → 5m default)
that quietly multiplied spend at another org by ~3x overnight. Cost data
comes from the ``agent_actions`` table which already logs ``cost_usd``
per LLM call; GBP is derived via the same price-table ``currency_usd_per_gbp``
factor the live cost calculator uses.

Defensive contract:

* Missing / empty price table → log + skip (cost attribution is broken;
  firing random-looking alerts would be worse than silence).
* No cost rows in the last 30 days → log + skip (not enough signal).
* Telegram bot not configured → log + skip.
* Dedup via Redis ``SET NX`` on key ``cost_alert:<YYYY-MM-DD>:<category>``
  with a 1h TTL so we never spam more than one alert per hour per
  category per day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from aiogram import Bot
from sqlalchemy import select

from src.app.config import Settings
from src.app.core.llm_pricing import (
    _latest_price_table,
)
from src.app.core.redis import get_redis_client
from src.app.persistence.models import AgentAction
from src.app.workers.github_filer import AlertRecord, file_github_issue

logger = structlog.get_logger()

# Dedup keys / TTL — one alert per category per day, with hourly re-eligibility
# so a sustained breach keeps firing once per hour rather than once per day.
_ALERT_TTL_SECONDS = 60 * 60  # 1 hour
_ALERT_CATEGORIES = ("rolling", "ceiling", "eval_ceiling")

# Minimum days of historical data before we trust the p95 baseline.
# Fewer than this and we skip the rolling alert (still honour the ceiling).
_MIN_BASELINE_DAYS = 7

# Known eval-purpose ``agent_name`` values. Every cost row with one of these
# names contributes to the eval-spend bucket used by ``eval_ceiling`` (P4.10).
# Keep this list aligned with ``ctxvars.bind_contextvars(purpose="evaluation")``
# call sites: ``src/app/core/auto_judge.py`` and
# ``src/app/core/judge_ensemble.py``. When a new eval component lands, add
# its agent_name here so its spend is attributed correctly.
_EVAL_AGENT_NAMES = frozenset(
    {
        "auto_judge",
        "judge_ensemble",
        "ab_test",
        "quick_eval",
    }
)


@dataclass(frozen=True)
class DailyCost:
    """One day's aggregated spend in GBP (derived from USD totals)."""

    day: date
    cost_gbp: float


def _resolve_timezone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning("cost_alerts_bad_timezone", tz_name=tz_name)
        return ZoneInfo("UTC")


def _fraction_of_day_elapsed(now_local: datetime) -> float:
    """Return how far through the local day we are, as a fraction in (0, 1].

    Clamped to a minimum of 1/24 (one hour's worth) so a 12:25 run doesn't
    project 1000x off a rounding error at midnight.
    """
    midnight = datetime.combine(now_local.date(), time(0, 0), tzinfo=now_local.tzinfo)
    elapsed_seconds = (now_local - midnight).total_seconds()
    fraction = elapsed_seconds / 86400.0
    return max(fraction, 1.0 / 24.0)


def _p95(values: list[float]) -> float:
    """Simple linear-interpolation p95 for a small sample (<= 31 points).

    We avoid pulling in numpy for a 30-element list. Values must already be
    numeric (GBP floats). Returns 0.0 for an empty list so the caller can
    short-circuit the rolling check without a None dance.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = 0.95 * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


async def _fetch_daily_costs_usd(
    session_factory,
    *,
    tz: ZoneInfo,
    start: datetime,
    end: datetime,
) -> dict[date, float]:
    """Sum ``cost_usd`` per local-calendar day from ``agent_actions``.

    We bucket on the *user's* local calendar day, not UTC, so "today's
    spend" matches the user's mental model. Precision isn't load-bearing
    here (a 1-hour boundary skew is well within rolling-p95 noise).
    """
    async with session_factory() as session:
        stmt = select(
            AgentAction.created_at,
            AgentAction.cost_usd,
        ).where(
            AgentAction.created_at >= start,
            AgentAction.created_at < end,
            AgentAction.cost_usd.isnot(None),
        )
        result = await session.execute(stmt)
        rows = result.all()

    per_day: dict[date, float] = {}
    for row in rows:
        created_at = row.created_at
        cost = row.cost_usd or 0.0
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        local_day = created_at.astimezone(tz).date()
        per_day[local_day] = per_day.get(local_day, 0.0) + float(cost)
    return per_day


async def _fetch_eval_costs_usd(
    session_factory,
    *,
    tz: ZoneInfo,
    start: datetime,
    end: datetime,
    eval_agent_names: frozenset[str] = _EVAL_AGENT_NAMES,
) -> dict[date, float]:
    """Sum ``cost_usd`` per local-calendar day for eval-purpose rows only.

    "Eval-purpose" is identified by ``agent_name`` falling in the
    ``_EVAL_AGENT_NAMES`` set. That set is the authoritative mapping
    between the ``purpose="evaluation"`` structlog tag and the persisted
    cost ledger — every code path that binds that structlog context also
    writes ``agent_actions`` with one of those names.
    """
    async with session_factory() as session:
        stmt = select(
            AgentAction.created_at,
            AgentAction.cost_usd,
            AgentAction.agent_name,
        ).where(
            AgentAction.created_at >= start,
            AgentAction.created_at < end,
            AgentAction.cost_usd.isnot(None),
            AgentAction.agent_name.in_(eval_agent_names),
        )
        result = await session.execute(stmt)
        rows = result.all()

    per_day: dict[date, float] = {}
    for row in rows:
        created_at = row.created_at
        cost = row.cost_usd or 0.0
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        local_day = created_at.astimezone(tz).date()
        per_day[local_day] = per_day.get(local_day, 0.0) + float(cost)
    return per_day


def _usd_to_gbp(per_day_usd: dict[date, float], *, rate_usd_to_gbp: float) -> dict[date, float]:
    return {day: total * rate_usd_to_gbp for day, total in per_day_usd.items()}


async def _already_alerted(redis_url: str, today: date, category: str) -> bool:
    """Return True if a ``category`` alert was already sent in the last hour.

    Uses ``SET key "1" NX EX 3600`` semantics — if SET succeeds we take
    ownership of this hour's slot; if it fails the slot was already
    claimed by a previous run.
    """
    if not redis_url:
        # Without Redis we fall back to best-effort (no dedup) rather than
        # swallow the alert. Spammy > silent when price data is trending up.
        return False
    try:
        client = get_redis_client(redis_url)
        key = f"cost_alert:{today.isoformat()}:{category}"
        acquired = await client.set(name=key, value="1", nx=True, ex=_ALERT_TTL_SECONDS)
        return not bool(acquired)
    except Exception:
        logger.exception("cost_alerts_redis_dedup_failed", category=category)
        return False


def _format_rolling_alert(
    *,
    today_gbp: float,
    projected_gbp: float,
    p95_gbp: float,
    multiplier: float,
    fraction_elapsed: float,
) -> str:
    budget_threshold = p95_gbp * multiplier
    return (
        "Cost alert: projected end-of-day spend over rolling p95.\n\n"
        f"Today so far: \u00a3{today_gbp:.2f} "
        f"({fraction_elapsed * 100:.0f}% of day elapsed)\n"
        f"Projected EOD: \u00a3{projected_gbp:.2f}\n"
        f"30d p95 baseline: \u00a3{p95_gbp:.2f}\n"
        f"{multiplier:g}x budget: \u00a3{budget_threshold:.2f}\n\n"
        "Check recent traffic and model mix. If a cache-TTL change "
        "or prompt regression is in play, investigate immediately."
    )


def _format_ceiling_alert(*, today_gbp: float, ceiling_gbp: float) -> str:
    return (
        "Cost alert: daily ceiling breached.\n\n"
        f"Today so far: \u00a3{today_gbp:.2f}\n"
        f"Absolute ceiling: \u00a3{ceiling_gbp:.2f}\n\n"
        "Check recent traffic. This is a hard stop — even if the "
        "spend is legitimate, confirm it was intended."
    )


def _format_eval_ceiling_alert(
    *,
    today_eval_gbp: float,
    eval_ceiling_gbp: float,
    today_total_gbp: float,
) -> str:
    """Alert message for eval-purpose spend exceeding its own ceiling (P4.10).

    Surfaces the eval split alongside total spend so the reader can decide
    whether the breach is driven by an A/B test or by a runaway auto-judge.
    """
    share = (today_eval_gbp / today_total_gbp) if today_total_gbp > 0 else 0.0
    return (
        "Cost alert: evaluation-purpose ceiling breached.\n\n"
        f"Today eval spend: \u00a3{today_eval_gbp:.2f}\n"
        f"Eval ceiling: \u00a3{eval_ceiling_gbp:.2f}\n"
        f"Today total spend: \u00a3{today_total_gbp:.2f} "
        f"(eval share: {share * 100:.0f}%)\n\n"
        "Eval spend covers auto-judge, A/B tests, and jury ensembles. "
        "Check for an in-flight A/B run or a runaway scoring cron job."
    )


async def run_cost_alerts(ctx: dict) -> None:
    """Cron entrypoint — compute today's cost, compare to baselines, alert."""
    settings: Settings = ctx["settings"]
    bot: Bot | None = ctx.get("bot")
    session_factory = ctx.get("session_factory")

    if not bool(getattr(settings, "cost_alerts_enabled", True)):
        logger.info("cost_alerts_disabled")
        return
    if bot is None:
        logger.warning("cost_alerts_no_bot", hint="Telegram not configured")
        return
    if session_factory is None:
        logger.warning("cost_alerts_no_session_factory")
        return

    user_ids = settings.allowed_user_ids
    if not user_ids:
        logger.warning("cost_alerts_no_user_ids")
        return

    # --- Load pricing / FX factor (defensively) -----------------------------
    try:
        table = _latest_price_table()
        rate_usd_to_gbp = float(table["currency_usd_per_gbp"])
        version = table["version"]
    except (FileNotFoundError, KeyError, ValueError, TypeError):
        logger.warning("cost_alerts_no_price_table", hint="add data/prices/anthropic_*.json")
        return

    tz = _resolve_timezone(getattr(settings, "user_timezone", "Europe/London"))
    now_utc = datetime.now(UTC)
    now_local = now_utc.astimezone(tz)
    today_local = now_local.date()

    # Pull 31 days back (30-day baseline + today). Trim to local midnight so
    # day buckets have clean edges.
    window_start_local = datetime.combine(
        today_local - timedelta(days=30),
        time(0, 0),
        tzinfo=tz,
    )
    window_end_utc = now_utc
    window_start_utc = window_start_local.astimezone(UTC)

    try:
        per_day_usd = await _fetch_daily_costs_usd(
            session_factory,
            tz=tz,
            start=window_start_utc,
            end=window_end_utc,
        )
    except Exception:
        logger.exception("cost_alerts_fetch_failed")
        return

    if not per_day_usd:
        logger.info("cost_alerts_no_data", price_table_version=version)
        return

    per_day_gbp = _usd_to_gbp(per_day_usd, rate_usd_to_gbp=rate_usd_to_gbp)
    today_gbp = per_day_gbp.get(today_local, 0.0)

    # --- Eval-purpose cost split (P4.10) -----------------------------------
    # Also fetch eval-only costs so we can surface a separate ceiling breach
    # for A/B tests / auto-judge / jury runs. Skip silently on fetch error
    # rather than poisoning the overall alerts if the filter predicate
    # trips a bad SQL state.
    try:
        per_day_eval_usd = await _fetch_eval_costs_usd(
            session_factory,
            tz=tz,
            start=window_start_utc,
            end=window_end_utc,
        )
    except Exception:
        logger.exception("cost_alerts_eval_fetch_failed")
        per_day_eval_usd = {}
    per_day_eval_gbp = _usd_to_gbp(per_day_eval_usd, rate_usd_to_gbp=rate_usd_to_gbp)
    today_eval_gbp = per_day_eval_gbp.get(today_local, 0.0)

    # Baseline excludes today (partial day would understate p95).
    baseline_values = [total for day, total in per_day_gbp.items() if day != today_local]

    # --- Ceiling alert (absolute) ------------------------------------------
    ceiling_gbp = float(getattr(settings, "cost_daily_ceiling_gbp", 5.0))
    eval_ceiling_gbp = float(getattr(settings, "eval_daily_ceiling_gbp", 1.0))
    redis_url = settings.redis_url.get_secret_value() if settings.redis_url else ""

    alerts_sent = 0

    if today_gbp > ceiling_gbp and not await _already_alerted(redis_url, today_local, "ceiling"):
        message = _format_ceiling_alert(today_gbp=today_gbp, ceiling_gbp=ceiling_gbp)
        try:
            await bot.send_message(chat_id=user_ids[0], text=message)
            alerts_sent += 1
            logger.warning(
                "cost_alert_sent",
                category="ceiling",
                today_gbp=round(today_gbp, 4),
                ceiling_gbp=ceiling_gbp,
                price_table_version=version,
            )
        except Exception:
            logger.exception("cost_alert_send_failed", category="ceiling")
            raise

        # --- Secondary fan-out: GitHub issue (Phase 3.9) ------------------
        # Fingerprint on the local date so each day's ceiling breach is a
        # distinct issue (if yesterday's wasn't resolved, today opens a
        # fresh one — escalation signal).
        try:
            alert = AlertRecord(
                category="cost_ceiling",
                title=(
                    f"Cost ceiling breached on {today_local.isoformat()} "
                    f"(\u00a3{today_gbp:.2f} > \u00a3{ceiling_gbp:.2f})"
                )[:120],
                summary=(
                    f"Daily spend \u00a3{today_gbp:.2f} has crossed the "
                    f"hard ceiling of \u00a3{ceiling_gbp:.2f}. Even "
                    "legitimate spend should be confirmed — then raise "
                    "the ceiling or investigate the traffic mix."
                ),
                key_fields={"date": today_local.isoformat()},
                context={"Detail": message},
            )
            await file_github_issue(
                alert,
                settings=settings,
                session_factory=session_factory,
            )
        except Exception:
            logger.warning("cost_ceiling_github_filer_failed", exc_info=True)

    # --- Rolling-p95 alert (projected EOD) ---------------------------------
    if len(baseline_values) < _MIN_BASELINE_DAYS:
        logger.info(
            "cost_alerts_baseline_thin",
            baseline_days=len(baseline_values),
            min_required=_MIN_BASELINE_DAYS,
        )
    else:
        multiplier = float(getattr(settings, "cost_rolling_multiplier", 1.5))
        p95_gbp = _p95(baseline_values)
        fraction_elapsed = _fraction_of_day_elapsed(now_local)
        projected_gbp = today_gbp / fraction_elapsed if fraction_elapsed else today_gbp
        budget = p95_gbp * multiplier

        if (
            p95_gbp > 0
            and projected_gbp > budget
            and not await _already_alerted(redis_url, today_local, "rolling")
        ):
            message = _format_rolling_alert(
                today_gbp=today_gbp,
                projected_gbp=projected_gbp,
                p95_gbp=p95_gbp,
                multiplier=multiplier,
                fraction_elapsed=fraction_elapsed,
            )
            try:
                await bot.send_message(chat_id=user_ids[0], text=message)
                alerts_sent += 1
                logger.warning(
                    "cost_alert_sent",
                    category="rolling",
                    today_gbp=round(today_gbp, 4),
                    projected_gbp=round(projected_gbp, 4),
                    p95_gbp=round(p95_gbp, 4),
                    multiplier=multiplier,
                    price_table_version=version,
                )
            except Exception:
                logger.exception("cost_alert_send_failed", category="rolling")
                raise

            # --- Secondary fan-out: GitHub issue (Phase 3.9) --------------
            try:
                alert = AlertRecord(
                    category="cost_rolling",
                    title=(f"Projected cost > {multiplier:g}x 30d p95 ({today_local.isoformat()})")[
                        :120
                    ],
                    summary=(
                        f"Projected EOD \u00a3{projected_gbp:.2f} "
                        f"exceeds {multiplier:g}x of the 30d p95 "
                        f"(\u00a3{p95_gbp:.2f})."
                    ),
                    key_fields={"date": today_local.isoformat()},
                    context={"Detail": message},
                )
                await file_github_issue(
                    alert,
                    settings=settings,
                    session_factory=session_factory,
                )
            except Exception:
                logger.warning("cost_rolling_github_filer_failed", exc_info=True)

    # --- Eval-purpose ceiling alert (P4.10) --------------------------------
    # Fires when today's cumulative eval spend (auto-judge + A/B + jury)
    # exceeds ``eval_daily_ceiling_gbp``. Independent of the overall
    # ceiling — a runaway A/B might spend £1.50 on eval alone without
    # breaching the £5 total ceiling.
    if today_eval_gbp > eval_ceiling_gbp and not await _already_alerted(
        redis_url, today_local, "eval_ceiling"
    ):
        message = _format_eval_ceiling_alert(
            today_eval_gbp=today_eval_gbp,
            eval_ceiling_gbp=eval_ceiling_gbp,
            today_total_gbp=today_gbp,
        )
        try:
            await bot.send_message(chat_id=user_ids[0], text=message)
            alerts_sent += 1
            logger.warning(
                "cost_alert_sent",
                category="eval_ceiling",
                today_eval_gbp=round(today_eval_gbp, 4),
                today_total_gbp=round(today_gbp, 4),
                eval_ceiling_gbp=eval_ceiling_gbp,
                price_table_version=version,
            )
        except Exception:
            logger.exception("cost_alert_send_failed", category="eval_ceiling")
            raise

        # --- Secondary fan-out: GitHub issue (Phase 3.9) ------------------
        try:
            alert = AlertRecord(
                category="eval_ceiling",
                title=(
                    f"Eval cost ceiling breached on "
                    f"{today_local.isoformat()} "
                    f"(\u00a3{today_eval_gbp:.2f} > \u00a3{eval_ceiling_gbp:.2f})"
                )[:120],
                summary=(
                    f"Today's eval-purpose spend "
                    f"\u00a3{today_eval_gbp:.2f} exceeds the eval "
                    f"ceiling of \u00a3{eval_ceiling_gbp:.2f}. Check "
                    "for a runaway A/B test or jury ensemble cron."
                ),
                key_fields={"date": today_local.isoformat()},
                context={"Detail": message},
            )
            await file_github_issue(
                alert,
                settings=settings,
                session_factory=session_factory,
            )
        except Exception:
            logger.warning("eval_ceiling_github_filer_failed", exc_info=True)

    logger.info(
        "cost_alerts_done",
        alerts_sent=alerts_sent,
        today_gbp=round(today_gbp, 4),
        today_eval_gbp=round(today_eval_gbp, 4),
        baseline_days=len(baseline_values),
        price_table_version=version,
    )


# --- Thin helpers exposed for testability. The worker deliberately calls
# these via module-level names so tests can ``monkeypatch`` them without
# spinning up a real DB session.
__all__ = [
    "_EVAL_AGENT_NAMES",
    "DailyCost",
    "_fetch_daily_costs_usd",
    "_fetch_eval_costs_usd",
    "_format_ceiling_alert",
    "_format_eval_ceiling_alert",
    "_format_rolling_alert",
    "_fraction_of_day_elapsed",
    "_p95",
    "run_cost_alerts",
]
