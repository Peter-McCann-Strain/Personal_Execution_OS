"""Risk-focused tests for scheduled-action persistence and recurrence rules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.persistence.models import ScheduledAction, ScheduledActionRun
from src.app.persistence.repositories.scheduled_actions import (
    _coerce_int,
    _coerce_weekday,
    _tz,
    compute_next_run_at,
    create_scheduled_action,
    create_scheduled_action_run,
    get_scheduled_action,
    list_due_scheduled_actions,
    list_scheduled_action_runs,
    list_scheduled_actions,
    mark_scheduled_action_executed,
    soft_delete_scheduled_action,
    update_scheduled_action,
    update_scheduled_action_run,
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


def _action(**overrides: object) -> ScheduledAction:
    action = ScheduledAction()
    action.id = overrides.get("id", uuid.uuid4())
    action.user_id = overrides.get("user_id", "owner")
    action.title = overrides.get("title", "Morning review")
    action.prompt = overrides.get("prompt", "Review the day")
    action.schedule_type = overrides.get("schedule_type", "daily")
    action.schedule_config = overrides.get("schedule_config", {"hour": 9})
    action.timezone = overrides.get("timezone", "UTC")
    action.status = overrides.get("status", "active")
    action.delivery_channel = overrides.get("delivery_channel", "web")
    action.next_run_at = overrides.get("next_run_at")
    action.last_run_at = overrides.get("last_run_at")
    action.last_result_summary = overrides.get("last_result_summary")
    action.metadata_ = overrides.get("metadata", {})
    action.deleted_at = overrides.get("deleted_at")
    action.created_at = overrides.get("created_at", datetime(2026, 8, 1, tzinfo=UTC))
    action.updated_at = overrides.get("updated_at", datetime(2026, 8, 1, tzinfo=UTC))
    return action


def _run(**overrides: object) -> ScheduledActionRun:
    run = ScheduledActionRun()
    run.id = overrides.get("id", uuid.uuid4())
    run.action_id = overrides.get("action_id", uuid.uuid4())
    run.workflow_id = overrides.get("workflow_id")
    run.status = overrides.get("status", "queued")
    run.result_summary = overrides.get("result_summary")
    run.error_message = overrides.get("error_message")
    run.payload = overrides.get("payload", {})
    run.completed_at = overrides.get("completed_at")
    return run


def test_recurrence_coercion_is_bounded_and_timezone_falls_back() -> None:
    assert _tz("Europe/London").key == "Europe/London"
    assert _tz("not/a-zone").key == "UTC"

    assert _coerce_weekday(-3) == 0
    assert _coerce_weekday(9) == 6
    assert _coerce_weekday(" Friday ") == 4
    assert _coerce_weekday("12") == 6
    assert _coerce_weekday("invalid") == 0
    assert _coerce_weekday(None) == 0

    assert _coerce_int(True, 9, minimum=0, maximum=23) == 9
    assert _coerce_int(-2, 9, minimum=0, maximum=23) == 0
    assert _coerce_int(99.9, 9, minimum=0, maximum=23) == 23
    assert _coerce_int(" 07 ", 9, minimum=0, maximum=23) == 7
    assert _coerce_int("bad", 9, minimum=0, maximum=23) == 9


def test_compute_next_run_covers_once_daily_weekly_monthly_and_unknown() -> None:
    now = datetime(2026, 12, 31, 10, 30, tzinfo=UTC)

    assert compute_next_run_at(
        schedule_type="once",
        schedule_config={"run_at": "2027-01-02T08:00:00+00:00"},
        timezone="UTC",
        now=now,
    ) == datetime(2027, 1, 2, 8, tzinfo=UTC)
    assert compute_next_run_at(
        schedule_type="once",
        schedule_config={"run_at": "2027-01-02T08:00:00"},
        timezone="UTC",
        now=now,
    ) == datetime(2027, 1, 2, 8, tzinfo=UTC)
    assert (
        compute_next_run_at(
            schedule_type="once",
            schedule_config={},
            timezone="UTC",
            now=now,
        )
        is None
    )

    assert compute_next_run_at(
        schedule_type="daily",
        schedule_config={"hour": 11, "minute": 0},
        timezone="UTC",
        now=now,
    ) == datetime(2026, 12, 31, 11, tzinfo=UTC)
    assert compute_next_run_at(
        schedule_type="daily",
        schedule_config={"hour": 10, "minute": 0},
        timezone="UTC",
        now=now,
    ) == datetime(2027, 1, 1, 10, tzinfo=UTC)
    assert compute_next_run_at(
        schedule_type="weekly",
        schedule_config={"weekday": "thursday", "hour": 9},
        timezone="UTC",
        now=now,
    ) == datetime(2027, 1, 7, 9, tzinfo=UTC)
    assert compute_next_run_at(
        schedule_type="weekly",
        schedule_config={"weekday": 4, "hour": 9},
        timezone="UTC",
        now=now,
    ) == datetime(2027, 1, 1, 9, tzinfo=UTC)
    assert compute_next_run_at(
        schedule_type="monthly",
        schedule_config={"day": 31, "hour": 9},
        timezone="UTC",
        now=now,
    ) == datetime(2027, 1, 31, 9, tzinfo=UTC)
    assert compute_next_run_at(
        schedule_type="monthly",
        schedule_config={"day": 31, "hour": 9},
        timezone="UTC",
        now=datetime(2027, 2, 1, tzinfo=UTC),
    ) == datetime(2027, 2, 28, 9, tzinfo=UTC)
    assert (
        compute_next_run_at(
            schedule_type="unsupported",
            schedule_config=None,
            timezone="invalid",
            now=now,
        )
        is None
    )


@pytest.mark.asyncio
async def test_create_actions_flush_without_committing_and_cover_add_variants() -> None:
    session = _session()
    active = await create_scheduled_action(
        session,
        user_id="owner",
        title="Daily review",
        prompt="Review",
        schedule_type="daily",
        schedule_config={"hour": 8},
        timezone="UTC",
        metadata={"source": "manual"},
    )
    assert active.next_run_at is not None
    assert active.metadata_ == {"source": "manual"}
    session.add.assert_called_once_with(active)
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()

    async_add_session = _session()
    async_add_session.add = AsyncMock()
    paused = await create_scheduled_action(
        async_add_session,
        user_id="owner",
        title="Paused",
        prompt="Wait",
        schedule_type="daily",
        schedule_config=None,
        timezone="UTC",
        status="paused",
    )
    assert paused.next_run_at is None
    assert paused.schedule_config == {}
    async_add_session.add.assert_awaited_once_with(paused)


@pytest.mark.asyncio
async def test_get_and_list_are_owner_scoped_and_preserve_empty_results() -> None:
    session = _session()
    action_id = uuid.uuid4()
    action = _action(id=action_id)
    session.execute.side_effect = [
        _Result(one_or_none=action),
        _Result(one=1),
        _Result(rows=[action]),
        _Result(one=0),
        _Result(rows=[]),
    ]

    assert await get_scheduled_action(session, action_id=action_id, user_id="owner") is action
    rows, total = await list_scheduled_actions(
        session,
        user_id="owner",
        status="active",
        limit=10,
        offset=2,
    )
    assert rows == [action]
    assert total == 1
    empty, empty_total = await list_scheduled_actions(session, user_id="other")
    assert empty == []
    assert empty_total == 0

    get_sql = str(session.execute.await_args_list[0].args[0])
    list_sql = str(session.execute.await_args_list[1].args[0])
    assert "scheduled_actions.user_id" in get_sql
    assert "scheduled_actions.deleted_at IS NULL" in get_sql
    assert "scheduled_actions.user_id" in list_sql
    assert "scheduled_actions.status" in list_sql


@pytest.mark.asyncio
async def test_update_and_delete_respect_missing_owner_and_flush_mutations() -> None:
    session = _session()
    action = _action()
    with patch(
        "src.app.persistence.repositories.scheduled_actions.get_scheduled_action",
        new=AsyncMock(side_effect=[None, action, None, action]),
    ):
        assert (
            await update_scheduled_action(
                session,
                action_id=uuid.uuid4(),
                user_id="wrong-owner",
                title="Forbidden",
            )
            is None
        )
        updated = await update_scheduled_action(
            session,
            action_id=action.id,
            user_id="owner",
            title="Updated",
            prompt="Updated prompt",
            schedule_type="weekly",
            schedule_config={"weekday": "monday"},
            timezone="Europe/London",
            status="paused",
            delivery_channel="email",
            metadata={"updated": True},
        )
        assert updated is action
        assert action.title == "Updated"
        assert action.prompt == "Updated prompt"
        assert action.schedule_type == "weekly"
        assert action.schedule_config == {"weekday": "monday"}
        assert action.timezone == "Europe/London"
        assert action.status == "paused"
        assert action.delivery_channel == "email"
        assert action.metadata_ == {"updated": True}
        assert action.next_run_at is None

        assert (
            await soft_delete_scheduled_action(
                session,
                action_id=uuid.uuid4(),
                user_id="wrong-owner",
            )
            is False
        )
        assert (
            await soft_delete_scheduled_action(
                session,
                action_id=action.id,
                user_id="owner",
            )
            is True
        )

    assert action.deleted_at is not None
    assert session.flush.await_count == 2
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_partial_update_recomputes_next_run() -> None:
    session = _session()
    action = _action(status="active")
    with patch(
        "src.app.persistence.repositories.scheduled_actions.get_scheduled_action",
        new=AsyncMock(return_value=action),
    ):
        result = await update_scheduled_action(
            session,
            action_id=action.id,
            user_id="owner",
        )
    assert result is action
    assert action.next_run_at is not None


@pytest.mark.asyncio
async def test_run_records_cover_create_update_empty_and_terminal_states() -> None:
    session = _session()
    created = await create_scheduled_action_run(
        session,
        action_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        status="running",
        payload={"attempt": 1},
    )
    assert created.status == "running"
    assert created.payload == {"attempt": 1}

    async_add_session = _session()
    async_add_session.add = AsyncMock()
    defaulted = await create_scheduled_action_run(
        async_add_session,
        action_id=uuid.uuid4(),
    )
    assert defaulted.payload == {}
    async_add_session.add.assert_awaited_once()

    session.get.side_effect = [None, created, created]
    assert (
        await update_scheduled_action_run(
            session,
            run_id=uuid.uuid4(),
            status="failed",
        )
        is None
    )
    completed = await update_scheduled_action_run(
        session,
        run_id=created.id,
        status="completed",
        result_summary="Done",
        error_message="old error",
        payload={"result": True},
    )
    assert completed is created
    assert created.completed_at is not None
    assert created.result_summary == "Done"
    assert created.error_message == "old error"
    assert created.payload == {"result": True}

    created.completed_at = None
    running = await update_scheduled_action_run(
        session,
        run_id=created.id,
        status="running",
    )
    assert running is created
    assert created.completed_at is None


@pytest.mark.asyncio
async def test_run_and_due_lists_cover_filters_defaults_and_empty_results() -> None:
    session = _session()
    action = _action()
    run = _run(action_id=action.id)
    session.execute.side_effect = [
        _Result(rows=[run]),
        _Result(rows=[]),
        _Result(rows=[action]),
        _Result(rows=[]),
    ]

    assert await list_scheduled_action_runs(
        session,
        user_id="owner",
        action_id=action.id,
        limit=4,
    ) == [run]
    assert await list_scheduled_action_runs(session, user_id="owner") == []
    assert await list_due_scheduled_actions(
        session,
        now=datetime(2026, 8, 2, tzinfo=UTC),
        limit=3,
    ) == [action]
    assert await list_due_scheduled_actions(session) == []

    runs_sql = str(session.execute.await_args_list[0].args[0])
    due_sql = str(session.execute.await_args_list[2].args[0])
    assert "scheduled_actions.user_id" in runs_sql
    assert "scheduled_action_runs.action_id" in runs_sql
    assert "scheduled_actions.status" in due_sql
    assert "scheduled_actions.deleted_at IS NULL" in due_sql


@pytest.mark.asyncio
async def test_mark_executed_archives_once_and_advances_recurring_without_commit() -> None:
    session = _session()
    now = datetime(2026, 8, 2, 12, tzinfo=UTC)
    once = _action(schedule_type="once")
    result_once = await mark_scheduled_action_executed(
        session,
        action=once,
        result_summary="Complete",
        now=now,
    )
    assert result_once.status == "archived"
    assert result_once.next_run_at is None
    assert result_once.last_run_at == now

    daily = _action(schedule_type="daily", schedule_config={"hour": 13})
    result_daily = await mark_scheduled_action_executed(
        session,
        action=daily,
        result_summary="Complete again",
    )
    assert result_daily.status == "active"
    assert result_daily.next_run_at is not None
    assert session.flush.await_count == 2
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_flush_failure_propagates_without_hidden_commit() -> None:
    session = _session()
    session.flush.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        await create_scheduled_action(
            session,
            user_id="owner",
            title="Will fail",
            prompt="Fail",
            schedule_type="daily",
            schedule_config={},
            timezone="UTC",
        )

    session.commit.assert_not_awaited()
