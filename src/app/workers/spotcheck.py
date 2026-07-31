"""Weekly human spot-check nudge — Friday 14:00 local.

Samples 5 random interactions from the last 7 days (stratified by agent where
possible), writes a short markdown queue file to
``data/evaluation/spotcheck/<YYYY-MM-DD>_queue.md``, and fires a Telegram nudge
pointing the operator at the file.

The file has a simple table:

    | ID | Agent | Prompt | Response | Auto | ✓/✗/edit | Note |

The operator fills it in with ``scripts/spotcheck.py score``. The weekly summary
(``scripts/spotcheck.py weekly-summary``) rolls up mismatch rates.

Pure Python — does not call Anthropic. No-op when ``spotcheck_enabled`` is
False or when fewer than 1 scored record exists in the 7-day window.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from aiogram import Bot
from sqlalchemy import func, select

from src.app.config import Settings
from src.app.domain.constants import EvalStatus
from src.app.persistence.models import InteractionRecord

logger = structlog.get_logger()

SPOTCHECK_DIR = Path("data/evaluation/spotcheck")
_DIMENSIONS: tuple[str, ...] = ("relevance", "actionability", "tone", "conciseness")


def _mean_auto_5pt(record: Any) -> float | None:
    """Mean auto score on 0-5 scale, ignoring None dims."""
    vals = [
        getattr(record, f"score_{d}")
        for d in _DIMENSIONS
        if getattr(record, f"score_{d}", None) is not None
    ]
    if not vals:
        return None
    return round(sum(vals) * 5.0 / len(vals), 2)


def _truncate(text: str, limit: int) -> str:
    """Single-line truncation for the markdown table."""
    cleaned = (text or "").replace("\n", " ").replace("|", "/").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _build_queue_markdown(
    *,
    date_str: str,
    records: list[Any],
) -> str:
    """Build the markdown spot-check queue file."""
    lines = [
        f"# Weekly Spot-check — {date_str}",
        "",
        (
            "Take ~15 min: read each interaction's prompt + response, mark ✓ "
            "if the auto-judge score feels right, ✗ otherwise, jot a word."
        ),
        "",
        "| ID | Agent | Prompt | Response | Auto (mean /5) | ✓/✗/edit | Note |",
        "|----|-------|--------|----------|----------------|----------|------|",
    ]
    for record in records:
        mean_auto = _mean_auto_5pt(record)
        mean_display = "N/A" if mean_auto is None else f"{mean_auto:.2f}"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(record.id)[:8],
                    record.specialist,
                    _truncate(record.user_message, 80),
                    _truncate(record.response_content, 80),
                    mean_display,
                    " ",
                    " ",
                ]
            )
            + " |",
        )

    # Stash a JSON block at the bottom so the scorer CLI can pick up the
    # full IDs without re-hitting the database.
    payload = [
        {
            "id": str(r.id),
            "agent": r.specialist,
            "user_message": r.user_message,
            "response": r.response_content,
            "auto_mean_5pt": _mean_auto_5pt(r),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]
    lines.extend(["", "<!-- spotcheck-data", json.dumps(payload), "-->", ""])
    return "\n".join(lines)


async def _sample_recent(
    session_factory: Any,
    *,
    n: int,
    now: datetime,
) -> list[Any]:
    """Sample up to ``n`` recent scored interactions, stratified by agent.

    Picks 1 per agent (ordered random) from the past 7d, then tops up
    randomly to reach ``n``.
    """
    start = now - timedelta(days=7)

    async with session_factory() as session:
        agents_stmt = (
            select(InteractionRecord.specialist)
            .where(
                InteractionRecord.created_at >= start,
                InteractionRecord.eval_status.in_(
                    [EvalStatus.AUTO_SCORED, EvalStatus.DEEP_SCORED],
                ),
            )
            .group_by(InteractionRecord.specialist)
        )
        agents = [row[0] for row in (await session.execute(agents_stmt)).all()]

        picked: list[Any] = []
        seen: set[uuid.UUID] = set()

        for agent in agents:
            if len(picked) >= n:
                break
            stmt = (
                select(InteractionRecord)
                .where(
                    InteractionRecord.created_at >= start,
                    InteractionRecord.specialist == agent,
                    InteractionRecord.eval_status.in_(
                        [EvalStatus.AUTO_SCORED, EvalStatus.DEEP_SCORED],
                    ),
                )
                .order_by(func.random())
                .limit(1)
            )
            for record in (await session.execute(stmt)).scalars().all():
                if record.id not in seen:
                    picked.append(record)
                    seen.add(record.id)

        remaining = max(0, n - len(picked))
        if remaining:
            topup_stmt = (
                select(InteractionRecord)
                .where(
                    InteractionRecord.created_at >= start,
                    InteractionRecord.eval_status.in_(
                        [EvalStatus.AUTO_SCORED, EvalStatus.DEEP_SCORED],
                    ),
                )
                .order_by(func.random())
                .limit(remaining * 3)
            )
            for record in (await session.execute(topup_stmt)).scalars().all():
                if len(picked) >= n:
                    break
                if record.id in seen:
                    continue
                picked.append(record)
                seen.add(record.id)

    return picked[:n]


async def run_weekly_spotcheck_nudge(ctx: dict) -> None:
    """ARQ cron entry point that samples 5 interactions and nudges the operator.

    Exits cleanly (with a log) when:
      - ``spotcheck_enabled`` is False
      - no scored interactions exist in the last 7 days
      - Telegram isn't configured (we still write the queue file so the operator
        can run the CLI manually)
    """
    settings: Settings = ctx["settings"]
    session_factory = ctx["session_factory"]
    bot: Bot | None = ctx.get("bot")

    if not settings.spotcheck_enabled:
        logger.info("spotcheck_disabled")
        return

    n = settings.spotcheck_n_per_week
    now = datetime.now(UTC)
    records = await _sample_recent(session_factory, n=n, now=now)

    if not records:
        logger.info("spotcheck_no_records")
        return

    date_str = now.strftime("%Y-%m-%d")
    spotcheck_dir = Path(getattr(settings, "spotcheck_dir", SPOTCHECK_DIR))
    spotcheck_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    queue_path = spotcheck_dir / f"{date_str}_queue.md"
    queue_path.write_text(
        _build_queue_markdown(date_str=date_str, records=records),
        encoding="utf-8",
    )

    logger.info(
        "spotcheck_queue_written",
        path=str(queue_path),
        count=len(records),
    )

    if bot is None:
        logger.warning("spotcheck_no_bot", hint="Telegram not configured")
        return

    user_ids = settings.allowed_user_ids
    if not user_ids:
        logger.warning("spotcheck_no_user_ids")
        return

    message = (
        f"Friday 14:00 — {len(records)} spot-check interactions ready. "
        "Takes 15 min. Open: "
        f"{spotcheck_dir.as_posix()}/{date_str}_queue.md"
    )
    try:
        await bot.send_message(chat_id=user_ids[0], text=message)
        logger.info("spotcheck_nudge_sent", count=len(records))
    except Exception:
        logger.exception("spotcheck_nudge_send_failed")
        raise
