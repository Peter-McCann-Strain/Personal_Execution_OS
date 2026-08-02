"""Ownership, lifecycle, and failure tests for web-push subscriptions."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.persistence.models import WebPushSubscription
from src.app.persistence.repositories.web_push_subscriptions import (
    _endpoint_hash,
    count_active_web_push_subscriptions,
    get_web_push_subscription,
    list_web_push_subscriptions,
    mark_web_push_subscription_failure,
    mark_web_push_subscription_success,
    revoke_web_push_subscription,
    upsert_web_push_subscription,
)


class _Scalars:
    def __init__(self, rows: list[object] | None = None) -> None:
        self._rows = list(rows or [])

    def all(self) -> list[object]:
        return list(self._rows)


class _Result:
    def __init__(
        self,
        *,
        one_or_none: object | None = None,
        one: object | None = None,
        rows: list[object] | None = None,
    ) -> None:
        self._one_or_none = one_or_none
        self._one = one
        self._rows = list(rows or [])

    def scalar_one_or_none(self) -> object | None:
        return self._one_or_none

    def scalar_one(self) -> object | None:
        return self._one

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


def _session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.get = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(rows=[]))
    return session


def _subscription(**overrides: object) -> WebPushSubscription:
    record = WebPushSubscription()
    record.id = overrides.get("id", uuid.uuid4())
    record.user_id = overrides.get("user_id", "owner")
    record.endpoint = overrides.get("endpoint", "https://push.example/one")
    record.endpoint_hash = overrides.get(
        "endpoint_hash",
        _endpoint_hash(record.endpoint),
    )
    record.auth_key = overrides.get("auth_key", "auth")
    record.p256dh_key = overrides.get("p256dh_key", "p256dh")
    record.expiration_time = overrides.get("expiration_time")
    record.user_agent = overrides.get("user_agent", "Browser")
    record.status = overrides.get("status", "active")
    record.failure_count = overrides.get("failure_count", 0)
    record.last_seen_at = overrides.get("last_seen_at")
    record.last_success_at = overrides.get("last_success_at")
    record.last_failure_at = overrides.get("last_failure_at")
    record.last_error = overrides.get("last_error")
    record.metadata_ = overrides.get("metadata", {})
    record.deleted_at = overrides.get("deleted_at")
    record.created_at = overrides.get("created_at", datetime(2026, 8, 1, tzinfo=UTC))
    record.updated_at = overrides.get("updated_at", datetime(2026, 8, 1, tzinfo=UTC))
    return record


def test_endpoint_hash_is_trimmed_and_deterministic() -> None:
    expected = hashlib.sha256(b"https://push.example/one").hexdigest()
    assert _endpoint_hash(" https://push.example/one ") == expected


@pytest.mark.asyncio
async def test_list_and_get_are_owner_scoped_with_revoked_control() -> None:
    session = _session()
    record = _subscription()
    session.execute.side_effect = [
        _Result(rows=[record]),
        _Result(rows=[]),
        _Result(one_or_none=record),
        _Result(one_or_none=None),
    ]

    assert await list_web_push_subscriptions(
        session,
        user_id="owner",
    ) == [record]
    assert (
        await list_web_push_subscriptions(
            session,
            user_id="owner",
            include_revoked=True,
        )
        == []
    )
    assert (
        await get_web_push_subscription(
            session,
            subscription_id=record.id,
            user_id="owner",
        )
        is record
    )
    assert (
        await get_web_push_subscription(
            session,
            subscription_id=record.id,
            user_id="other",
        )
        is None
    )

    default_list_sql = str(session.execute.await_args_list[0].args[0])
    inclusive_list_sql = str(session.execute.await_args_list[1].args[0])
    get_sql = str(session.execute.await_args_list[2].args[0])
    assert "web_push_subscriptions.user_id" in default_list_sql
    assert "web_push_subscriptions.status !=" in default_list_sql
    assert "web_push_subscriptions.status !=" not in inclusive_list_sql
    assert "web_push_subscriptions.user_id" in get_sql
    assert "web_push_subscriptions.deleted_at IS NULL" in get_sql


@pytest.mark.asyncio
async def test_upsert_create_trims_endpoint_adds_and_flushes_without_commit() -> None:
    session = _session()
    session.execute.return_value = _Result(one_or_none=None)

    created = await upsert_web_push_subscription(
        session,
        user_id="owner",
        endpoint=" https://push.example/new ",
        auth_key="new-auth",
        p256dh_key="new-p256dh",
    )

    assert created.endpoint == "https://push.example/new"
    assert created.endpoint_hash == _endpoint_hash("https://push.example/new")
    assert created.metadata_ == {}
    assert created.failure_count == 0
    assert created.status == "active"
    session.add.assert_called_once_with(created)
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()
    assert "web_push_subscriptions.user_id" in str(session.execute.await_args.args[0])

    async_add_session = _session()
    async_add_session.add = AsyncMock()
    async_add_session.execute.return_value = _Result(one_or_none=None)
    second = await upsert_web_push_subscription(
        async_add_session,
        user_id="owner",
        endpoint="https://push.example/two",
        auth_key="auth",
        p256dh_key="key",
        metadata={"device": "phone"},
    )
    async_add_session.add.assert_awaited_once_with(second)
    assert second.metadata_ == {"device": "phone"}


@pytest.mark.asyncio
async def test_upsert_existing_reactivates_and_clears_prior_failure() -> None:
    session = _session()
    existing = _subscription(
        status="revoked",
        failure_count=3,
        last_error="gone",
        deleted_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    session.execute.return_value = _Result(one_or_none=existing)
    expiration = datetime(2027, 1, 1, tzinfo=UTC)

    result = await upsert_web_push_subscription(
        session,
        user_id="owner",
        endpoint=" https://push.example/one ",
        auth_key="replacement-auth",
        p256dh_key="replacement-key",
        expiration_time=expiration,
        user_agent="New browser",
        metadata={"device": "desktop"},
    )

    assert result is existing
    assert result.status == "active"
    assert result.deleted_at is None
    assert result.failure_count == 0
    assert result.last_error is None
    assert result.auth_key == "replacement-auth"
    assert result.p256dh_key == "replacement-key"
    assert result.expiration_time == expiration
    assert result.user_agent == "New browser"
    assert result.metadata_ == {"device": "desktop"}
    session.add.assert_not_called()
    session.flush.assert_awaited_once()

    existing.failure_count = 0
    existing.last_error = "preserved when no failures"
    await upsert_web_push_subscription(
        session,
        user_id="owner",
        endpoint=existing.endpoint,
        auth_key="auth",
        p256dh_key="key",
    )
    assert existing.last_error == "preserved when no failures"


@pytest.mark.asyncio
async def test_revoke_is_owner_checked_and_preserves_history() -> None:
    session = _session()
    record = _subscription()
    with patch(
        "src.app.persistence.repositories.web_push_subscriptions.get_web_push_subscription",
        new=AsyncMock(side_effect=[None, record]),
    ):
        assert (
            await revoke_web_push_subscription(
                session,
                subscription_id=record.id,
                user_id="wrong-owner",
            )
            is False
        )
        assert (
            await revoke_web_push_subscription(
                session,
                subscription_id=record.id,
                user_id="owner",
            )
            is True
        )

    assert record.status == "revoked"
    assert record.deleted_at is not None
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delivery_success_handles_missing_and_resets_error_state() -> None:
    session = _session()
    record = _subscription(status="error", failure_count=2, last_error="timeout")
    session.get.side_effect = [None, record]

    await mark_web_push_subscription_success(
        session,
        subscription_id=uuid.uuid4(),
    )
    session.flush.assert_not_awaited()

    await mark_web_push_subscription_success(
        session,
        subscription_id=record.id,
    )
    assert record.status == "active"
    assert record.failure_count == 0
    assert record.last_error is None
    assert record.last_success_at is not None
    assert record.last_seen_at == record.last_success_at
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delivery_failure_covers_error_revoke_missing_and_truncation() -> None:
    session = _session()
    error_record = _subscription(failure_count=None)
    revoked_record = _subscription(failure_count=4)
    session.get.side_effect = [None, error_record, revoked_record]

    await mark_web_push_subscription_failure(
        session,
        subscription_id=uuid.uuid4(),
        error_message="missing",
    )
    await mark_web_push_subscription_failure(
        session,
        subscription_id=error_record.id,
        error_message="x" * 700,
    )
    await mark_web_push_subscription_failure(
        session,
        subscription_id=revoked_record.id,
        error_message="subscription expired",
        revoke=True,
    )

    assert error_record.status == "error"
    assert error_record.failure_count == 1
    assert len(error_record.last_error) == 500
    assert revoked_record.status == "revoked"
    assert revoked_record.failure_count == 5
    assert revoked_record.deleted_at is not None
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_active_count_normalizes_empty_and_positive_results() -> None:
    session = _session()
    session.execute.side_effect = [_Result(one=None), _Result(one=3)]

    assert await count_active_web_push_subscriptions(session, user_id="owner") == 0
    assert await count_active_web_push_subscriptions(session, user_id="owner") == 3
    assert "web_push_subscriptions.user_id" in str(session.execute.await_args_list[0].args[0])


@pytest.mark.asyncio
async def test_flush_failure_propagates_without_committing() -> None:
    session = _session()
    session.execute.return_value = _Result(one_or_none=None)
    session.flush.side_effect = RuntimeError("constraint failure")

    with pytest.raises(RuntimeError, match="constraint failure"):
        await upsert_web_push_subscription(
            session,
            user_id="owner",
            endpoint="https://push.example/fail",
            auth_key="auth",
            p256dh_key="key",
        )

    session.commit.assert_not_awaited()
