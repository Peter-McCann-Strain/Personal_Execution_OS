"""Tests for schema-drift Telegram alert worker."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.app.workers import schema_drift_alerts
from src.app.workers.schema_drift_alerts import (
    SchemaDriftHit,
    _parse_hit,
    aggregate_hits,
    run_schema_drift_alerts,
)


def _make_settings(**overrides) -> SimpleNamespace:
    base = {
        "schema_drift_alerts_enabled": True,
        "schema_drift_alert_window_hours": 24,
        "schema_drift_alert_threshold": 10,
        "schema_drift_alert_log_path": "",
        "allowed_user_ids": [12345],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_parse_hit_extracts_table_and_column() -> None:
    raw = (
        "asyncpg.exceptions.UndefinedColumnError: column "
        "web_push_subscriptions.deleted_at does not exist"
    )
    hit = _parse_hit(datetime.now(UTC), raw)
    assert hit is not None
    assert hit.table == "web_push_subscriptions"
    assert hit.column == "deleted_at"


def test_parse_hit_falls_back_to_bare_column_and_relation() -> None:
    raw = (
        'sqlalchemy.exc.ProgrammingError: relation "ghost_table" does not exist '
        'and column "missing" does not exist'
    )
    hit = _parse_hit(datetime.now(UTC), raw)
    assert hit is not None
    assert hit.table == "ghost_table"
    assert hit.column == "missing"


def test_parse_hit_returns_none_for_unrelated_lines() -> None:
    assert _parse_hit(datetime.now(UTC), "ValueError: something else entirely") is None


def test_aggregate_hits_groups_by_fingerprint() -> None:
    now = datetime.now(UTC)
    hits = [
        SchemaDriftHit(now, "t", "c", "raw1"),
        SchemaDriftHit(now + timedelta(seconds=1), "t", "c", "raw2"),
        SchemaDriftHit(now, "other", "x", "raw3"),
    ]
    buckets = aggregate_hits(hits)
    assert set(buckets.keys()) == {("t", "c"), ("other", "x")}
    assert buckets[("t", "c")].count == 2
    assert buckets[("other", "x")].count == 1


@pytest.mark.asyncio
async def test_run_schema_drift_alerts_skips_without_bot() -> None:
    ctx = {"settings": _make_settings(), "bot": None}
    # Should not raise even without a session_factory because we never reach that code.
    await run_schema_drift_alerts(ctx)


@pytest.mark.asyncio
async def test_run_schema_drift_alerts_skips_when_disabled() -> None:
    bot = AsyncMock()
    ctx = {
        "settings": _make_settings(schema_drift_alerts_enabled=False),
        "bot": bot,
    }
    await run_schema_drift_alerts(ctx)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_schema_drift_alerts_below_threshold(monkeypatch) -> None:
    bot = AsyncMock()
    ctx = {
        "settings": _make_settings(schema_drift_alert_threshold=5),
        "bot": bot,
    }
    now = datetime.now(UTC)
    monkeypatch.setattr(
        schema_drift_alerts,
        "scan_log_source",
        lambda cutoff, *, settings: iter([SchemaDriftHit(now, "tbl", "col", "raw")]),
    )
    await run_schema_drift_alerts(ctx)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_schema_drift_alerts_fires_one_alert_per_fingerprint(
    monkeypatch,
) -> None:
    bot = AsyncMock()
    ctx = {
        "settings": _make_settings(schema_drift_alert_threshold=3),
        "bot": bot,
    }
    now = datetime.now(UTC)
    raw_missing = (
        "asyncpg.exceptions.UndefinedColumnError: column "
        "web_push_subscriptions.deleted_at does not exist"
    )
    raw_other = 'asyncpg.exceptions.UndefinedTableError: relation "ghost" does not exist'

    hits = [
        SchemaDriftHit(now, "web_push_subscriptions", "deleted_at", raw_missing),
        SchemaDriftHit(
            now + timedelta(seconds=1),
            "web_push_subscriptions",
            "deleted_at",
            raw_missing,
        ),
        SchemaDriftHit(
            now + timedelta(seconds=2),
            "web_push_subscriptions",
            "deleted_at",
            raw_missing,
        ),
        SchemaDriftHit(now, "ghost", "unknown", raw_other),  # below threshold
    ]
    monkeypatch.setattr(
        schema_drift_alerts,
        "scan_log_source",
        lambda cutoff, *, settings: iter(hits),
    )

    await run_schema_drift_alerts(ctx)

    assert bot.send_message.await_count == 1
    sent = bot.send_message.await_args.kwargs["text"]
    assert "Schema drift: web_push_subscriptions.deleted_at does not exist" in sent
    assert "3 occurrence(s)" in sent
    assert "alembic upgrade head" in sent


@pytest.mark.asyncio
async def test_scan_log_source_reads_jsonl_file(tmp_path) -> None:
    log_path = tmp_path / "app.jsonl"
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    recent_ts = datetime.now(UTC).isoformat()
    stale_ts = (datetime.now(UTC) - timedelta(hours=10)).isoformat()
    lines = [
        json.dumps(
            {
                "timestamp": recent_ts,
                "event": "asyncpg query failed",
                "exception": (
                    "asyncpg.exceptions.UndefinedColumnError: column "
                    "web_push_subscriptions.deleted_at does not exist"
                ),
            }
        ),
        json.dumps(
            {
                "timestamp": stale_ts,
                "exception": (
                    "asyncpg.exceptions.UndefinedColumnError: column foo.bar does not exist"
                ),
            }
        ),
        "not-json-at-all",
        json.dumps({"timestamp": recent_ts, "event": "unrelated info log"}),
    ]
    log_path.write_text("\n".join(lines), encoding="utf-8")

    settings = _make_settings(schema_drift_alert_log_path=str(log_path))
    found = list(schema_drift_alerts.scan_log_source(cutoff, settings=settings))
    assert len(found) == 1
    assert found[0].table == "web_push_subscriptions"
    assert found[0].column == "deleted_at"


@pytest.mark.asyncio
async def test_run_schema_drift_alerts_no_user_ids(monkeypatch) -> None:
    bot = AsyncMock()
    ctx = {
        "settings": _make_settings(allowed_user_ids=[]),
        "bot": bot,
    }
    await run_schema_drift_alerts(ctx)
    bot.send_message.assert_not_awaited()
