"""Tests for scheduled-action routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import Principal, get_anthropic_client, get_current_principal, get_db
from src.app.api.routes.scheduled_actions import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from src.app.persistence.models import AuditEvent


def _make_action(*, action_id: uuid.UUID | None = None, status: str = "active") -> MagicMock:
    now = datetime.now(UTC)
    action = MagicMock()
    action.id = action_id or uuid.uuid4()
    action.user_id = "owner"
    action.title = "Morning pulse"
    action.prompt = "Prepare today's pulse."
    action.schedule_type = "daily"
    action.schedule_config = {"hour": 8, "minute": 0}
    action.timezone = "Europe/London"
    action.status = status
    action.delivery_channel = "web"
    action.next_run_at = now
    action.last_run_at = None
    action.last_result_summary = None
    action.metadata_ = {"source": "ui"}
    action.created_at = now
    action.updated_at = now
    return action


def _make_run(*, action_id: uuid.UUID) -> MagicMock:
    now = datetime.now(UTC)
    run = MagicMock()
    run.id = uuid.uuid4()
    run.action_id = action_id
    run.workflow_id = uuid.uuid4()
    run.status = "completed"
    run.result_summary = "Pulse delivered"
    run.error_message = None
    run.payload = {"delivery_channel": "web"}
    run.triggered_at = now
    run.completed_at = now
    run.created_at = now
    return run


def _build_app(mock_session: AsyncMock) -> FastAPI:
    app = FastAPI()

    async def _mock_db():
        yield mock_session

    async def _always_principal() -> Principal:
        return Principal(
            subject="owner",
            external_subject=None,
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
            account_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            role="owner",
            plan="pro",
            scopes=("admin",),
            auth_method="api_key",
        )

    def _fake_client():
        return AsyncMock()

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.dependency_overrides[get_db] = _mock_db
    app.dependency_overrides[get_current_principal] = _always_principal
    app.dependency_overrides[get_anthropic_client] = _fake_client
    app.include_router(router, prefix="/api")
    return app


async def test_list_scheduled_actions_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    action = _make_action()

    with patch(
        "src.app.api.routes.scheduled_actions.repo_list_scheduled_actions",
        new_callable=AsyncMock,
        return_value=([action], 1),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/scheduled-actions", params={"status": "active"})

    assert response.status_code == 200
    assert response.json()["items"][0]["title"] == "Morning pulse"


async def test_create_scheduled_action_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    action = _make_action()

    with patch(
        "src.app.api.routes.scheduled_actions.repo_create_scheduled_action",
        new_callable=AsyncMock,
        return_value=action,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/scheduled-actions",
                json={
                    "title": "Morning pulse",
                    "prompt": "Prepare today's pulse.",
                    "schedule_type": "daily",
                },
            )

    assert response.status_code == 201
    assert response.json()["schedule_type"] == "daily"
    added_rows = [call.args[0] for call in mock_session.add.await_args_list]
    audit_event = next(row for row in added_rows if isinstance(row, AuditEvent))
    assert audit_event.event_type == "scheduled_action.created"
    assert audit_event.resource_id == str(action.id)


async def test_run_scheduled_action_now_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    action = _make_action()
    run = _make_run(action_id=action.id)

    with (
        patch(
            "src.app.api.routes.scheduled_actions.repo_get_scheduled_action",
            new_callable=AsyncMock,
            return_value=action,
        ),
        patch(
            "src.app.api.routes.scheduled_actions.execute_scheduled_action",
            new_callable=AsyncMock,
        ) as execute_action,
        patch(
            "src.app.api.routes.scheduled_actions.repo_list_scheduled_action_runs",
            new_callable=AsyncMock,
            return_value=[run],
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/scheduled-actions/{action.id}/run")

    assert response.status_code == 200
    assert response.json()["result_summary"] == "Pulse delivered"
    execute_action.assert_awaited_once()
    added_rows = [call.args[0] for call in mock_session.add.await_args_list]
    audit_event = next(row for row in added_rows if isinstance(row, AuditEvent))
    assert audit_event.event_type == "scheduled_action.run_requested"
    assert audit_event.resource_id == str(action.id)


async def test_delete_scheduled_action_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    action_id = uuid.uuid4()

    with patch(
        "src.app.api.routes.scheduled_actions.repo_soft_delete_scheduled_action",
        new_callable=AsyncMock,
        return_value=True,
    ) as delete_repo:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/scheduled-actions/{action_id}")

    assert response.status_code == 204
    delete_repo.assert_awaited_once()
    added_rows = [call.args[0] for call in mock_session.add.await_args_list]
    audit_event = next(row for row in added_rows if isinstance(row, AuditEvent))
    assert audit_event.event_type == "scheduled_action.deleted"
    assert audit_event.resource_id == str(action_id)
