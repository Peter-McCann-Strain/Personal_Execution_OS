"""Transaction and failure-boundary tests for scheduled-action execution."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.domain.services.scheduled_actions_runtime import execute_scheduled_action
from src.app.persistence.models import NotificationRecord, ScheduledAction


def _session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _action(**overrides: object) -> ScheduledAction:
    action = ScheduledAction()
    action.id = overrides.get("id", uuid.uuid4())
    action.user_id = overrides.get("user_id", "owner")
    action.title = overrides.get("title", "Morning review")
    action.prompt = overrides.get("prompt", "Review risks")
    action.delivery_channel = overrides.get("delivery_channel", "web")
    return action


@pytest.mark.asyncio
async def test_success_commits_run_before_processing_and_persists_visible_result() -> None:
    session = _session()
    action = _action()
    client = MagicMock()
    workflow_id = uuid.uuid4()
    request_id = uuid.uuid4()
    scheduled_run = SimpleNamespace(id=uuid.uuid4())
    response = SimpleNamespace(
        content="A" * 600,
        metadata={"model": "test"},
    )
    events: list[str] = []

    async def create_run(*args, **kwargs):
        events.append("create-run")
        return scheduled_run

    async def commit() -> None:
        events.append("commit")

    async def process(*args, **kwargs):
        events.append("process")
        return response

    async def update_run(*args, **kwargs):
        events.append("update-run")

    async def mark_executed(*args, **kwargs):
        events.append("mark-executed")

    session.commit.side_effect = commit
    session.add.side_effect = lambda notification: events.append("add-notification")

    with (
        patch(
            "src.app.domain.services.scheduled_actions_runtime.uuid.uuid4",
            side_effect=[workflow_id, request_id],
        ),
        patch(
            "src.app.domain.services.scheduled_actions_runtime.create_scheduled_action_run",
            new=AsyncMock(side_effect=create_run),
        ) as create_mock,
        patch(
            "src.app.domain.services.scheduled_actions_runtime.process_message",
            new=AsyncMock(side_effect=process),
        ) as process_mock,
        patch(
            "src.app.domain.services.scheduled_actions_runtime.persist_recorded_trace",
            new=AsyncMock(),
        ) as trace_mock,
        patch(
            "src.app.domain.services.scheduled_actions_runtime.update_scheduled_action_run",
            new=AsyncMock(side_effect=update_run),
        ) as update_mock,
        patch(
            "src.app.domain.services.scheduled_actions_runtime.mark_scheduled_action_executed",
            new=AsyncMock(side_effect=mark_executed),
        ) as mark_mock,
        patch(
            "src.app.domain.services.scheduled_actions_runtime.dispatch_web_push_for_notification",
            new=AsyncMock(),
        ) as push_mock,
    ):
        summary = await execute_scheduled_action(
            session,
            client=client,
            action=action,
        )

    assert summary == "A" * 500
    assert events == [
        "create-run",
        "commit",
        "process",
        "update-run",
        "mark-executed",
        "add-notification",
        "commit",
    ]
    create_mock.assert_awaited_once_with(
        session,
        action_id=action.id,
        workflow_id=workflow_id,
        status="running",
        payload={"delivery_channel": "web"},
    )
    message = process_mock.await_args.args[0]
    assert message.content == action.prompt
    assert message.user_id == "owner"
    assert message.metadata == {
        "request_id": str(request_id),
        "workflow_id": str(workflow_id),
        "scheduled_action_id": str(action.id),
        "scheduled_action_run_id": str(scheduled_run.id),
        "scheduled_delivery_channel": "web",
    }
    trace_mock.assert_awaited_once_with(session, message.metadata)
    update_mock.assert_awaited_once_with(
        session,
        run_id=scheduled_run.id,
        status="completed",
        result_summary="A" * 500,
        payload={
            "response_metadata": {"model": "test"},
            "workflow_id": str(workflow_id),
        },
    )
    mark_mock.assert_awaited_once_with(
        session,
        action=action,
        result_summary="A" * 500,
    )
    notification = session.add.call_args.args[0]
    assert isinstance(notification, NotificationRecord)
    assert notification.message == f"{action.title}: {'A' * 500}"
    assert notification.priority == "P2"
    push_mock.assert_awaited_once_with(
        session,
        user_id="owner",
        notification=notification,
    )
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmation_result_is_user_visible_and_push_failure_is_nonfatal() -> None:
    session = _session()
    action = _action(title="Publish release")
    scheduled_run = SimpleNamespace(id=uuid.uuid4())
    response = SimpleNamespace(
        content="Please approve publication." + ("x" * 500),
        metadata={"confirmation_required": True},
    )

    with (
        patch(
            "src.app.domain.services.scheduled_actions_runtime.create_scheduled_action_run",
            new=AsyncMock(return_value=scheduled_run),
        ),
        patch(
            "src.app.domain.services.scheduled_actions_runtime.process_message",
            new=AsyncMock(return_value=response),
        ),
        patch(
            "src.app.domain.services.scheduled_actions_runtime.persist_recorded_trace",
            new=AsyncMock(),
        ),
        patch(
            "src.app.domain.services.scheduled_actions_runtime.update_scheduled_action_run",
            new=AsyncMock(),
        ) as update_mock,
        patch(
            "src.app.domain.services.scheduled_actions_runtime.mark_scheduled_action_executed",
            new=AsyncMock(),
        ),
        patch(
            "src.app.domain.services.scheduled_actions_runtime.dispatch_web_push_for_notification",
            new=AsyncMock(side_effect=RuntimeError("push offline")),
        ),
    ):
        summary = await execute_scheduled_action(
            session,
            client=MagicMock(),
            action=action,
        )

    assert summary.startswith(
        "Approval required for scheduled action 'Publish release'. Please approve"
    )
    assert len(summary) <= len("Approval required for scheduled action 'Publish release'. ") + 400
    assert update_mock.await_args.kwargs["status"] == "completed"
    assert update_mock.await_args.kwargs["result_summary"] == summary
    assert session.commit.await_count == 2
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_processing_failure_rolls_back_then_commits_failed_run_and_notification() -> None:
    session = _session()
    action = _action()
    scheduled_run = SimpleNamespace(id=uuid.uuid4())
    workflow_id = uuid.uuid4()
    request_id = uuid.uuid4()
    events: list[str] = []

    async def commit() -> None:
        events.append("commit")

    async def rollback() -> None:
        events.append("rollback")

    async def fail_process(*args, **kwargs):
        events.append("process")
        raise RuntimeError("provider unavailable")

    async def update_run(*args, **kwargs):
        events.append("update-failed-run")

    session.commit.side_effect = commit
    session.rollback.side_effect = rollback
    session.add.side_effect = lambda notification: events.append("add-failure-notification")

    with (
        patch(
            "src.app.domain.services.scheduled_actions_runtime.uuid.uuid4",
            side_effect=[workflow_id, request_id],
        ),
        patch(
            "src.app.domain.services.scheduled_actions_runtime.create_scheduled_action_run",
            new=AsyncMock(return_value=scheduled_run),
        ),
        patch(
            "src.app.domain.services.scheduled_actions_runtime.process_message",
            new=AsyncMock(side_effect=fail_process),
        ),
        patch(
            "src.app.domain.services.scheduled_actions_runtime.persist_recorded_trace",
            new=AsyncMock(),
        ) as trace_mock,
        patch(
            "src.app.domain.services.scheduled_actions_runtime.update_scheduled_action_run",
            new=AsyncMock(side_effect=update_run),
        ) as update_mock,
        patch(
            "src.app.domain.services.scheduled_actions_runtime.mark_scheduled_action_executed",
            new=AsyncMock(),
        ) as mark_mock,
        patch(
            "src.app.domain.services.scheduled_actions_runtime.dispatch_web_push_for_notification",
            new=AsyncMock(),
        ) as push_mock,
        pytest.raises(RuntimeError, match="provider unavailable"),
    ):
        await execute_scheduled_action(
            session,
            client=MagicMock(),
            action=action,
        )

    assert events == [
        "commit",
        "process",
        "rollback",
        "update-failed-run",
        "add-failure-notification",
        "commit",
    ]
    update_mock.assert_awaited_once_with(
        session,
        run_id=scheduled_run.id,
        status="failed",
        error_message="provider unavailable",
        payload={"workflow_id": str(workflow_id)},
    )
    trace_mock.assert_not_awaited()
    mark_mock.assert_not_awaited()
    notification = session.add.call_args.args[0]
    assert notification.message == "Scheduled action failed: Morning review"
    assert notification.priority == "P1"
    push_mock.assert_awaited_once_with(
        session,
        user_id="owner",
        notification=notification,
    )


@pytest.mark.asyncio
async def test_trace_failure_uses_failure_path_and_failure_push_error_is_nonfatal() -> None:
    session = _session()
    action = _action()
    scheduled_run = SimpleNamespace(id=uuid.uuid4())

    with (
        patch(
            "src.app.domain.services.scheduled_actions_runtime.create_scheduled_action_run",
            new=AsyncMock(return_value=scheduled_run),
        ),
        patch(
            "src.app.domain.services.scheduled_actions_runtime.process_message",
            new=AsyncMock(
                return_value=SimpleNamespace(content="Generated", metadata={}),
            ),
        ),
        patch(
            "src.app.domain.services.scheduled_actions_runtime.persist_recorded_trace",
            new=AsyncMock(side_effect=ValueError("trace persistence failed")),
        ),
        patch(
            "src.app.domain.services.scheduled_actions_runtime.update_scheduled_action_run",
            new=AsyncMock(),
        ) as update_mock,
        patch(
            "src.app.domain.services.scheduled_actions_runtime.mark_scheduled_action_executed",
            new=AsyncMock(),
        ) as mark_mock,
        patch(
            "src.app.domain.services.scheduled_actions_runtime.dispatch_web_push_for_notification",
            new=AsyncMock(side_effect=RuntimeError("push also failed")),
        ),
        pytest.raises(ValueError, match="trace persistence failed"),
    ):
        await execute_scheduled_action(
            session,
            client=MagicMock(),
            action=action,
        )

    session.rollback.assert_awaited_once()
    assert session.commit.await_count == 2
    assert update_mock.await_args.kwargs["status"] == "failed"
    assert update_mock.await_args.kwargs["error_message"] == "trace persistence failed"
    mark_mock.assert_not_awaited()
