"""Daily evaluation pipeline — exports, failures, reports, and Telegram summary.

This runs once a day (user-local 03:00) and turns the raw auto-judge scores
already stored in ``interaction_records`` into readable markdown on disk plus a
concise Telegram summary.

Outputs (all under ``data/evaluation/``):
  - ``exports/YYYY-MM-DD_<agent>.md``   — last 24h of scored interactions per agent
  - ``failures/YYYY-MM-DD_<agent>.md``  — interactions scoring <3.0 on any dim
  - ``reports/YYYY-MM-DD_summary.md``   — per-agent 7-day rolling means + regressions

The pipeline is pure Python — it does NOT call Anthropic. It relies on
the pre-scored rows that ``auto_judge`` has already written. If Telegram is
unconfigured, the summary is logged and the worker exits cleanly.

Scores in ``interaction_records`` are on the 0.0-1.0 scale (auto-judge output).
User-facing summaries present them on the 0-5 scale for readability. Internal
thresholds (4.0 warn, 0.3 regression) follow that convention.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from aiogram import Bot

from src.app.config import Settings
from src.app.persistence.repositories.interactions import (
    get_interactions_for_export,
    get_specialist_score_averages,
)

logger = structlog.get_logger()

# Score dimension keys as they appear on InteractionRecord.score_*
_DIMENSIONS: tuple[str, ...] = ("relevance", "actionability", "tone", "conciseness")

# Dimension labels used in the per-agent score averages dict
_AVG_KEYS: tuple[str, ...] = tuple(f"avg_{d}" for d in _DIMENSIONS)

# Display thresholds (all on the 0-5 scale — see module docstring)
_MIN_AGENT_OK_5PT = 4.0
_REGRESSION_DROP_5PT = 0.3
_FAILURE_THRESHOLD_5PT = 3.0


def _to_5pt(v: float | None) -> float | None:
    """Convert a 0-1 auto-judge score to a 0-5 display value."""
    return None if v is None else round(v * 5.0, 2)


def _fmt_5pt(v: float | None) -> str:
    """Render a 0-1 score as ``X.Y/5`` or ``N/A``."""
    scaled = _to_5pt(v)
    return "N/A" if scaled is None else f"{scaled:.1f}/5"


def _iter_dim_scores(record: Any) -> Iterable[tuple[str, float]]:
    """Yield (dimension, score) for each non-null dimension on a record."""
    for dim in _DIMENSIONS:
        value = getattr(record, f"score_{dim}", None)
        if value is not None:
            yield dim, float(value)


def _group_by_agent(records: list[Any]) -> dict[str, list[Any]]:
    """Bucket records by specialist name, preserving input order."""
    grouped: dict[str, list[Any]] = {}
    for record in records:
        grouped.setdefault(record.specialist, []).append(record)
    return grouped


def _mean_by_dim(records: list[Any]) -> dict[str, float | None]:
    """Compute per-dimension mean (ignores null dims) for a list of records."""
    means: dict[str, float | None] = {}
    for dim in _DIMENSIONS:
        values = [
            float(getattr(r, f"score_{dim}"))
            for r in records
            if getattr(r, f"score_{dim}", None) is not None
        ]
        means[dim] = sum(values) / len(values) if values else None
    return means


def _frontmatter(
    *,
    date_str: str,
    agent: str,
    n_samples: int,
    extra: dict[str, Any] | None = None,
) -> list[str]:
    """Return a YAML-ish frontmatter block for machine readability."""
    lines = [
        "---",
        f"date: {date_str}",
        f"agent: {agent}",
        f"n_samples: {n_samples}",
    ]
    if extra:
        for key, value in extra.items():
            if isinstance(value, dict):
                lines.append(f"{key}:")
                for sub_key, sub_val in value.items():
                    lines.append(f"  {sub_key}: {sub_val}")
            else:
                lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    return lines


def _write_agent_export(
    *,
    export_dir: Path,
    date_str: str,
    agent: str,
    records: list[Any],
) -> Path:
    """Write per-agent interactions file for the last 24h."""
    means = _mean_by_dim(records)
    mean_display = {dim: _fmt_5pt(val) for dim, val in means.items()}

    lines = _frontmatter(
        date_str=date_str,
        agent=agent,
        n_samples=len(records),
        extra={"mean_scores": mean_display},
    )
    lines.extend(
        [
            f"# Interactions — {agent} — {date_str}",
            "",
            f"Samples: {len(records)}",
            "",
            "## Mean Scores (0-5)",
            "",
        ]
    )
    for dim in _DIMENSIONS:
        lines.append(f"- {dim.title()}: {_fmt_5pt(means[dim])}")
    lines.append("")
    lines.extend(["## Records", ""])

    for record in records:
        score_bits = [f"{dim}={value:.2f}" for dim, value in _iter_dim_scores(record)] or [
            "not scored"
        ]
        record_data = {
            "id": str(record.id),
            "specialist": record.specialist,
            "created_at": (record.created_at.isoformat() if record.created_at else None),
            "scores": " ".join(score_bits),
            "feedback": getattr(record, "feedback_rating", None) or "none",
            "user_message": (record.user_message or "")[:500],
            "response": (record.response_content or "")[:1000],
        }
        reasoning = getattr(record, "auto_judge_reasoning", None)
        if reasoning:
            record_data["reasoning"] = reasoning

        lines.extend(
            [
                f"### {record.specialist} — "
                f"{record.created_at.isoformat() if record.created_at else 'unknown'}",
                "",
                "```json",
                json.dumps(record_data, indent=2),
                "```",
                "",
            ]
        )

    path = export_dir / f"{date_str}_{agent}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_agent_failures(
    *,
    failures_dir: Path,
    date_str: str,
    agent: str,
    records: list[Any],
) -> Path | None:
    """Write per-agent failures file. Returns None if no failures.

    A failure is any scored record whose worst dimension (on 0-5) is below
    ``_FAILURE_THRESHOLD_5PT`` (3.0).
    """
    threshold_01 = _FAILURE_THRESHOLD_5PT / 5.0
    failures: list[Any] = []
    for record in records:
        dim_scores = list(_iter_dim_scores(record))
        if not dim_scores:
            continue
        worst = min(value for _, value in dim_scores)
        if worst < threshold_01:
            failures.append(record)

    if not failures:
        return None

    lines = _frontmatter(
        date_str=date_str,
        agent=agent,
        n_samples=len(failures),
        extra={"threshold_5pt": _FAILURE_THRESHOLD_5PT},
    )
    lines.extend(
        [
            f"# Failures — {agent} — {date_str}",
            "",
            f"Records scoring below {_FAILURE_THRESHOLD_5PT}/5 on any dimension.",
            "",
        ]
    )

    for record in failures:
        dim_scores = dict(_iter_dim_scores(record))
        weakest_dim, weakest_val = min(
            dim_scores.items(),
            key=lambda kv: kv[1],
        )
        record_data = {
            "id": str(record.id),
            "specialist": record.specialist,
            "created_at": (record.created_at.isoformat() if record.created_at else None),
            "weakest_dimension": weakest_dim,
            "weakest_score_5pt": _to_5pt(weakest_val),
            "all_scores": {d: round(v, 3) for d, v in dim_scores.items()},
            "user_message": (record.user_message or "")[:500],
            "response": (record.response_content or "")[:1000],
        }
        reasoning = getattr(record, "auto_judge_reasoning", None)
        if reasoning:
            record_data["reasoning"] = reasoning

        lines.extend(
            [
                f"### {record.specialist} — {weakest_dim}={_fmt_5pt(weakest_val)}",
                "",
                "```json",
                json.dumps(record_data, indent=2),
                "```",
                "",
            ]
        )

    path = failures_dir / f"{date_str}_{agent}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _build_summary_report(
    *,
    date_str: str,
    today_by_agent: dict[str, dict[str, float | None]],
    baseline_by_agent: dict[str, dict[str, float | None]],
    agent_sample_counts: dict[str, int],
    min_samples: int,
) -> tuple[str, list[str], list[str]]:
    """Build the report content plus regression/below-budget flag lists.

    Returns (report_markdown, regression_notes, below_budget_notes).
    """
    regression_notes: list[str] = []
    below_budget_notes: list[str] = []

    lines = _frontmatter(
        date_str=date_str,
        agent="all",
        n_samples=sum(agent_sample_counts.values()),
        extra={
            "min_samples_per_agent": min_samples,
            "baseline_window_days": 7,
        },
    )
    lines.extend(
        [
            f"# Eval Summary — {date_str}",
            "",
            "Per-agent rolling 7-day means (0-5 scale).",
            "",
            "| Agent | N (today) | Relevance | Actionability | Tone | Conciseness |",
            "|-------|-----------|-----------|---------------|------|-------------|",
        ]
    )

    for agent in sorted(today_by_agent):
        today_means = today_by_agent[agent]
        baseline_means = baseline_by_agent.get(agent, {})
        n = agent_sample_counts.get(agent, 0)

        row = [
            agent,
            str(n),
            _fmt_5pt(today_means.get("relevance")),
            _fmt_5pt(today_means.get("actionability")),
            _fmt_5pt(today_means.get("tone")),
            _fmt_5pt(today_means.get("conciseness")),
        ]
        lines.append("| " + " | ".join(row) + " |")

        if n < min_samples:
            continue

        for dim in _DIMENSIONS:
            today_val = today_means.get(dim)
            baseline_val = baseline_means.get(dim)
            if today_val is None:
                continue

            today_5 = _to_5pt(today_val)
            if today_5 is not None and today_5 < _MIN_AGENT_OK_5PT:
                below_budget_notes.append(f"{agent} {dim} {today_5:.1f}/5 (< {_MIN_AGENT_OK_5PT})")

            if baseline_val is None:
                continue
            drop_5 = _to_5pt(baseline_val - today_val) or 0.0
            if drop_5 >= _REGRESSION_DROP_5PT:
                regression_notes.append(
                    f"{agent} {dim} dropped {drop_5:.2f} "
                    f"({_fmt_5pt(baseline_val)} -> {_fmt_5pt(today_val)})"
                )

    lines.append("")
    if regression_notes:
        lines.extend(["## Regressions (> 0.3 drop vs 7-day baseline)", ""])
        lines.extend(f"- {note}" for note in regression_notes)
        lines.append("")
    if below_budget_notes:
        lines.extend([f"## Below budget (< {_MIN_AGENT_OK_5PT}/5)", ""])
        lines.extend(f"- {note}" for note in below_budget_notes)
        lines.append("")
    if not regression_notes and not below_budget_notes:
        lines.extend(["## Status", "", "All agents within budget. No regressions.", ""])

    return "\n".join(lines), regression_notes, below_budget_notes


def _build_telegram_summary(
    *,
    date_str: str,
    today_by_agent: dict[str, dict[str, float | None]],
    agent_sample_counts: dict[str, int],
    min_samples: int,
    regression_notes: list[str],
    below_budget_notes: list[str],
) -> str:
    """Build the concise Telegram summary message."""
    header = f"Eval Summary — {date_str}"

    lines: list[str] = [header, ""]

    per_agent_bits: list[str] = []
    for agent in sorted(today_by_agent):
        n = agent_sample_counts.get(agent, 0)
        if n < min_samples:
            continue
        means = today_by_agent[agent]
        scored = [value for value in means.values() if value is not None]
        if not scored:
            continue
        overall = sum(scored) / len(scored)
        per_agent_bits.append(f"{agent.title()} {_fmt_5pt(overall)}")

    if per_agent_bits:
        lines.append(", ".join(per_agent_bits))
    else:
        lines.append(f"No agents had >= {min_samples} scored samples in the last 24h.")

    if not regression_notes and not below_budget_notes:
        lines.append("All within budget. No regressions.")
    else:
        if below_budget_notes:
            lines.append("")
            lines.append(f"Below {_MIN_AGENT_OK_5PT}/5:")
            lines.extend(f"- {n}" for n in below_budget_notes)
        if regression_notes:
            lines.append("")
            lines.append(f"Regressions (> {_REGRESSION_DROP_5PT} drop vs 7d baseline):")
            lines.extend(f"- {n}" for n in regression_notes)

    return "\n".join(lines)


async def _send_telegram_summary(
    *,
    bot: Bot | None,
    user_ids: list[int],
    message: str,
) -> bool:
    """Send the summary to the first allowed user. Returns True if sent."""
    if bot is None:
        logger.warning(
            "eval_pipeline_telegram_disabled",
            hint="Bot not configured — summary logged only",
        )
        return False
    if not user_ids:
        logger.warning("eval_pipeline_no_user_ids")
        return False

    try:
        await bot.send_message(chat_id=user_ids[0], text=message)
    except Exception:
        logger.exception("eval_pipeline_summary_send_failed")
        # Never let a Telegram failure crash the pipeline — the files
        # have already been written.
        return False
    return True


async def run_daily_eval_pipeline(ctx: dict) -> None:
    """Daily evaluation pipeline — build exports, failures, reports, Telegram.

    Called by ARQ cron at user-local 03:00. Produces files under
    ``data/evaluation/{exports,failures,reports}/`` and sends a concise
    Telegram summary. Never calls the Anthropic API.
    """
    settings: Settings = ctx["settings"]
    session_factory = ctx["session_factory"]
    bot: Bot | None = ctx.get("bot")

    if not getattr(settings, "eval_pipeline_enabled", True):
        logger.info("eval_pipeline_disabled")
        return

    min_samples = int(getattr(settings, "eval_pipeline_min_samples", 5))

    root = Path(getattr(settings, "evaluation_export_dir", "data/evaluation/exports"))
    base_dir = root.parent  # data/evaluation
    exports_dir = base_dir / "exports"
    failures_dir = base_dir / "failures"
    reports_dir = base_dir / "reports"

    for directory in (exports_dir, failures_dir, reports_dir):
        directory.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    window_start = now - timedelta(hours=24)
    baseline_start = now - timedelta(days=7)
    baseline_end = window_start
    date_str = now.strftime("%Y-%m-%d")

    async with session_factory() as session:
        records_24h = await get_interactions_for_export(
            session,
            start=window_start,
            end=now,
        )
        today_rows = await get_specialist_score_averages(
            session,
            start=window_start,
            end=now,
        )
        baseline_rows = await get_specialist_score_averages(
            session,
            start=baseline_start,
            end=baseline_end,
        )

    # --- Per-agent exports + failures for the last 24h ---
    grouped = _group_by_agent(records_24h)
    agent_sample_counts: dict[str, int] = {
        agent: len(records) for agent, records in grouped.items()
    }

    exports_written: list[str] = []
    failures_written: list[str] = []
    for agent, records in grouped.items():
        # Only keep scored records for per-agent aggregates, but the export
        # file includes all 24h records so we can see what was not scored.
        export_path = _write_agent_export(
            export_dir=exports_dir,
            date_str=date_str,
            agent=agent,
            records=records,
        )
        exports_written.append(str(export_path))

        failure_path = _write_agent_failures(
            failures_dir=failures_dir,
            date_str=date_str,
            agent=agent,
            records=records,
        )
        if failure_path is not None:
            failures_written.append(str(failure_path))

    # --- Per-agent means for today's window (scored-only, from repo aggregate) ---
    today_by_agent: dict[str, dict[str, float | None]] = {}
    for row in today_rows:
        agent = row["specialist"]
        today_by_agent[agent] = {dim: row.get(f"avg_{dim}") for dim in _DIMENSIONS}

    # --- 7-day baseline means (scored-only) ---
    baseline_by_agent: dict[str, dict[str, float | None]] = {}
    for row in baseline_rows:
        agent = row["specialist"]
        baseline_by_agent[agent] = {dim: row.get(f"avg_{dim}") for dim in _DIMENSIONS}

    # Make sure every agent we have raw records for shows up in the report
    # table, even if no records were scored yet.
    for agent in grouped:
        today_by_agent.setdefault(
            agent,
            {dim: None for dim in _DIMENSIONS},
        )

    report_md, regressions, below_budget = _build_summary_report(
        date_str=date_str,
        today_by_agent=today_by_agent,
        baseline_by_agent=baseline_by_agent,
        agent_sample_counts=agent_sample_counts,
        min_samples=min_samples,
    )

    report_path = reports_dir / f"{date_str}_summary.md"
    report_path.write_text(report_md, encoding="utf-8")

    # --- Telegram summary ---
    summary_text = _build_telegram_summary(
        date_str=date_str,
        today_by_agent=today_by_agent,
        agent_sample_counts=agent_sample_counts,
        min_samples=min_samples,
        regression_notes=regressions,
        below_budget_notes=below_budget,
    )

    sent = await _send_telegram_summary(
        bot=bot,
        user_ids=settings.allowed_user_ids,
        message=summary_text,
    )

    logger.info(
        "eval_pipeline_complete",
        date=date_str,
        n_records=len(records_24h),
        agents=sorted(grouped.keys()),
        exports=len(exports_written),
        failures=len(failures_written),
        report=str(report_path),
        telegram_sent=sent,
        regressions=regressions,
        below_budget=below_budget,
    )
