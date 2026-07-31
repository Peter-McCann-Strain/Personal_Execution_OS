"""CLI tool for the ARQ dead-letter queue (Phase 7.1).

Usage:
    # List the 100 most recent unreplayed failures
    uv run python -m scripts.dlq_replay list

    # Filter by function, include replayed rows, last 48 hours
    uv run python -m scripts.dlq_replay list --function process_agent_task:entity_extraction \\
        --include-replayed --hours 48

    # Dump one row fully (kwargs + traceback)
    uv run python -m scripts.dlq_replay show <uuid>

    # Re-enqueue one failed job
    uv run python -m scripts.dlq_replay replay <uuid>

    # Re-enqueue every unreplayed row for a function (needs --yes or prompt)
    uv run python -m scripts.dlq_replay replay --function process_agent_task:notification --yes

    # Delete replayed rows older than 30 days
    uv run python -m scripts.dlq_replay prune --older-than 30d
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid as uuid_module
from datetime import UTC, datetime
from typing import Any

import structlog

from src.app.config import get_settings
from src.app.persistence.database import init_engine, init_session_factory
from src.app.persistence.models import DLQJob
from src.app.persistence.repositories.dlq_jobs import (
    delete_replayed_older_than,
    get_dlq_job_by_id,
    list_dlq_jobs,
    mark_replayed,
)

logger = structlog.get_logger()


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%SZ")


def _print_table(rows: list[DLQJob]) -> None:
    if not rows:
        print("(no rows)")
        return
    header = f"{'id':<36}  {'function':<40}  {'failed_at':<21}  {'exception':<28}  retries"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r.id!s:<36}  "
            f"{(r.function or '<unknown>')[:40]:<40}  "
            f"{_fmt_dt(r.failed_at):<21}  "
            f"{(r.exception_class or '')[:28]:<28}  "
            f"{r.retry_count}"
        )


def _serialize_row(row: DLQJob) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "job_id": row.job_id,
        "function": row.function,
        "args": row.args,
        "kwargs": row.kwargs,
        "exception_class": row.exception_class,
        "exception_message": row.exception_message,
        "traceback": row.traceback,
        "retry_count": row.retry_count,
        "enqueued_at": row.enqueued_at.isoformat() if row.enqueued_at else None,
        "failed_at": row.failed_at.isoformat() if row.failed_at else None,
        "replayed_at": row.replayed_at.isoformat() if row.replayed_at else None,
        "replay_result": row.replay_result,
    }


async def _enqueue_agent_task_direct(task_type: str, payload: dict) -> None:
    """Re-enqueue process_agent_task preserving the original request_id."""
    from arq.connections import RedisSettings, create_pool

    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.redis_url.get_secret_value())
    pool = await create_pool(redis_settings)
    try:
        await pool.enqueue_job("process_agent_task", task_type, payload)
    finally:
        await pool.aclose()


def _parse_process_agent_task(row: DLQJob) -> tuple[str, dict] | None:
    """Extract (task_type, payload) from a DLQ row if it's a process_agent_task job."""
    if not row.function or not row.function.startswith("process_agent_task:"):
        return None
    task_type = row.function.split(":", 1)[1]
    payload: dict = {}
    if isinstance(row.kwargs, dict):
        inner = row.kwargs.get("payload")
        if isinstance(inner, dict):
            payload = dict(inner)
    return task_type, payload


async def _replay_row(row: DLQJob) -> str:
    """Replay one row. Returns the replay_result string ('queued' or 'skipped:…')."""
    parsed = _parse_process_agent_task(row)
    if parsed is None:
        return f"skipped:unsupported_function:{row.function}"
    task_type, payload = parsed
    # Preserve the original request_id so correlation IDs survive replay.
    # The payload already carries it when present (set by _attach_request_id
    # at the original enqueue site).
    await _enqueue_agent_task_direct(task_type, payload)
    return "queued"


def _confirm_batch(count: int, function: str) -> bool:
    resp = input(f"Replay {count} row(s) for function '{function}'? [y/N]: ").strip().lower()
    return resp in {"y", "yes"}


_DURATION_RE = re.compile(r"^(\d+)([dhm])$")


def _parse_age_to_days(value: str) -> int:
    """Parse '30d' / '72h' / '120m' into a whole-day count (rounded up)."""
    match = _DURATION_RE.match(value.strip().lower())
    if not match:
        raise ValueError(f"Invalid --older-than value {value!r}. Use e.g. '30d', '72h', or '120m'.")
    qty, unit = int(match.group(1)), match.group(2)
    if unit == "d":
        return qty
    if unit == "h":
        return max(1, (qty + 23) // 24)
    return max(1, (qty + 60 * 24 - 1) // (60 * 24))


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def cmd_list(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = init_engine(settings.database_url.get_secret_value())
    session_factory = init_session_factory(engine)

    async with session_factory() as session:
        rows = await list_dlq_jobs(
            session,
            function=args.function,
            include_replayed=args.include_replayed,
            max_age_hours=args.hours,
            limit=args.limit,
        )
    _print_table(rows)
    print(f"\n{len(rows)} row(s).")
    return 0


async def cmd_show(args: argparse.Namespace) -> int:
    try:
        dlq_id = uuid_module.UUID(args.id)
    except ValueError:
        print(f"Not a valid UUID: {args.id}", file=sys.stderr)
        return 2

    settings = get_settings()
    engine = init_engine(settings.database_url.get_secret_value())
    session_factory = init_session_factory(engine)

    async with session_factory() as session:
        row = await get_dlq_job_by_id(session, dlq_id)
    if row is None:
        print(f"No DLQ row with id {dlq_id}", file=sys.stderr)
        return 1
    print(json.dumps(_serialize_row(row), indent=2, default=str))
    return 0


async def cmd_replay(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = init_engine(settings.database_url.get_secret_value())
    session_factory = init_session_factory(engine)

    # Single-row mode
    if args.id:
        try:
            dlq_id = uuid_module.UUID(args.id)
        except ValueError:
            print(f"Not a valid UUID: {args.id}", file=sys.stderr)
            return 2

        async with session_factory() as session:
            row = await get_dlq_job_by_id(session, dlq_id)
            if row is None:
                print(f"No DLQ row with id {dlq_id}", file=sys.stderr)
                return 1
            if row.replayed_at is not None:
                print(
                    f"Row {dlq_id} was already replayed at {_fmt_dt(row.replayed_at)} "
                    f"(result={row.replay_result}).",
                    file=sys.stderr,
                )
                return 1
            try:
                result_str = await _replay_row(row)
            except Exception as exc:
                print(f"Replay failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 1
            await mark_replayed(
                session,
                dlq_id=row.id,
                replay_result=result_str,
            )
            await session.commit()
        print(f"Replayed {dlq_id}: {result_str}")
        return 0

    # Batch-by-function mode
    if not args.function:
        print("Must pass either <id> or --function <name>.", file=sys.stderr)
        return 2

    async with session_factory() as session:
        rows = await list_dlq_jobs(
            session,
            function=args.function,
            include_replayed=False,
            limit=args.limit,
        )

    if not rows:
        print(f"No unreplayed DLQ rows for function '{args.function}'.")
        return 0

    if not args.yes and not _confirm_batch(len(rows), args.function):
        print("Aborted.")
        return 1

    replayed = 0
    failed = 0
    async with session_factory() as session:
        for row in rows:
            # Re-fetch in this session to mark_replayed cleanly.
            fresh = await get_dlq_job_by_id(session, row.id)
            if fresh is None or fresh.replayed_at is not None:
                continue
            try:
                result_str = await _replay_row(fresh)
            except Exception as exc:
                failed += 1
                logger.warning(
                    "dlq_replay_batch_row_failed",
                    dlq_id=str(fresh.id),
                    error=str(exc),
                )
                continue
            await mark_replayed(
                session,
                dlq_id=fresh.id,
                replay_result=result_str,
            )
            replayed += 1
        await session.commit()
    print(f"Replayed {replayed} row(s); {failed} failed.")
    return 0 if failed == 0 else 1


async def cmd_prune(args: argparse.Namespace) -> int:
    days = _parse_age_to_days(args.older_than)
    settings = get_settings()
    engine = init_engine(settings.database_url.get_secret_value())
    session_factory = init_session_factory(engine)

    async with session_factory() as session:
        removed = await delete_replayed_older_than(session, days=days)
        await session.commit()
    print(f"Pruned {removed} replayed DLQ row(s) older than {days}d.")
    return 0


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dlq_replay",
        description="Inspect and replay ARQ dead-letter jobs.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List DLQ rows.")
    p_list.add_argument("--function", type=str, default=None)
    p_list.add_argument("--hours", type=int, default=None, help="Only rows failed within N hours.")
    p_list.add_argument("--include-replayed", action="store_true")
    p_list.add_argument("--limit", type=int, default=100)
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Dump one DLQ row (including kwargs + traceback).")
    p_show.add_argument("id", type=str)
    p_show.set_defaults(func=cmd_show)

    p_replay = sub.add_parser("replay", help="Re-enqueue a DLQ row (or all rows for a function).")
    p_replay.add_argument("id", type=str, nargs="?", default=None)
    p_replay.add_argument("--function", type=str, default=None)
    p_replay.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt for --function batch replays.",
    )
    p_replay.add_argument("--limit", type=int, default=500)
    p_replay.set_defaults(func=cmd_replay)

    p_prune = sub.add_parser("prune", help="Delete replayed DLQ rows older than a cutoff.")
    p_prune.add_argument("--older-than", type=str, required=True, help="e.g. 30d, 72h, 1440m")
    p_prune.set_defaults(func=cmd_prune)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
