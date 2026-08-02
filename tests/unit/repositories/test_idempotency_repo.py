"""Concurrency and response-cache tests for HTTP idempotency persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from src.app.persistence.models import IdempotencyKey
from src.app.persistence.repositories.idempotency import (
    _as_json_safe,
    delete_expired,
    get_active_key,
    get_key,
    insert_started,
    mark_completed,
    mark_failed,
    reset_started,
)


class _Result:
    def __init__(
        self,
        *,
        one_or_none: object | None = None,
        rowcount: int | None = None,
    ) -> None:
        self._one_or_none = one_or_none
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> object | None:
        return self._one_or_none


def _session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock(return_value=_Result())
    return session


def _key(**overrides: object) -> IdempotencyKey:
    record = IdempotencyKey()
    record.key = overrides.get("key", "idem-1")
    record.request_fingerprint = overrides.get("request_fingerprint", "fingerprint-1")
    record.recovery_point = overrides.get("recovery_point", "completed")
    record.response_status = overrides.get("response_status", 200)
    record.response_body = overrides.get("response_body", {"ok": True})
    record.response_headers = overrides.get("response_headers", {"x-test": "one"})
    record.method = overrides.get("method", "POST")
    record.route = overrides.get("route", "/api/projects")
    record.created_at = overrides.get(
        "created_at",
        datetime(2026, 8, 1, tzinfo=UTC),
    )
    record.expires_at = overrides.get(
        "expires_at",
        datetime(2026, 8, 2, tzinfo=UTC),
    )
    return record


@pytest.mark.asyncio
async def test_get_active_key_filters_exact_key_and_expiry_with_empty_path() -> None:
    session = _session()
    record = _key()
    session.execute.side_effect = [
        _Result(one_or_none=record),
        _Result(one_or_none=None),
    ]

    assert await get_active_key(session, key="idem-1") is record
    assert await get_active_key(session, key="missing") is None

    sql = str(session.execute.await_args_list[0].args[0])
    assert "idempotency_keys.key" in sql
    assert "idempotency_keys.expires_at >" in sql
    assert "LIMIT" in sql


@pytest.mark.asyncio
async def test_get_key_covers_locking_and_nonlocking_dedupe_reads() -> None:
    session = _session()
    record = _key()
    session.execute.side_effect = [
        _Result(one_or_none=record),
        _Result(one_or_none=None),
    ]

    assert await get_key(session, key="idem-1") is record
    assert await get_key(session, key="idem-1", for_update=True) is None

    unlocked_sql = str(session.execute.await_args_list[0].args[0])
    locked_sql = str(session.execute.await_args_list[1].args[0])
    assert "FOR UPDATE" not in unlocked_sql
    assert "FOR UPDATE" in locked_sql
    assert "idempotency_keys.key" in locked_sql


@pytest.mark.asyncio
async def test_reset_started_clears_cached_response_and_refreshes_identity() -> None:
    session = _session()
    record = _key()
    before = datetime.now(UTC)

    reset = await reset_started(
        session,
        record=record,
        request_fingerprint="fingerprint-2",
        method="PATCH",
        route="/api/projects/one",
    )

    assert reset is record
    assert record.request_fingerprint == "fingerprint-2"
    assert record.recovery_point == "started"
    assert record.response_status is None
    assert record.response_body is None
    assert record.response_headers is None
    assert record.method == "PATCH"
    assert record.route == "/api/projects/one"
    assert record.created_at >= before
    assert record.expires_at == record.created_at + timedelta(hours=24)
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_insert_started_flushes_before_return_without_committing() -> None:
    session = _session()

    created = await insert_started(
        session,
        key="idem-new",
        request_fingerprint="fingerprint-new",
        method="POST",
        route="/api/notes",
    )

    assert created.key == "idem-new"
    assert created.request_fingerprint == "fingerprint-new"
    assert created.recovery_point == "started"
    assert created.method == "POST"
    assert created.route == "/api/notes"
    session.add.assert_called_once_with(created)
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_duplicate_insert_surfaces_integrity_error_for_caller_retry() -> None:
    session = _session()
    session.flush.side_effect = IntegrityError(
        "INSERT INTO idempotency_keys",
        {"key": "same-key"},
        RuntimeError("unique violation"),
    )

    with pytest.raises(IntegrityError):
        await insert_started(
            session,
            key="same-key",
            request_fingerprint="fingerprint",
            method="POST",
            route="/api/notes",
        )

    session.add.assert_called_once()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_completed_handles_missing_key_json_body_and_header_copy() -> None:
    session = _session()
    record = _key()
    headers = {"etag": "one"}
    with patch(
        "src.app.persistence.repositories.idempotency.get_active_key",
        new=AsyncMock(side_effect=[None, record, record]),
    ):
        assert (
            await mark_completed(
                session,
                key="missing",
                response_status=404,
                response_body={"error": "missing"},
            )
            is None
        )
        completed = await mark_completed(
            session,
            key=record.key,
            response_status=201,
            response_body=b'{"created": true}',
            response_headers=headers,
        )
        assert completed is record
        assert record.recovery_point == "completed"
        assert record.response_status == 201
        assert record.response_body == {"created": True}
        assert record.response_headers == {"etag": "one"}
        assert record.response_headers is not headers

        without_headers = await mark_completed(
            session,
            key=record.key,
            response_status=204,
            response_body=None,
            response_headers={},
        )
        assert without_headers is record
        assert record.response_headers is None

    assert session.flush.await_count == 2
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_failed_handles_missing_and_existing_rows() -> None:
    session = _session()
    record = _key()
    with patch(
        "src.app.persistence.repositories.idempotency.get_active_key",
        new=AsyncMock(side_effect=[None, record]),
    ):
        assert await mark_failed(session, key="missing") is None
        assert await mark_failed(session, key=record.key) is record

    assert record.recovery_point == "failed"
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_expired_preserves_started_rows_and_normalizes_rowcount() -> None:
    session = _session()
    session.execute.side_effect = [
        _Result(rowcount=-1),
        _Result(rowcount=None),
        _Result(rowcount=4),
    ]

    assert await delete_expired(session) == 0
    assert await delete_expired(session) == 0
    assert await delete_expired(session) == 4

    sql = str(session.execute.await_args_list[0].args[0])
    assert "DELETE FROM idempotency_keys" in sql
    assert "idempotency_keys.expires_at <" in sql
    assert "idempotency_keys.recovery_point !=" in sql
    session.commit.assert_not_awaited()


def test_json_safe_preserves_json_and_handles_invalid_bytes_without_raising() -> None:
    payload = {"already": ["json", 1, True]}
    assert _as_json_safe(payload) is payload
    assert _as_json_safe(bytearray(b"[1, 2]")) == [1, 2]
    assert _as_json_safe(b"not-json") == {"__raw__": "not-json"}
    assert _as_json_safe(b"\xffsecret") == {"__raw__": "\ufffdsecret"}


@pytest.mark.asyncio
async def test_mark_completed_flush_failure_propagates_without_commit() -> None:
    session = _session()
    session.flush.side_effect = RuntimeError("write unavailable")
    with (
        patch(
            "src.app.persistence.repositories.idempotency.get_active_key",
            new=AsyncMock(return_value=_key()),
        ),
        pytest.raises(RuntimeError, match="write unavailable"),
    ):
        await mark_completed(
            session,
            key="idem-1",
            response_status=200,
            response_body={"ok": True},
        )

    session.commit.assert_not_awaited()
