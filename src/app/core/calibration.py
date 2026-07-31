"""Calibration helpers — drift-guard rules and judge-model version tracking.

Shared module used by both the monthly calibration CLI (``scripts/calibrate.py``)
and the startup preflight (to detect a new Anthropic snapshot of the auto-judge
model and nudge the operator to recalibrate).

Design rules (April 2026 best practice):

- A single-month drift blip is NOT a block signal. We only block prompt edits
  when the SAME dimension drifts > 0.5 for TWO consecutive months — sustained
  disagreement between the operator and the auto-judge, not a noisy sample.
- Auto-recalibration triggers fire when the judge model's snapshot version
  changes (e.g. ``claude-sonnet-4-6`` → ``claude-sonnet-4-6.1``). The
  ``auto_judge_model_version_pinned`` config freezes the expected version, and
  a small persistent state file remembers the last seen snapshot so we don't
  spam the alert every startup.

The state file lives outside the data directory because it represents runtime
metadata (version seen on last boot), not evaluation data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# The magnitude of drift (on the 1-5 scale) that warrants a block when sustained.
DRIFT_BLOCK_THRESHOLD: float = 0.5

# Number of consecutive months the same dimension must exceed the threshold
# before we block prompt edits. Single-month blips are tolerated as noise.
DRIFT_BLOCK_CONSECUTIVE_MONTHS: int = 2

# Days after a judge-model version change before the operator should have recalibrated.
# Used to format the Telegram alert text, not enforced as a hard deadline.
RECALIBRATION_SLA_DAYS: int = 7


def should_block_prompt_edits(
    agent: str,
    dim: str,
    recent_months: list[float],
) -> bool:
    """Return True if prompt edits for ``agent``/``dim`` should be blocked.

    ``recent_months`` is the drift value (``human_mean - auto_mean``, on the
    1-5 scale) for the agent/dim pair for each of the most recent months,
    ordered oldest → newest. Months without enough samples should be
    represented as ``0.0`` or omitted — we require strict consecutive
    exceedances of ``DRIFT_BLOCK_THRESHOLD`` in absolute value.

    Rule: block only when the last N months (N = ``DRIFT_BLOCK_CONSECUTIVE_MONTHS``)
    ALL show |drift| > ``DRIFT_BLOCK_THRESHOLD``. A single-month blip is never
    enough — that's sampling noise, not judge drift.
    """
    if len(recent_months) < DRIFT_BLOCK_CONSECUTIVE_MONTHS:
        # Not enough history to judge — never block on sparse data.
        return False

    tail = recent_months[-DRIFT_BLOCK_CONSECUTIVE_MONTHS:]
    blocked = all(abs(d) > DRIFT_BLOCK_THRESHOLD for d in tail)

    if blocked:
        logger.warning(
            "calibration_drift_block",
            agent=agent,
            dim=dim,
            threshold=DRIFT_BLOCK_THRESHOLD,
            consecutive_months=DRIFT_BLOCK_CONSECUTIVE_MONTHS,
            recent_drifts=tail,
        )
    return blocked


def _state_file_path() -> Path:
    """Return the default path for the judge-model version state file.

    Kept alongside other calibration artefacts. Created on first write.
    """
    return Path("data/evaluation/calibration/_judge_model_state.json")


def load_judge_model_state(path: Path | None = None) -> dict[str, Any]:
    """Return the persisted state: {model_snapshot_seen, last_seen_at}.

    Returns an empty dict if the file does not exist or is corrupt — the
    caller treats that as "no snapshot recorded yet" and will seed the file
    on next check.
    """
    target = path or _state_file_path()
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("calibration_state_unreadable", path=str(target))
        return {}


def save_judge_model_state(
    *,
    model_snapshot_seen: str,
    path: Path | None = None,
) -> None:
    """Persist the currently observed judge model snapshot."""
    target = path or _state_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_snapshot_seen": model_snapshot_seen,
        "last_seen_at": datetime.now(UTC).isoformat(),
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def judge_model_changed(
    *,
    current_snapshot: str,
    pinned_version: str,
    state_path: Path | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Detect a judge-model snapshot change.

    Returns (changed, state). ``changed`` is True when either:
      - the current snapshot differs from the pinned version in config, OR
      - the current snapshot differs from the last-seen snapshot on disk
        AND the state file already existed (first-ever boot is not a change).

    Callers should fire a Telegram alert + log ``judge_model_version_changed``
    when this returns True, then update the state file via
    ``save_judge_model_state`` so the alert only fires once per transition.
    """
    if not current_snapshot:
        # Empty means we have no information — don't false-alarm.
        return False, {}

    state = load_judge_model_state(state_path)
    last_seen = state.get("model_snapshot_seen")

    changed_vs_pin = bool(pinned_version) and current_snapshot != pinned_version
    changed_vs_seen = last_seen is not None and last_seen != current_snapshot
    changed = changed_vs_pin or changed_vs_seen

    return changed, {
        "current_snapshot": current_snapshot,
        "last_seen": last_seen,
        "pinned_version": pinned_version or None,
        "changed_vs_pin": changed_vs_pin,
        "changed_vs_seen": changed_vs_seen,
    }
