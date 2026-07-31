"""Service-level objectives (SLOs) and burn-rate tracking.

P3.6 — Four SLOs + a combined goodput SLO, computed from the already
wired-up observability surfaces:

* ``agent_trace_spans`` — latency + error signal per request span.
* ``interaction_records`` — auto-judge quality scores per agent.
* ``agent_actions`` — USD/GBP spend per LLM call (cross-ref cost_alerts).

The module exposes:

1. :class:`SLOValue` / :class:`SLOReport` dataclasses — pure value types.
2. Pure computation functions that take SQL helpers + a window and
   return current-value / target / burn-rate tuples. No I/O coupling.
3. :func:`collect_slo_report` — the public entry point used by the
   ``/api/monitoring/slo`` route and the ``run_slo_alerts`` cron.

Burn rate math (per Google SRE workbook):
    burn_rate = actual_bad_fraction / error_budget_fraction
where ``error_budget_fraction = 1 - target``. A burn rate of 2.0 means
we're consuming the error budget twice as fast as the target permits;
sustained for 24h that's a day's worth of budget gone in 12h. The alert
fires when any SLO exceeds 2.0 over the last 24 hours.

Quality SLO deliberately uses the 10th-percentile of 7-day rolling
judge scores per dimension per agent. Averages hide tails; p10 catches
the "one in ten responses are subtly bad" pattern that destroys trust
before any headline metric moves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import Settings
from src.app.core.llm_pricing import _latest_price_table
from src.app.domain.constants import TraceSpanKind, TraceSpanStatus
from src.app.persistence.models import (
    AgentAction,
    AgentTraceSpan,
    InteractionRecord,
)

# ---------------------------------------------------------------------------
# Constants — tunable via settings but kept as module defaults for call sites
# ---------------------------------------------------------------------------

# Span kinds that represent a user-facing request (used for latency/error).
_REQUEST_SPAN_KINDS: tuple[str, ...] = (TraceSpanKind.REQUEST,)

# Burn-rate threshold above which the cron alert fires.
DEFAULT_BURN_RATE_ALERT: float = 2.0

# Dimensions an auto-judge scores per interaction. Quality SLO requires
# p10 over each dimension, per agent, to be >= threshold.
_QUALITY_DIMENSIONS: tuple[str, ...] = (
    "score_relevance",
    "score_actionability",
    "score_tone",
    "score_conciseness",
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SLOValue:
    """One SLO's current state."""

    name: str
    current: float
    target: float
    unit: str  # e.g. "seconds", "ratio", "score", "gbp"
    meets_target: bool
    burn_rate: float  # 0 when not applicable
    sample_size: int
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "current": self.current,
            "target": self.target,
            "unit": self.unit,
            "meets_target": self.meets_target,
            "burn_rate": self.burn_rate,
            "sample_size": self.sample_size,
            "details": self.details,
        }


@dataclass(frozen=True)
class SLOReport:
    """Snapshot of all SLOs at a given window."""

    window_hours: int
    generated_at: datetime
    slos: list[SLOValue]

    def breaches(self, threshold: float = DEFAULT_BURN_RATE_ALERT) -> list[SLOValue]:
        return [slo for slo in self.slos if slo.burn_rate >= threshold]

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_hours": self.window_hours,
            "generated_at": self.generated_at.isoformat(),
            "slos": [slo.as_dict() for slo in self.slos],
        }


# ---------------------------------------------------------------------------
# Pure-ish math helpers
# ---------------------------------------------------------------------------


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile; empty list → 0.0."""
    if not values:
        return 0.0
    if pct <= 0:
        return float(values[0])
    if pct >= 1:
        return float(max(values))
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = pct * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def burn_rate(*, bad_fraction: float, target: float) -> float:
    """Burn rate = actual_bad_fraction / error_budget_fraction.

    ``target`` is the SLO target as a fraction (e.g. 0.995 for 99.5%).
    A burn rate of 1.0 means we're exactly spending the budget at target
    rate; 2.0 means double consumption. Clamped to 0 when the budget is
    effectively zero (target == 1) to avoid div-by-zero noise.
    """
    if bad_fraction <= 0:
        return 0.0
    budget = 1.0 - target
    if budget <= 0:
        return float("inf") if bad_fraction > 0 else 0.0
    return bad_fraction / budget


# ---------------------------------------------------------------------------
# DB query helpers — each returns a pre-aggregated list ready for computation.
# They're separate functions so tests can stub them cheaply and the cron
# can reuse the exact same aggregation the API route uses.
# ---------------------------------------------------------------------------


async def fetch_request_latencies_ms(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    span_kinds: tuple[str, ...] = _REQUEST_SPAN_KINDS,
) -> list[int]:
    """Return latency_ms values for user-facing request spans in the window."""
    stmt = select(AgentTraceSpan.latency_ms).where(
        AgentTraceSpan.created_at >= start,
        AgentTraceSpan.created_at < end,
        AgentTraceSpan.span_kind.in_(list(span_kinds)),
        AgentTraceSpan.latency_ms.isnot(None),
    )
    result = await session.execute(stmt)
    return [int(row[0]) for row in result.all() if row[0] is not None]


async def fetch_request_statuses(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    span_kinds: tuple[str, ...] = _REQUEST_SPAN_KINDS,
) -> tuple[int, int]:
    """Return ``(total, errors)`` counts over the window for request spans."""
    total_stmt = select(func.count(AgentTraceSpan.id)).where(
        AgentTraceSpan.created_at >= start,
        AgentTraceSpan.created_at < end,
        AgentTraceSpan.span_kind.in_(list(span_kinds)),
    )
    error_stmt = select(func.count(AgentTraceSpan.id)).where(
        AgentTraceSpan.created_at >= start,
        AgentTraceSpan.created_at < end,
        AgentTraceSpan.span_kind.in_(list(span_kinds)),
        AgentTraceSpan.status == TraceSpanStatus.ERROR,
    )
    total = (await session.execute(total_stmt)).scalar() or 0
    errors = (await session.execute(error_stmt)).scalar() or 0
    return int(total), int(errors)


async def fetch_quality_dimensions(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Return per-interaction quality scores within the window.

    One row per scored interaction — the caller is responsible for
    bucketing by agent and computing the p10 per dimension.
    """
    stmt = select(
        InteractionRecord.specialist,
        InteractionRecord.score_relevance,
        InteractionRecord.score_actionability,
        InteractionRecord.score_tone,
        InteractionRecord.score_conciseness,
    ).where(
        InteractionRecord.created_at >= start,
        InteractionRecord.created_at < end,
        InteractionRecord.score_relevance.isnot(None),
    )
    result = await session.execute(stmt)
    rows: list[dict[str, Any]] = []
    for row in result.all():
        rows.append(
            {
                "specialist": row[0],
                "score_relevance": row[1],
                "score_actionability": row[2],
                "score_tone": row[3],
                "score_conciseness": row[4],
            }
        )
    return rows


async def fetch_goodput_rows(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    latency_threshold_ms: int,
    quality_threshold: float,
) -> tuple[int, int]:
    """Return ``(total_interactions, good_interactions)`` over the window.

    An interaction is "good" when its duration_ms is under the p95
    latency threshold AND every scored quality dimension is >= the
    quality threshold. Unscored interactions are treated as failing
    the quality check (safer than declaring them good on the way up).
    """
    stmt = select(
        InteractionRecord.duration_ms,
        InteractionRecord.score_relevance,
        InteractionRecord.score_actionability,
        InteractionRecord.score_tone,
        InteractionRecord.score_conciseness,
    ).where(
        and_(
            InteractionRecord.created_at >= start,
            InteractionRecord.created_at < end,
        )
    )
    result = await session.execute(stmt)
    total = 0
    good = 0
    for row in result.all():
        total += 1
        latency_ok = row[0] is not None and row[0] <= latency_threshold_ms
        scores = [row[1], row[2], row[3], row[4]]
        quality_ok = all(s is not None and s >= quality_threshold for s in scores)
        if latency_ok and quality_ok:
            good += 1
    return total, good


async def fetch_daily_cost_gbp(
    session: AsyncSession,
    *,
    start_utc: datetime,
    end_utc: datetime,
) -> float:
    """Sum ``cost_usd`` over the window and convert using the latest price table."""
    stmt = select(func.coalesce(func.sum(AgentAction.cost_usd), 0.0)).where(
        AgentAction.created_at >= start_utc,
        AgentAction.created_at < end_utc,
        AgentAction.cost_usd.isnot(None),
    )
    total_usd = float((await session.execute(stmt)).scalar() or 0.0)
    try:
        table = _latest_price_table()
        rate = float(table.get("currency_usd_per_gbp", 0.79))
    except (FileNotFoundError, KeyError, ValueError, TypeError):
        rate = 0.79  # fallback — we'd rather over-report GBP than miss the breach
    return total_usd * rate


# ---------------------------------------------------------------------------
# SLO computations — each takes pre-fetched data so tests can stub cheaply.
# ---------------------------------------------------------------------------


def compute_latency_slo(
    *,
    latencies_ms: list[int],
    p95_seconds_target: float,
    p99_seconds_target: float,
    goodput_target: float,
) -> SLOValue:
    """Latency SLO — p95 < p95_seconds_target AND p99 < p99_seconds_target.

    Burn rate is derived from the fraction of requests that exceed the p95
    threshold compared to the goodput error budget (1 - target).
    """
    if not latencies_ms:
        return SLOValue(
            name="latency",
            current=0.0,
            target=p95_seconds_target,
            unit="seconds",
            meets_target=True,
            burn_rate=0.0,
            sample_size=0,
            details={"p95_seconds": 0.0, "p99_seconds": 0.0},
        )

    latencies_sec = [ms / 1000.0 for ms in latencies_ms]
    p95 = percentile(latencies_sec, 0.95)
    p99 = percentile(latencies_sec, 0.99)
    bad = sum(1 for sec in latencies_sec if sec > p95_seconds_target)
    bad_fraction = bad / len(latencies_sec)

    return SLOValue(
        name="latency",
        current=round(p95, 3),
        target=p95_seconds_target,
        unit="seconds",
        meets_target=(p95 < p95_seconds_target and p99 < p99_seconds_target),
        burn_rate=round(burn_rate(bad_fraction=bad_fraction, target=goodput_target), 3),
        sample_size=len(latencies_sec),
        details={
            "p95_seconds": round(p95, 3),
            "p99_seconds": round(p99, 3),
            "p99_target_seconds": p99_seconds_target,
        },
    )


def compute_error_slo(
    *,
    total: int,
    errors: int,
    max_error_rate: float,
) -> SLOValue:
    """Error SLO — 5xx/unhandled/LLM-provider errors < max_error_rate."""
    if total == 0:
        return SLOValue(
            name="error",
            current=0.0,
            target=max_error_rate,
            unit="ratio",
            meets_target=True,
            burn_rate=0.0,
            sample_size=0,
            details={"errors": 0, "total": 0},
        )
    rate = errors / total
    target = 1.0 - max_error_rate  # availability target
    return SLOValue(
        name="error",
        current=round(rate, 5),
        target=max_error_rate,
        unit="ratio",
        meets_target=(rate < max_error_rate),
        burn_rate=round(burn_rate(bad_fraction=rate, target=target), 3),
        sample_size=total,
        details={"errors": errors, "total": total},
    )


def compute_quality_slo(
    *,
    rows: list[dict[str, Any]],
    p10_min: float,
    goodput_target: float,
) -> SLOValue:
    """Quality SLO — p10 of 7-day rolling judge score >= p10_min per agent per dim.

    Fails if any (agent, dimension) pair has p10 below threshold. The
    ``details`` block lists the offending pairs so the alert is actionable.
    """
    if not rows:
        return SLOValue(
            name="quality",
            current=0.0,
            target=p10_min,
            unit="score",
            meets_target=True,
            burn_rate=0.0,
            sample_size=0,
            details={"breaches": []},
        )

    per_agent: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        specialist = row["specialist"] or "unknown"
        bucket = per_agent.setdefault(specialist, {dim: [] for dim in _QUALITY_DIMENSIONS})
        for dim in _QUALITY_DIMENSIONS:
            value = row.get(dim)
            if value is not None:
                bucket[dim].append(float(value))

    breaches: list[dict[str, Any]] = []
    worst_p10 = float("inf")
    for specialist, dims in per_agent.items():
        for dim, values in dims.items():
            if len(values) < 3:
                # Not enough samples to trust p10 — skip silently.
                continue
            p10 = percentile(values, 0.10)
            worst_p10 = min(worst_p10, p10)
            if p10 < p10_min:
                breaches.append(
                    {
                        "specialist": specialist,
                        "dimension": dim,
                        "p10": round(p10, 3),
                    }
                )

    if worst_p10 == float("inf"):
        worst_p10 = 0.0  # no agent had enough samples

    bad_fraction = len(breaches) / max(1, sum(len(d) for d in per_agent.values()))
    return SLOValue(
        name="quality",
        current=round(worst_p10, 3),
        target=p10_min,
        unit="score",
        meets_target=(not breaches),
        burn_rate=round(burn_rate(bad_fraction=bad_fraction, target=goodput_target), 3),
        sample_size=len(rows),
        details={"breaches": breaches, "agents": list(per_agent.keys())},
    )


def compute_goodput_slo(
    *,
    total: int,
    good: int,
    target: float,
) -> SLOValue:
    """Goodput SLO — % of requests meeting latency AND quality >= target."""
    if total == 0:
        return SLOValue(
            name="goodput",
            current=1.0,
            target=target,
            unit="ratio",
            meets_target=True,
            burn_rate=0.0,
            sample_size=0,
            details={"good": 0, "total": 0},
        )
    current = good / total
    bad_fraction = 1.0 - current
    return SLOValue(
        name="goodput",
        current=round(current, 4),
        target=target,
        unit="ratio",
        meets_target=(current >= target),
        burn_rate=round(burn_rate(bad_fraction=bad_fraction, target=target), 3),
        sample_size=total,
        details={"good": good, "total": total},
    )


def compute_cost_slo(
    *,
    spend_gbp: float,
    ceiling_gbp: float,
) -> SLOValue:
    """Cost SLO — daily LLM spend < cost_daily_ceiling_gbp.

    Burn rate here is intentionally "how deep into the ceiling are we"
    since any spend >= ceiling is a breach by definition. Sub-ceiling
    spend has burn_rate = 0 and the cron alert only fires on overrun.
    """
    if ceiling_gbp <= 0:
        return SLOValue(
            name="cost",
            current=round(spend_gbp, 4),
            target=0.0,
            unit="gbp",
            meets_target=True,
            burn_rate=0.0,
            sample_size=0,
            details={"ceiling_gbp": ceiling_gbp},
        )
    br = 0.0
    if spend_gbp > ceiling_gbp:
        br = spend_gbp / ceiling_gbp  # e.g. 1.2 means 20% over ceiling
    return SLOValue(
        name="cost",
        current=round(spend_gbp, 4),
        target=ceiling_gbp,
        unit="gbp",
        meets_target=(spend_gbp <= ceiling_gbp),
        burn_rate=round(br, 3),
        sample_size=1,
        details={"ceiling_gbp": ceiling_gbp},
    )


# ---------------------------------------------------------------------------
# Public entry point — fetch everything and return one report.
# ---------------------------------------------------------------------------


async def collect_slo_report(
    session: AsyncSession,
    settings: Settings,
    *,
    now: datetime | None = None,
    window_hours: int = 24,
    quality_window_days: int = 7,
) -> SLOReport:
    """Compute the five SLOs for the given rolling window.

    * Latency / error / goodput / cost use a 24h window by default.
    * Quality uses a 7-day window as the spec requires "p10 of 7-day
      rolling judge score" (stability vs point-in-time).
    """
    now = (now or datetime.now(UTC)).astimezone(UTC)
    window_end = now
    window_start = now - timedelta(hours=window_hours)
    quality_start = now - timedelta(days=quality_window_days)

    latency_p95_target = float(getattr(settings, "slo_latency_p95_seconds", 5.0))
    latency_p99_target = float(getattr(settings, "slo_latency_p99_seconds", 12.0))
    error_max = float(getattr(settings, "slo_error_rate_max", 0.005))
    quality_min = float(getattr(settings, "slo_quality_p10_min", 4.0))
    goodput_target = float(getattr(settings, "slo_goodput_target", 0.99))
    cost_ceiling = float(getattr(settings, "cost_daily_ceiling_gbp", 5.0))

    latencies = await fetch_request_latencies_ms(
        session,
        start=window_start,
        end=window_end,
    )
    total, errors = await fetch_request_statuses(
        session,
        start=window_start,
        end=window_end,
    )
    quality_rows = await fetch_quality_dimensions(
        session,
        start=quality_start,
        end=window_end,
    )

    # Derive the goodput latency threshold from the SLO p95 target so a
    # user-facing "good request" matches the advertised target.
    latency_threshold_ms = int(latency_p95_target * 1000)
    goodput_total, goodput_good = await fetch_goodput_rows(
        session,
        start=window_start,
        end=window_end,
        latency_threshold_ms=latency_threshold_ms,
        quality_threshold=quality_min,
    )

    spend_gbp = await fetch_daily_cost_gbp(
        session,
        start_utc=window_start,
        end_utc=window_end,
    )

    latency_slo = compute_latency_slo(
        latencies_ms=latencies,
        p95_seconds_target=latency_p95_target,
        p99_seconds_target=latency_p99_target,
        goodput_target=goodput_target,
    )
    error_slo = compute_error_slo(
        total=total,
        errors=errors,
        max_error_rate=error_max,
    )
    quality_slo = compute_quality_slo(
        rows=quality_rows,
        p10_min=quality_min,
        goodput_target=goodput_target,
    )
    goodput_slo = compute_goodput_slo(
        total=goodput_total,
        good=goodput_good,
        target=goodput_target,
    )
    cost_slo = compute_cost_slo(
        spend_gbp=spend_gbp,
        ceiling_gbp=cost_ceiling,
    )

    return SLOReport(
        window_hours=window_hours,
        generated_at=now,
        slos=[latency_slo, error_slo, quality_slo, goodput_slo, cost_slo],
    )


__all__ = [
    "DEFAULT_BURN_RATE_ALERT",
    "SLOReport",
    "SLOValue",
    "burn_rate",
    "collect_slo_report",
    "compute_cost_slo",
    "compute_error_slo",
    "compute_goodput_slo",
    "compute_latency_slo",
    "compute_quality_slo",
    "fetch_daily_cost_gbp",
    "fetch_goodput_rows",
    "fetch_quality_dimensions",
    "fetch_request_latencies_ms",
    "fetch_request_statuses",
    "percentile",
]
