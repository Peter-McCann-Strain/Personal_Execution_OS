"""Focused unit coverage for daily planning state and artifacts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfoNotFoundError

import pytest

from src.app.domain.models import DayPlanArtifact, DayPlanTask, PendingPlanningSession
from src.app.domain.services import day_plans

NOW = datetime(2026, 4, 8, 10, 30, tzinfo=UTC)
SOURCE_DATE = "2026-04-08"


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "allowed_user_ids": [],
        "user_phone_number": "",
        "user_timezone": "UTC",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _task(
    title: str,
    *,
    status: str = "planned",
    rescheduled_for: str | None = None,
) -> DayPlanTask:
    return DayPlanTask(
        title=title,
        status=status,
        rescheduled_for=rescheduled_for,
    )


def _plan(
    *,
    source_date: str = SOURCE_DATE,
    tasks: list[DayPlanTask] | None = None,
    plan_summary: str = "",
) -> DayPlanArtifact:
    return DayPlanArtifact(
        source_date=source_date,
        plan_summary=plan_summary,
        tasks=tasks or [],
        updated_at=NOW,
    )


def _artifact(
    payload: object,
    *,
    artifact_id: object = "artifact-1",
    created_at: datetime | None = NOW,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=artifact_id,
        payload=payload,
        created_at=created_at,
    )


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        (_settings(allowed_user_ids=[123, 456], user_phone_number="+440000"), "123"),
        (_settings(user_phone_number="  +44 7700 900000  "), "+44 7700 900000"),
        (_settings(allowed_user_ids=("+1",), user_phone_number=123), "owner"),
        (SimpleNamespace(), "owner"),
    ],
)
def test_planning_owner_user_id_uses_supported_identity_fallbacks(
    settings: SimpleNamespace,
    expected: str,
) -> None:
    assert day_plans.planning_owner_user_id(settings) == expected


def test_planning_source_date_respects_local_midnight_and_default_timezone() -> None:
    just_after_utc_midnight = datetime(2026, 1, 1, 0, 30, tzinfo=UTC)

    assert (
        day_plans.planning_source_date(
            _settings(user_timezone="America/Los_Angeles"),
            now_utc=just_after_utc_midnight,
        )
        == "2025-12-31"
    )
    assert (
        day_plans.planning_source_date(
            _settings(user_timezone="  "),
            now_utc=just_after_utc_midnight,
        )
        == "2026-01-01"
    )
    assert (
        day_plans.planning_source_date(
            _settings(user_timezone=42),
            now_utc=just_after_utc_midnight,
        )
        == "2026-01-01"
    )


def test_planning_source_date_rejects_an_unknown_timezone() -> None:
    with pytest.raises(ZoneInfoNotFoundError):
        day_plans.planning_source_date(
            _settings(user_timezone="Mars/Olympus_Mons"),
            now_utc=NOW,
        )


def test_planning_session_activity_observes_missing_expired_and_local_day_boundaries() -> None:
    settings = _settings()
    active = PendingPlanningSession(
        session_type="morning_plan",
        source_date=SOURCE_DATE,
        expires_at=NOW + timedelta(minutes=1),
        last_active_at=NOW,
    )

    assert not day_plans.planning_session_is_active(None, settings=settings, now_utc=NOW)
    assert day_plans.planning_session_is_active(active, settings=settings, now_utc=NOW)
    assert not day_plans.planning_session_is_active(
        active.model_copy(update={"expires_at": NOW}),
        settings=settings,
        now_utc=NOW,
    )
    assert not day_plans.planning_session_is_active(
        active.model_copy(update={"source_date": "2026-04-07"}),
        settings=settings,
        now_utc=NOW,
    )


def test_session_builders_set_expected_stages_expiry_and_copy_mutable_inputs() -> None:
    settings = _settings()
    unresolved = ["Finish release notes"]

    morning = day_plans.build_morning_planning_session(settings=settings, now_utc=NOW)
    evening = day_plans.build_evening_review_session(
        settings=settings,
        plan_artifact_id="artifact-1",
        unresolved_tasks=unresolved,
        now_utc=NOW,
    )
    unresolved.append("Added after construction")

    assert morning.session_type == "morning_plan"
    assert morning.stage == "invited"
    assert morning.source_date == SOURCE_DATE
    assert morning.last_active_at == NOW
    assert morning.expires_at == NOW + timedelta(minutes=90)

    assert evening.session_type == "evening_review"
    assert evening.stage == "collecting"
    assert evening.plan_artifact_id == "artifact-1"
    assert evening.unresolved_tasks == ["Finish release notes"]
    assert evening.expires_at == NOW + timedelta(minutes=180)


def test_renew_planning_session_preserves_or_replaces_optional_state_by_session_type() -> None:
    settings = _settings()
    draft = _plan(tasks=[_task("Original task")])
    morning = PendingPlanningSession(
        session_type="morning_plan",
        source_date="2026-04-07",
        stage="invited",
        expires_at=NOW,
        last_active_at=NOW - timedelta(hours=2),
        draft_plan=draft,
        unresolved_tasks=["Original unresolved"],
    )

    preserved = day_plans.renew_planning_session(
        morning,
        settings=settings,
        now_utc=NOW,
    )
    replacement = _plan(tasks=[_task("Replacement task")])
    evening = day_plans.renew_planning_session(
        morning.model_copy(update={"session_type": "evening_review"}),
        settings=settings,
        stage="confirming",
        draft_plan=replacement,
        unresolved_tasks=["Replacement unresolved"],
        now_utc=NOW,
    )

    assert preserved.stage == "invited"
    assert preserved.draft_plan == draft
    assert preserved.unresolved_tasks == ["Original unresolved"]
    assert preserved.unresolved_tasks is not morning.unresolved_tasks
    assert preserved.source_date == SOURCE_DATE
    assert preserved.last_active_at == NOW
    assert preserved.expires_at == NOW + timedelta(minutes=90)

    assert evening.stage == "confirming"
    assert evening.draft_plan == replacement
    assert evening.unresolved_tasks == ["Replacement unresolved"]
    assert evening.expires_at == NOW + timedelta(minutes=180)


async def test_load_latest_day_plan_skips_bad_and_other_day_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matching_plan = _plan(tasks=[_task("Ship the release")])
    artifact_id = uuid.uuid4()
    list_artifacts = AsyncMock(
        return_value=[
            _artifact(["not", "a", "mapping"]),
            _artifact({"plan_summary": "missing source date"}),
            _artifact(_plan(source_date="2026-04-07").model_dump(mode="json")),
            SimpleNamespace(id=artifact_id, payload=matching_plan.model_dump(mode="json")),
            _artifact(_plan(tasks=[_task("Older duplicate")]).model_dump(mode="json")),
        ]
    )
    monkeypatch.setattr(day_plans, "list_recent_artifacts_for_user", list_artifacts)
    session = AsyncMock()

    stored = await day_plans.load_latest_day_plan(
        session,
        user_id="owner-1",
        source_date=SOURCE_DATE,
        limit=7,
    )

    assert stored is not None
    assert stored.artifact_id == str(artifact_id)
    assert stored.created_at is None
    assert stored.plan == matching_plan
    list_artifacts.assert_awaited_once_with(
        session,
        user_id="owner-1",
        limit=7,
        artifact_types=["day_plan"],
    )


async def test_load_latest_day_plan_returns_none_for_empty_and_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_artifacts = AsyncMock(return_value=[])
    monkeypatch.setattr(day_plans, "list_recent_artifacts_for_user", list_artifacts)

    assert (
        await day_plans.load_latest_day_plan(
            AsyncMock(),
            user_id="owner-1",
            source_date=SOURCE_DATE,
        )
        is None
    )

    list_artifacts.side_effect = RuntimeError("database offline")
    assert (
        await day_plans.load_latest_day_plan(
            AsyncMock(),
            user_id="owner-1",
            source_date=SOURCE_DATE,
        )
        is None
    )


async def test_load_carry_over_tasks_filters_deduplicates_and_caps_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_plan = _plan(
        source_date="2026-04-07",
        tasks=[
            _task("  Draft launch  ", status="moved_to_backlog"),
            _task("draft LAUNCH", status="moved_to_backlog"),
            _task("Call Sam", status="moved_to_day", rescheduled_for=SOURCE_DATE),
            _task("Move tomorrow", status="moved_to_day", rescheduled_for="2026-04-09"),
            _task("Still planned", status="planned"),
            _task("Cancelled", status="cancelled"),
            _task("   ", status="moved_to_backlog"),
            *[_task(f"Task {index}", status="moved_to_backlog") for index in range(1, 8)],
        ],
    )
    list_artifacts = AsyncMock(
        return_value=[
            _artifact(None),
            _artifact({"source_date": "invalid", "tasks": "not-a-list"}),
            _artifact(
                _plan(tasks=[_task("Current-day task", status="moved_to_backlog")]).model_dump(
                    mode="json"
                )
            ),
            _artifact(prior_plan.model_dump(mode="json")),
        ]
    )
    monkeypatch.setattr(day_plans, "list_recent_artifacts_for_user", list_artifacts)
    session = AsyncMock()

    result = await day_plans.load_carry_over_tasks(
        session,
        user_id="owner-1",
        source_date=SOURCE_DATE,
        limit=15,
    )

    assert result == ["Draft launch", "Call Sam", "Task 1", "Task 2", "Task 3", "Task 4"]
    list_artifacts.assert_awaited_once_with(
        session,
        user_id="owner-1",
        limit=15,
        artifact_types=["day_plan"],
    )


async def test_load_carry_over_tasks_returns_empty_on_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        day_plans,
        "list_recent_artifacts_for_user",
        AsyncMock(side_effect=RuntimeError("database offline")),
    )

    result = await day_plans.load_carry_over_tasks(
        AsyncMock(),
        user_id="owner-1",
        source_date=SOURCE_DATE,
    )

    assert result == []


async def test_persist_day_plan_artifact_forwards_typed_payload_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_id = uuid.uuid4()
    create_record = AsyncMock(return_value=SimpleNamespace(id=artifact_id))
    monkeypatch.setattr(day_plans, "create_artifact_record", create_record)
    session = AsyncMock()
    plan = _plan(
        tasks=[
            _task("Write tests"),
            _task("Review release"),
            _task("Update notes"),
            _task("Publish"),
        ]
    )

    result = await day_plans.persist_day_plan_artifact(
        session,
        user_id="owner-1",
        plan=plan,
        source_id="message-1",
        trace_id="trace-1",
        workflow_id="workflow-1",
    )

    assert result == str(artifact_id)
    create_record.assert_awaited_once()
    assert create_record.await_args.args == (session,)
    assert create_record.await_args.kwargs["user_id"] == "owner-1"
    record = create_record.await_args.kwargs["artifact"]
    assert record.artifact_type == "day_plan"
    assert record.summary == (
        f"Daily plan for {SOURCE_DATE}: Write tests; Review release; Update notes; ..."
    )
    assert record.source_id == "message-1"
    assert record.trace_id == "trace-1"
    assert record.workflow_id == "workflow-1"
    assert record.payload["source_date"] == SOURCE_DATE
    assert record.payload["updated_at"] == NOW.isoformat().replace("+00:00", "Z")


async def test_persist_day_plan_artifact_propagates_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        day_plans,
        "create_artifact_record",
        AsyncMock(side_effect=RuntimeError("write failed")),
    )

    with pytest.raises(RuntimeError, match="write failed"):
        await day_plans.persist_day_plan_artifact(
            AsyncMock(),
            user_id="owner-1",
            plan=_plan(),
        )


def test_day_plan_summary_uses_tasks_then_summary_then_date_only() -> None:
    assert (
        day_plans.build_day_plan_summary(
            _plan(
                tasks=[
                    _task(" First "),
                    _task(""),
                    _task("Second"),
                    _task("Third"),
                    _task("Fourth"),
                ],
                plan_summary="Ignored while tasks exist",
            )
        )
        == f"Daily plan for {SOURCE_DATE}: First; Second; Third; ..."
    )
    assert (
        day_plans.build_day_plan_summary(
            _plan(plan_summary="  Protect the morning for focused work.  ")
        )
        == f"Daily plan for {SOURCE_DATE}: Protect the morning for focused work."
    )
    assert day_plans.build_day_plan_summary(_plan(tasks=[_task("Only task")])) == (
        f"Daily plan for {SOURCE_DATE}: Only task"
    )
    assert day_plans.build_day_plan_summary(_plan(plan_summary="  ")) == (
        f"Daily plan for {SOURCE_DATE}"
    )


def test_day_plan_completion_status_classifies_only_actionable_titles() -> None:
    plan = _plan(
        tasks=[
            _task(" Done ", status="completed"),
            _task("Open", status="planned"),
            _task("Blocked", status="blocked"),
            _task("Moved day", status="moved_to_day"),
            _task("Moved backlog", status="moved_to_backlog"),
            _task("Cancelled", status="cancelled"),
            _task("   ", status="planned"),
        ]
    )

    assert day_plans.day_plan_completion_status(plan) == (
        ["Done"],
        ["Open", "Blocked"],
    )


def test_morning_plan_prompt_handles_empty_and_truncated_carry_over() -> None:
    empty = day_plans.build_morning_plan_prompt(carry_over_tasks=[])
    populated = day_plans.build_morning_plan_prompt(
        carry_over_tasks=["One", "Two", "Three", "Four", "Five"]
    )

    assert "Carry-over or backlog" not in empty
    assert empty.startswith("\nDAY PLAN:")
    assert empty.endswith("narrow it into a concrete plan.")
    assert "Carry-over or backlog to consider: One; Two; Three; Four" in populated
    assert "Five" not in populated


def test_evening_closeout_message_reports_open_work_or_an_all_closed_state() -> None:
    open_plan = _plan(
        tasks=[
            _task("Done one", status="completed"),
            _task("Done two", status="completed"),
            *[_task(f"Open {index}") for index in range(1, 7)],
        ]
    )
    closed_plan = _plan(
        tasks=[
            _task("Finished", status="completed"),
            _task("Deferred", status="moved_to_backlog"),
        ]
    )
    unresolved_only_plan = _plan(tasks=[_task("Not finished")])

    open_message = day_plans.build_evening_closeout_message(open_plan)
    closed_message = day_plans.build_evening_closeout_message(closed_plan)
    unresolved_only_message = day_plans.build_evening_closeout_message(unresolved_only_plan)

    assert "Already closed: Done one; Done two" in open_message
    assert "Still open: Open 1; Open 2; Open 3; Open 4; Open 5" in open_message
    assert "Open 6" not in open_message
    assert "what should move to another day" in open_message
    assert "Everything on today's plan looks closed." in closed_message
    assert "Still open:" not in closed_message
    assert "Already closed:" not in unresolved_only_message
    assert "Still open: Not finished" in unresolved_only_message


def test_day_plan_section_renders_summary_and_only_first_five_task_slots() -> None:
    rendered = day_plans.build_day_plan_section(
        _plan(
            plan_summary="  Keep the day deliberately small.  ",
            tasks=[
                _task("First"),
                _task("  "),
                _task("Third"),
                _task("Fourth"),
                _task("Fifth"),
                _task("Sixth is outside the slice"),
            ],
        )
    )

    assert rendered == "\n".join(
        [
            "TODAY'S PLAN:",
            "  Keep the day deliberately small.",
            "  - First",
            "  - Third",
            "  - Fourth",
            "  - Fifth",
        ]
    )
    assert day_plans.build_day_plan_section(_plan()) == "TODAY'S PLAN:"
