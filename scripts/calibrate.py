"""Monthly calibration CLI — human spot-check vs auto-judge drift.

Three subcommands:

- ``sample --month YYYY-MM [--n 30]``
    Pull a stratified random sample from ``interaction_records`` for the given
    month. At least ``settings.calibration_min_per_agent`` (default 3) per
    agent where possible, topping up with random picks to reach ``n``. Writes
    JSONL to ``data/evaluation/calibration/YYYY-MM_samples.jsonl``.

- ``score --file <path>``
    Walk the sample file in a simple TTY loop. For each interaction, print
    the prompt + response + auto-judge scores, then prompt the operator for 1-5 on
    each dim (or ``k`` to keep the auto-score). Writes the operator's scores to
    ``data/evaluation/calibration/YYYY-MM_human.jsonl`` one JSON object per
    line so the loop is resumable.

- ``report --month YYYY-MM``
    Aggregate drift per dim per agent (mean / p10 / p90 of ``human - auto``
    on the 1-5 scale). Writes a markdown report to
    ``data/evaluation/calibration/YYYY-MM.md``. Highlights agents/dims where
    ``should_block_prompt_edits`` fires based on the trailing N months.

Scores from the DB are on the 0-1 scale (auto-judge native). The operator scores on
1-5 (natural for humans). We convert 0-1 → 1-5 for comparison by multiplying
by 5 (0.8 → 4.0). Drift is reported on the 1-5 scale.

Not meant for CI — interactive TTY flow. Mocked in unit tests.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import uuid
from calendar import monthrange
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

from src.app.config import get_settings
from src.app.core.calibration import (
    DRIFT_BLOCK_CONSECUTIVE_MONTHS,
    DRIFT_BLOCK_THRESHOLD,
    should_block_prompt_edits,
)

logger = structlog.get_logger()

_DIMENSIONS: tuple[str, ...] = ("relevance", "actionability", "tone", "conciseness")
_CALIBRATION_DIR = Path("data/evaluation/calibration")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_month(value: str) -> tuple[datetime, datetime]:
    """Parse YYYY-MM and return inclusive UTC start + exclusive end."""
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:  # pragma: no cover — argparse rejects malformed input
        raise SystemExit(f"Invalid --month value {value!r}, expected YYYY-MM") from exc
    start = parsed.replace(tzinfo=UTC)
    last_day = monthrange(parsed.year, parsed.month)[1]
    end = start.replace(day=last_day, hour=23, minute=59, second=59)
    return start, end


def _to_5pt(value: float | None) -> float | None:
    """Convert a 0-1 auto-judge score to a 1-5 human-friendly score."""
    if value is None:
        return None
    # 0.0 → 0, 1.0 → 5. Clamp for safety.
    scaled = round(value * 5.0, 3)
    return max(0.0, min(5.0, scaled))


def _percentile(values: list[float], pct: float) -> float | None:
    """Compute a percentile without numpy. ``pct`` is in [0, 100]."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    fraction = rank - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


# ---------------------------------------------------------------------------
# sample subcommand
# ---------------------------------------------------------------------------


async def _sample(args: argparse.Namespace) -> None:
    """Pull a stratified random sample for the given month."""
    from sqlalchemy import func, select

    from src.app.domain.constants import EvalStatus
    from src.app.persistence.database import close_engine, init_engine, init_session_factory
    from src.app.persistence.models import InteractionRecord

    settings = get_settings()
    start, end = _parse_month(args.month)
    n = args.n or settings.calibration_default_sample_size
    min_per_agent = settings.calibration_min_per_agent

    engine = init_engine(settings.database_url.get_secret_value())
    session_factory = init_session_factory(engine)

    async with session_factory() as session:
        # Stratified pull: min_per_agent per agent, then top up randomly.
        agent_stmt = (
            select(InteractionRecord.specialist)
            .where(
                InteractionRecord.created_at >= start,
                InteractionRecord.created_at <= end,
                InteractionRecord.eval_status.in_(
                    [EvalStatus.AUTO_SCORED, EvalStatus.DEEP_SCORED],
                ),
            )
            .group_by(InteractionRecord.specialist)
        )
        result = await session.execute(agent_stmt)
        agents = [row[0] for row in result.all()]

        picked: list[InteractionRecord] = []
        picked_ids: set[uuid.UUID] = set()

        for agent in agents:
            stmt = (
                select(InteractionRecord)
                .where(
                    InteractionRecord.created_at >= start,
                    InteractionRecord.created_at <= end,
                    InteractionRecord.specialist == agent,
                    InteractionRecord.eval_status.in_(
                        [EvalStatus.AUTO_SCORED, EvalStatus.DEEP_SCORED],
                    ),
                )
                .order_by(func.random())
                .limit(min_per_agent)
            )
            result = await session.execute(stmt)
            for record in result.scalars().all():
                if record.id in picked_ids:
                    continue
                picked.append(record)
                picked_ids.add(record.id)

        # Top-up pass: random records to reach N
        remaining = max(0, n - len(picked))
        if remaining:
            topup_stmt = (
                select(InteractionRecord)
                .where(
                    InteractionRecord.created_at >= start,
                    InteractionRecord.created_at <= end,
                    InteractionRecord.eval_status.in_(
                        [EvalStatus.AUTO_SCORED, EvalStatus.DEEP_SCORED],
                    ),
                )
                .order_by(func.random())
                .limit(remaining * 3)  # overshoot to allow dedupe skipping
            )
            result = await session.execute(topup_stmt)
            for record in result.scalars().all():
                if len(picked) >= n:
                    break
                if record.id in picked_ids:
                    continue
                picked.append(record)
                picked_ids.add(record.id)

    await close_engine()

    if not picked:
        print(f"No scored interactions found for {args.month}.")
        return

    _CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    out_path = _CALIBRATION_DIR / f"{args.month}_samples.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for record in picked:
            fh.write(
                json.dumps(
                    {
                        "id": str(record.id),
                        "agent": record.specialist,
                        "user_message": record.user_message,
                        "response": record.response_content,
                        "auto_scores": {
                            dim: _to_5pt(getattr(record, f"score_{dim}")) for dim in _DIMENSIONS
                        },
                        "auto_reasoning": record.auto_judge_reasoning,
                        "created_at": record.created_at.isoformat() if record.created_at else None,
                    }
                )
                + "\n",
            )

    by_agent: dict[str, int] = defaultdict(int)
    for r in picked:
        by_agent[r.specialist] += 1
    summary = ", ".join(f"{k}={v}" for k, v in sorted(by_agent.items()))
    print(f"Sampled {len(picked)} interactions → {out_path}")
    print(f"Per-agent: {summary}")


# ---------------------------------------------------------------------------
# score subcommand
# ---------------------------------------------------------------------------


@dataclass
class _ScoreIO:
    """Stdin/stdout hooks — injectable so unit tests can mock the loop."""

    reader: Callable[[str], str]
    writer: Callable[[str], None]


def _default_io() -> _ScoreIO:
    return _ScoreIO(reader=input, writer=lambda s: print(s))


def _prompt_dim(io: _ScoreIO, dim: str, auto_5pt: float | None) -> float:
    """Prompt for a single dim score. 'k' keeps the auto score."""
    auto_str = "N/A" if auto_5pt is None else f"{auto_5pt:.2f}"
    while True:
        raw = io.reader(f"  {dim} (auto={auto_str}, 1-5 or k to keep): ").strip().lower()
        if raw == "k":
            if auto_5pt is None:
                io.writer("  (no auto score to keep — please enter 1-5)")
                continue
            return float(auto_5pt)
        try:
            val = float(raw)
        except ValueError:
            io.writer("  invalid — enter a number 1-5 or 'k'")
            continue
        if not 1.0 <= val <= 5.0:
            io.writer("  out of range — must be 1-5")
            continue
        return val


def _score_loop(
    samples: Iterable[dict],
    out_path: Path,
    *,
    io: _ScoreIO | None = None,
    already_scored_ids: set[str] | None = None,
) -> int:
    """Walk samples, collect operator scores, append to ``out_path`` as JSONL.

    Returns the number of newly scored items. Resumable — lines are appended
    one-at-a-time so Ctrl-C only loses the current interaction's keystrokes.
    """
    ioc = io or _default_io()
    seen = set(already_scored_ids or set())
    count = 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fh:
        for sample in samples:
            sample_id = sample["id"]
            if sample_id in seen:
                continue

            ioc.writer("")
            ioc.writer("=" * 72)
            ioc.writer(f"[{sample.get('agent', '?')}] id={sample_id}")
            ioc.writer(f"USER: {sample.get('user_message', '')[:500]}")
            ioc.writer(f"ASSISTANT: {sample.get('response', '')[:1000]}")
            auto_scores = sample.get("auto_scores") or {}
            ioc.writer(
                "AUTO: "
                + ", ".join(
                    f"{d}={auto_scores.get(d) if auto_scores.get(d) is not None else 'N/A'}"
                    for d in _DIMENSIONS
                )
            )
            if sample.get("auto_reasoning"):
                ioc.writer(f"REASONING: {sample['auto_reasoning']}")

            scores: dict[str, float] = {}
            for dim in _DIMENSIONS:
                scores[dim] = _prompt_dim(ioc, dim, auto_scores.get(dim))

            record = {
                "id": sample_id,
                "agent": sample.get("agent"),
                "human_scores": scores,
                "auto_scores": auto_scores,
                "scored_at": datetime.now(UTC).isoformat(),
            }
            fh.write(json.dumps(record) + "\n")
            fh.flush()
            count += 1
            seen.add(sample_id)

    return count


def _score(args: argparse.Namespace) -> None:
    """Open the sample file in a TTY loop and record operator scores."""
    sample_path = Path(args.file)
    if not sample_path.exists():
        print(f"Sample file not found: {sample_path}")
        sys.exit(1)

    with sample_path.open(encoding="utf-8") as fh:
        samples = [json.loads(line) for line in fh if line.strip()]

    if not samples:
        print("Sample file is empty — nothing to score.")
        return

    # Derive the human-review output path from the input filename.
    stem = sample_path.stem
    out_name = stem.replace("_samples", "_human") + ".jsonl"
    out_path = sample_path.parent / out_name

    already: set[str] = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    already.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    continue

    newly = _score_loop(samples, out_path, already_scored_ids=already)
    print(f"\nScored {newly} new interactions (total on disk: {len(already) + newly}).")
    print(f"Wrote {out_path}")


# ---------------------------------------------------------------------------
# report subcommand
# ---------------------------------------------------------------------------


def _compute_drift(
    human_rows: list[dict],
) -> dict[str, dict[str, dict[str, float]]]:
    """Return {agent: {dim: {mean, p10, p90, n}}} drift summary."""
    by_agent_dim: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list),
    )
    for row in human_rows:
        agent = row.get("agent") or "unknown"
        human_scores = row.get("human_scores", {})
        auto_scores = row.get("auto_scores", {})
        for dim in _DIMENSIONS:
            p = human_scores.get(dim)
            a = auto_scores.get(dim)
            if p is None or a is None:
                continue
            by_agent_dim[agent][dim].append(float(p) - float(a))

    summary: dict[str, dict[str, dict[str, float]]] = {}
    for agent, dims in by_agent_dim.items():
        summary[agent] = {}
        for dim, drifts in dims.items():
            summary[agent][dim] = {
                "mean": statistics.fmean(drifts) if drifts else 0.0,
                "p10": _percentile(drifts, 10) or 0.0,
                "p90": _percentile(drifts, 90) or 0.0,
                "n": len(drifts),
            }
    return summary


def _load_history(month: str) -> list[dict]:
    """Load current and up to 5 prior months of operator scoring files."""
    history: list[dict] = []
    current = Path(_CALIBRATION_DIR / f"{month}_human.jsonl")
    if current.exists():
        with current.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    history.append(json.loads(line))
    return history


def _load_prior_drift_series(
    month: str,
    max_months: int = 5,
) -> dict[str, dict[str, list[float]]]:
    """Load {agent: {dim: [drift_month-n, ..., drift_month_current]}} series.

    Reads ``YYYY-MM.md`` frontmatter-style JSON block from prior reports, or
    computes directly from the matching ``_human.jsonl`` files if present.
    """
    series: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list),
    )
    months = _previous_months(month, max_months)
    for m in [*months, month]:
        human_file = _CALIBRATION_DIR / f"{m}_human.jsonl"
        if not human_file.exists():
            continue
        with human_file.open(encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        drift = _compute_drift(rows)
        for agent, dims in drift.items():
            for dim, stats in dims.items():
                series[agent][dim].append(stats["mean"])
    return series


def _previous_months(month: str, n: int) -> list[str]:
    """Return the ``n`` months immediately prior to ``month`` (oldest first)."""
    base = datetime.strptime(month, "%Y-%m")
    out: list[str] = []
    year, m = base.year, base.month
    for _ in range(n):
        m -= 1
        if m == 0:
            m = 12
            year -= 1
        out.append(f"{year:04d}-{m:02d}")
    return list(reversed(out))


def _build_report_markdown(
    *,
    month: str,
    summary: dict[str, dict[str, dict[str, float]]],
    drift_series: dict[str, dict[str, list[float]]],
) -> str:
    """Build the markdown calibration report."""
    lines = [
        f"# Calibration Report — {month}",
        "",
        f"Generated at: {datetime.now(UTC).isoformat()}",
        "Drift = operator score - auto-judge score (on 1-5 scale).",
        f"Block rule: same dim drifts > {DRIFT_BLOCK_THRESHOLD:.1f} for "
        f"{DRIFT_BLOCK_CONSECUTIVE_MONTHS} consecutive months.",
        "",
    ]

    if not summary:
        lines.extend(["_No scored samples found — run `calibrate.py score` first._", ""])
        return "\n".join(lines)

    block_flags: list[str] = []

    for agent in sorted(summary):
        lines.extend([f"## {agent}", ""])
        lines.append("| Dim | N | Mean drift | P10 | P90 | Block? |")
        lines.append("|-----|---|------------|-----|-----|--------|")
        for dim in _DIMENSIONS:
            stats = summary[agent].get(dim)
            if stats is None:
                lines.append(f"| {dim} | 0 | — | — | — | — |")
                continue
            history = drift_series.get(agent, {}).get(dim, [])
            blocked = should_block_prompt_edits(agent, dim, history)
            if blocked:
                block_flags.append(f"{agent}/{dim}")
            lines.append(
                f"| {dim} | {stats['n']} | {stats['mean']:+.2f} | "
                f"{stats['p10']:+.2f} | {stats['p90']:+.2f} | "
                f"{'YES' if blocked else 'no'} |"
            )
        lines.append("")

    lines.extend(["## Overall Drift Summary", ""])
    total_drifts: list[float] = [
        stats["mean"] for dims in summary.values() for stats in dims.values()
    ]
    if total_drifts:
        mean_abs_drift = statistics.fmean(abs(d) for d in total_drifts)
        lines.append(f"- Overall mean |drift|: {mean_abs_drift:.2f}")
        lines.append(f"- Max mean drift: {max(total_drifts, key=abs):+.2f}")
    if block_flags:
        lines.append("")
        lines.append(
            f"**Blocked from prompt edits** ({len(block_flags)} agent/dim pairs): "
            + ", ".join(block_flags),
        )
    lines.append("")
    return "\n".join(lines)


def _report(args: argparse.Namespace) -> None:
    """Compute drift and write a markdown report."""
    human_file = _CALIBRATION_DIR / f"{args.month}_human.jsonl"
    if not human_file.exists():
        print(f"No operator scores found for {args.month}: {human_file} missing.")
        sys.exit(1)

    rows = _load_history(args.month)
    if not rows:
        print(f"Operator score file empty: {human_file}")
        sys.exit(1)

    summary = _compute_drift(rows)
    drift_series = _load_prior_drift_series(args.month)

    content = _build_report_markdown(
        month=args.month,
        summary=summary,
        drift_series=drift_series,
    )

    out_path = _CALIBRATION_DIR / f"{args.month}.md"
    out_path.write_text(content, encoding="utf-8")
    print(f"Wrote {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Monthly calibration — human spot-check vs auto-judge drift.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sample_p = sub.add_parser("sample", help="Pull a stratified monthly sample")
    sample_p.add_argument("--month", required=True, help="YYYY-MM")
    sample_p.add_argument("--n", type=int, default=None, help="Target sample size (default 30)")

    score_p = sub.add_parser("score", help="Score samples in a TTY loop")
    score_p.add_argument("--file", required=True, help="Path to samples JSONL")

    report_p = sub.add_parser("report", help="Compute drift and write report")
    report_p.add_argument("--month", required=True, help="YYYY-MM")

    args = parser.parse_args()

    if args.command == "sample":
        asyncio.run(_sample(args))
    elif args.command == "score":
        _score(args)
    elif args.command == "report":
        _report(args)


if __name__ == "__main__":
    main()
