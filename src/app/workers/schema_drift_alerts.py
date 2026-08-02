"""Schema-drift alerts — surface ORM/database divergence to Telegram.

When the SQLAlchemy ORM expects a column or table that does not exist in the
live database (typically because an Alembic migration was authored but never
applied to a particular environment) the runtime emits very high-volume
``asyncpg.exceptions.UndefinedColumnError`` / ``UndefinedTableError`` /
``sqlalchemy.exc.ProgrammingError`` warnings. A single missing column can
fire 60+ times per runtime_stream tick, drowning real signal.

This worker scans a structured-log source for those exceptions over the past
24 hours and, if at least :pyattr:`Settings.schema_drift_alert_threshold`
occurrences have been recorded, sends a single distinct Telegram alert per
``(table, column)`` pair so the operator can run the corresponding
``alembic upgrade``.

Log-source contract:
    The checked-in adapter reads a JSON-lines structlog file configured through
    ``SCHEMA_DRIFT_ALERT_LOG_PATH``. The default Compose stack writes container
    logs through Docker's logging driver instead of mounting such a file, so
    this alert remains a no-op unless an operator deliberately supplies one.
    A future Loki, journald, or Sentry adapter must preserve the same contract:

      * read structlog JSON records since ``cutoff``
      * yield :class:`SchemaDriftHit` for any record whose ``exception`` /
        ``event`` field matches one of the patterns in
        :data:`SCHEMA_DRIFT_PATTERNS`.

    Replace :func:`scan_log_source` with the real adapter when the log
    pipeline lands; the rest of the worker (rate limiting, alert formatting,
    Telegram dispatch) is already production-shaped.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

import structlog
from aiogram import Bot

from src.app.config import Settings
from src.app.workers.github_filer import AlertRecord, file_github_issue

logger = structlog.get_logger()


SCHEMA_DRIFT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"asyncpg\.exceptions\.UndefinedColumnError"),
    re.compile(r"asyncpg\.exceptions\.UndefinedTableError"),
    re.compile(r"sqlalchemy\.exc\.ProgrammingError.*does not exist", re.DOTALL),
)

# Captures `<table>.<column>` and the bare `column "<column>"` / `relation
# "<table>"` flavours produced by asyncpg / Postgres. Best-effort: if no group
# matches we fall back to "unknown".
_COLUMN_RE: Final[re.Pattern[str]] = re.compile(
    r'column\s+"?(?P<table>[a-zA-Z_][a-zA-Z0-9_]*)\.'
    r'(?P<column>[a-zA-Z_][a-zA-Z0-9_]*)"?\s+does not exist'
)
_BARE_COLUMN_RE: Final[re.Pattern[str]] = re.compile(
    r'column\s+"(?P<column>[a-zA-Z_][a-zA-Z0-9_]*)"\s+does not exist'
)
_RELATION_RE: Final[re.Pattern[str]] = re.compile(
    r'relation\s+"(?P<table>[a-zA-Z_][a-zA-Z0-9_]*)"\s+does not exist'
)


@dataclass(frozen=True)
class SchemaDriftHit:
    """A single log occurrence indicating schema drift."""

    timestamp: datetime
    table: str
    column: str
    raw: str


@dataclass
class _Bucket:
    """Aggregate count + sample message for a (table, column) drift fingerprint."""

    count: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    sample: str = ""
    samples: list[str] = field(default_factory=list)


def _parse_hit(timestamp: datetime, raw: str) -> SchemaDriftHit | None:
    """Extract `(table, column)` from a structlog record's exception text."""
    if not any(pattern.search(raw) for pattern in SCHEMA_DRIFT_PATTERNS):
        return None

    match = _COLUMN_RE.search(raw)
    if match:
        return SchemaDriftHit(
            timestamp=timestamp,
            table=match.group("table"),
            column=match.group("column"),
            raw=raw,
        )

    column_match = _BARE_COLUMN_RE.search(raw)
    table_match = _RELATION_RE.search(raw)
    return SchemaDriftHit(
        timestamp=timestamp,
        table=table_match.group("table") if table_match else "unknown",
        column=column_match.group("column") if column_match else "unknown",
        raw=raw,
    )


def scan_log_source(
    cutoff: datetime,
    *,
    settings: Settings,
) -> Iterator[SchemaDriftHit]:
    """Yield schema-drift log records since ``cutoff`` from the configured file."""
    log_path = getattr(settings, "schema_drift_alert_log_path", None)
    if not log_path:
        logger.debug(
            "schema_drift_alerts_no_log_source",
            hint="Set Settings.schema_drift_alert_log_path or replace scan_log_source",
        )
        return iter(())

    return _scan_jsonl_log(log_path, cutoff)


def _parse_record_timestamp(ts_raw: object) -> datetime:
    """Parse a structlog record timestamp; fall back to ``now`` on failure."""
    if not isinstance(ts_raw, str):
        return datetime.now(UTC)
    candidate = ts_raw[:-1] + "+00:00" if ts_raw.endswith("Z") else ts_raw
    try:
        ts = datetime.fromisoformat(candidate)
    except ValueError:
        return datetime.now(UTC)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts


def _scan_jsonl_log(log_path: str, cutoff: datetime) -> Iterator[SchemaDriftHit]:
    """Scan a JSON-lines structlog file for schema-drift exceptions.

    Tolerates records without timestamps (assumed recent) and malformed lines.
    Kept narrow on purpose: the production source-of-truth will likely be a
    log-aggregator query, not a flat file.
    """
    import json
    from pathlib import Path

    path = Path(log_path)
    if not path.exists():
        logger.warning("schema_drift_alerts_log_missing", log_path=log_path)
        return

    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts_raw = record.get("timestamp") or record.get("time")
                ts = _parse_record_timestamp(ts_raw)
                if ts < cutoff:
                    continue

                raw = " ".join(
                    str(record.get(k, ""))
                    for k in ("event", "exception", "exc_info", "message", "error")
                )
                hit = _parse_hit(ts, raw)
                if hit is not None:
                    yield hit
    except OSError:
        logger.exception("schema_drift_alerts_log_read_failed", log_path=log_path)


def aggregate_hits(hits: Iterable[SchemaDriftHit]) -> dict[tuple[str, str], _Bucket]:
    """Group hits by ``(table, column)`` fingerprint."""
    buckets: dict[tuple[str, str], _Bucket] = {}
    for hit in hits:
        key = (hit.table, hit.column)
        bucket = buckets.setdefault(key, _Bucket())
        bucket.count += 1
        if bucket.first_seen is None or hit.timestamp < bucket.first_seen:
            bucket.first_seen = hit.timestamp
        if bucket.last_seen is None or hit.timestamp > bucket.last_seen:
            bucket.last_seen = hit.timestamp
        if not bucket.sample:
            bucket.sample = hit.raw[:240]
        if len(bucket.samples) < 3:
            bucket.samples.append(hit.raw[:240])
    return buckets


def _format_alert(table: str, column: str, bucket: _Bucket, *, window_hours: int) -> str:
    first = bucket.first_seen.isoformat(timespec="seconds") if bucket.first_seen else "unknown"
    last = bucket.last_seen.isoformat(timespec="seconds") if bucket.last_seen else "unknown"
    return (
        f"Schema drift: {table}.{column} does not exist\n\n"
        f"{bucket.count} occurrence(s) in the last {window_hours}h\n"
        f"First seen: {first}\n"
        f"Last seen:  {last}\n\n"
        f"Sample: {bucket.sample}\n\n"
        "Run the matching `alembic upgrade head` to reconcile the schema."
    )


async def run_schema_drift_alerts(ctx: dict) -> None:
    """Cron entrypoint — scan logs and dispatch one Telegram alert per fingerprint."""
    settings: Settings = ctx["settings"]
    bot: Bot | None = ctx.get("bot")

    if not bool(getattr(settings, "schema_drift_alerts_enabled", True)):
        logger.info("schema_drift_alerts_disabled")
        return
    if bot is None:
        logger.warning(
            "schema_drift_alerts_no_bot",
            hint="Telegram not configured",
        )
        return

    user_ids = settings.allowed_user_ids
    if not user_ids:
        logger.warning("schema_drift_alerts_no_user_ids")
        return

    window_hours = int(getattr(settings, "schema_drift_alert_window_hours", 24))
    threshold = int(getattr(settings, "schema_drift_alert_threshold", 10))
    cutoff = datetime.now(UTC) - timedelta(hours=window_hours)

    hits = list(scan_log_source(cutoff, settings=settings))
    if not hits:
        logger.info(
            "schema_drift_alerts_none",
            window_hours=window_hours,
            threshold=threshold,
        )
        return

    buckets = aggregate_hits(hits)
    qualifying = sorted(
        ((key, bucket) for key, bucket in buckets.items() if bucket.count >= threshold),
        key=lambda item: item[1].count,
        reverse=True,
    )
    if not qualifying:
        logger.info(
            "schema_drift_alerts_below_threshold",
            window_hours=window_hours,
            threshold=threshold,
            unique_fingerprints=len(buckets),
        )
        return

    session_factory = ctx.get("session_factory")

    sent = 0
    for (table, column), bucket in qualifying:
        message = _format_alert(table, column, bucket, window_hours=window_hours)
        try:
            await bot.send_message(chat_id=user_ids[0], text=message)
            sent += 1
            logger.warning(
                "schema_drift_alert_sent",
                category="schema_drift",
                table=table,
                column=column,
                occurrences=bucket.count,
                window_hours=window_hours,
            )
        except Exception:
            logger.exception(
                "schema_drift_alert_send_failed",
                table=table,
                column=column,
            )
            raise

        # --- Secondary fan-out: GitHub issue (Phase 3.9) ------------------
        if session_factory is not None:
            try:
                alert = AlertRecord(
                    category="schema_drift",
                    title=f"Schema drift: {table}.{column} does not exist"[:120],
                    summary=(
                        f"{bucket.count} occurrence(s) of "
                        f"`{table}.{column}` not-existing in the last "
                        f"{window_hours}h. Run the matching "
                        "`alembic upgrade head` to reconcile."
                    ),
                    key_fields={"table": table, "column": column},
                    context={"Sample exception": bucket.sample},
                )
                await file_github_issue(
                    alert,
                    settings=settings,
                    session_factory=session_factory,
                )
            except Exception:
                logger.warning(
                    "schema_drift_alert_github_filer_failed",
                    table=table,
                    column=column,
                    exc_info=True,
                )

    logger.info(
        "schema_drift_alerts_done",
        sent=sent,
        considered=len(buckets),
    )
