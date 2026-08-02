"""Energy-aware scheduling driven by the identity configuration."""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import structlog
from pydantic import BaseModel

from src.app.core.exceptions import ConfigError

logger = structlog.get_logger()

_ADMIN_TAGS = {"email", "admin", "meeting"}
_CREATIVE_TAGS = {"creative", "writing", "brainstorm"}
_CONFIG_ROOT = Path(__file__).resolve().parents[3] / "config"
_IDENTITY_LOCAL_PATH = _CONFIG_ROOT / "IDENTITY.local.md"
_IDENTITY_EXAMPLE_PATH = _CONFIG_ROOT / "IDENTITY.example.md"
_RANGE_RE = re.compile(r"(\d{2}):(\d{2})[\u2013-](\d{2}):(\d{2})")
_START_PLUS_RE = re.compile(r"(\d{2}):(\d{2})\+")
_DEFAULT_IDENTITY_SCHEDULE = """\
- Peak focus: 09:00-12:00 (deep work, analysis)
- Admin window: 13:00-15:00 (email, admin)
- Creative/reflective: 19:00-21:00 (creative, writing)
- Low energy: 12:00-13:00 (light tasks), 21:00+ (rest)
"""


class EnergyBlock(BaseModel):
    """A named time block with an energy profile and suited task types."""

    label: str
    start_hour: int
    end_hour: int
    task_types: list[str]


_FREE_BLOCK = EnergyBlock(
    label="free",
    start_hour=0,
    end_hour=0,
    task_types=["any"],
)


def get_energy_block(hour: int) -> EnergyBlock:
    """Return the configured energy block that covers the given hour (0-23)."""
    for block in get_energy_blocks():
        if block.start_hour <= hour < block.end_hour:
            logger.debug("energy_block_matched", hour=hour, label=block.label)
            return block

    logger.debug("energy_block_default", hour=hour, label="free")
    return _FREE_BLOCK


def get_energy_blocks() -> list[EnergyBlock]:
    """Return energy blocks parsed from the identity configuration."""
    return list(_load_energy_blocks())


def suggest_task_timing(tasks: list[dict]) -> list[dict]:
    """Add a ``suggested_block`` field to each task based on complexity and tags."""
    if not tasks:
        return []

    results: list[dict] = []
    for task in tasks:
        suggested = _classify_task(task)
        enriched = {**task, "suggested_block": suggested}
        results.append(enriched)

        logger.debug(
            "task_scheduled",
            task_has_title=bool(task.get("title")),
            suggested_block=suggested,
        )

    return results


def format_energy_schedule() -> str:
    """Return a human-readable energy schedule for use in planning."""
    lines: list[str] = ["Energy Schedule", "=" * 40]

    for block in get_energy_blocks():
        start = _format_hour(block.start_hour)
        end = _format_hour(block.end_hour)
        suited = ", ".join(block.task_types)
        lines.append(f"  {start}-{end}  {block.label:<12}  ({suited})")

    lines.append("=" * 40)
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _load_energy_blocks() -> tuple[EnergyBlock, ...]:
    """Load private local identity, the public example, or safe defaults."""
    identity_path = (
        _IDENTITY_LOCAL_PATH if _IDENTITY_LOCAL_PATH.exists() else _IDENTITY_EXAMPLE_PATH
    )
    try:
        identity = (
            identity_path.read_text(encoding="utf-8")
            if identity_path.exists()
            else _DEFAULT_IDENTITY_SCHEDULE
        )
    except OSError:
        logger.warning("identity_schedule_unreadable_using_defaults", file=str(identity_path))
        identity = _DEFAULT_IDENTITY_SCHEDULE

    lines = identity.splitlines()
    try:
        peak_line = _find_identity_line(lines, "Peak focus")
        admin_line = _find_identity_line(lines, "Admin window")
        creative_line = _find_identity_line(lines, "Creative/reflective")
        low_energy_line = _find_identity_line(lines, "Low energy")
    except ConfigError:
        logger.info("identity_schedule_missing_using_defaults")
        lines = _DEFAULT_IDENTITY_SCHEDULE.splitlines()
        peak_line = _find_identity_line(lines, "Peak focus")
        admin_line = _find_identity_line(lines, "Admin window")
        creative_line = _find_identity_line(lines, "Creative/reflective")
        low_energy_line = _find_identity_line(lines, "Low energy")

    blocks = (
        EnergyBlock(
            label="deep_work",
            start_hour=_parse_range_hours(peak_line, "Peak focus")[0],
            end_hour=_parse_range_hours(peak_line, "Peak focus")[1],
            task_types=_parse_task_types(peak_line),
        ),
        EnergyBlock(
            label="low_energy",
            start_hour=_parse_range_hours(low_energy_line, "Low energy")[0],
            end_hour=_parse_range_hours(low_energy_line, "Low energy")[1],
            task_types=_parse_low_energy_task_types(low_energy_line)[0],
        ),
        EnergyBlock(
            label="admin",
            start_hour=_parse_range_hours(admin_line, "Admin window")[0],
            end_hour=_parse_range_hours(admin_line, "Admin window")[1],
            task_types=_parse_task_types(admin_line),
        ),
        EnergyBlock(
            label="creative",
            start_hour=_parse_range_hours(creative_line, "Creative/reflective")[0],
            end_hour=_parse_range_hours(creative_line, "Creative/reflective")[1],
            task_types=_parse_task_types(creative_line),
        ),
        EnergyBlock(
            label="low_energy",
            start_hour=_parse_plus_hour(low_energy_line, "Low energy"),
            end_hour=24,
            task_types=_parse_low_energy_task_types(low_energy_line)[1],
        ),
    )

    return blocks


def _find_identity_line(lines: Sequence[str], label: str) -> str:
    prefix = f"- {label}:"
    for line in lines:
        if line.startswith(prefix):
            return line
    raise ConfigError(f"Identity configuration is missing '{label}'.")


def _parse_range_hours(line: str, label: str) -> tuple[int, int]:
    match = _RANGE_RE.search(line)
    if match is None:
        raise ConfigError(f"Identity configuration has no time range for '{label}'.")

    start_hour = _parse_hour(match.group(1), match.group(2), label)
    end_hour = _parse_hour(match.group(3), match.group(4), label)
    return start_hour, end_hour


def _parse_plus_hour(line: str, label: str) -> int:
    match = _START_PLUS_RE.search(line)
    if match is None:
        raise ConfigError(f"Identity configuration has no trailing hour for '{label}'.")
    return _parse_hour(match.group(1), match.group(2), label)


def _parse_hour(hour: str, minute: str, label: str) -> int:
    if minute != "00":
        raise ConfigError(
            "Identity configuration for "
            f"'{label}' must use full-hour boundaries, got {hour}:{minute}."
        )
    return int(hour)


def _parse_task_types(line: str) -> list[str]:
    match = re.search(r"\(([^)]+)\)", line)
    if match is None:
        raise ConfigError(f"Identity configuration is missing task types in: {line}")
    return [part.strip().replace(" ", "_") for part in match.group(1).split(",") if part.strip()]


def _parse_low_energy_task_types(line: str) -> tuple[list[str], list[str]]:
    matches = re.findall(r"\(([^)]+)\)", line)
    if len(matches) < 2:
        raise ConfigError(f"Identity configuration is missing low-energy descriptors in: {line}")
    return (
        [matches[0].strip().replace(" ", "_")],
        [matches[1].strip().replace(" ", "_")],
    )


def _classify_task(task: dict) -> str:
    """Determine the best energy block label for a task."""
    complexity: str = task.get("complexity", "medium")
    tags: list[str] = [t.lower() for t in task.get("tags", [])]

    if complexity == "high":
        return "deep_work"

    if _ADMIN_TAGS & set(tags):
        return "admin"

    if _CREATIVE_TAGS & set(tags):
        return "creative"

    if complexity == "low":
        return "admin"

    return "free"


def _format_hour(hour: int) -> str:
    """Format hour (0-24) as a 12-hour clock string."""
    if hour == 0 or hour == 24:
        return "12am"
    if hour == 12:
        return "12pm"
    if hour < 12:
        return f"{hour}am"
    return f"{hour - 12}pm"
