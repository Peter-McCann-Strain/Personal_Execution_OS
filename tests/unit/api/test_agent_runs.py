"""Tests for agent-run inspection and approval routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import (
    Principal,
    get_anthropic_client,
    get_current_principal,
    get_db,
    get_mcp_manager,
)
from src.app.api.routes.agent_runs import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from src.app.persistence.models import AuditEvent


def _make_run(*, workflow_id: uuid.UUID | None = None, status: str = "running") -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=workflow_id or uuid.uuid4(),
        user_id="owner",
        source="chat",
        status=status,
        specialist="tools",
        request_excerpt="Send the follow-up email",
        trace_id="trace-123",
        response_id="resp-123",
        metadata_={"mode": "live"},
        created_at=now,
        updated_at=now,
    )


def _make_approval(
    *,
    workflow_id: uuid.UUID,
    approval_id: uuid.UUID | None = None,
    status: str = "pending",
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=approval_id or uuid.uuid4(),
        workflow_id=workflow_id,
        checkpoint_id=uuid.uuid4(),
        request_kind="confirmation",
        title="Send email?",
        description="Approve sending the drafted email.",
        status=status,
        payload={"risk": "send"},
        created_at=now,
        resolved_at=None,
        updated_at=now,
    )


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

    def _fake_manager():
        return object()

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.dependency_overrides[get_db] = _mock_db
    app.dependency_overrides[get_current_principal] = _always_principal
    app.dependency_overrides[get_anthropic_client] = _fake_client
    app.dependency_overrides[get_mcp_manager] = _fake_manager
    app.include_router(router, prefix="/api")
    return app


async def test_list_agent_runs_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    run = _make_run()
    approval = _make_approval(workflow_id=run.id)

    with (
        patch(
            "src.app.api.routes.agent_runs.list_workflow_runs_for_user",
            new_callable=AsyncMock,
            return_value=([run], 1),
        ),
        patch(
            "src.app.api.routes.agent_runs.list_approval_requests",
            new_callable=AsyncMock,
            return_value=[approval],
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/agent-runs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["pending_approvals"] == 1


async def test_get_agent_run_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    run = _make_run()
    approval = _make_approval(workflow_id=run.id)

    with (
        patch(
            "src.app.api.routes.agent_runs.get_workflow_run_by_id",
            new_callable=AsyncMock,
            return_value=run,
        ),
        patch(
            "src.app.api.routes.agent_runs.list_workflow_run_steps",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.agent_runs.list_approval_requests",
            new_callable=AsyncMock,
            return_value=[approval],
        ),
        patch(
            "src.app.api.routes.agent_runs.list_browser_sessions",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.agent_runs.list_tool_receipts",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.agent_runs.list_artifacts_for_workflow",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/agent-runs/{run.id}")

    assert response.status_code == 200
    assert response.json()["approvals"][0]["title"] == "Send email?"


async def test_cancel_agent_run_request_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    run = _make_run()
    approval = _make_approval(workflow_id=run.id)

    with (
        patch(
            "src.app.api.routes.agent_runs.get_workflow_run_by_id",
            new_callable=AsyncMock,
            return_value=run,
        ),
        patch(
            "src.app.api.routes.agent_runs.get_approval_request_by_id",
            new_callable=AsyncMock,
            return_value=approval,
        ),
        patch(
            "src.app.api.routes.agent_runs.resolve_approval_request",
            new_callable=AsyncMock,
        ) as resolve_request,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/agent-runs/{run.id}/approvals/{approval.id}")

    assert response.status_code == 204
    resolve_request.assert_awaited_once()
    added_rows = [call.args[0] for call in mock_session.add.await_args_list]
    audit_event = next(row for row in added_rows if isinstance(row, AuditEvent))
    assert audit_event.event_type == "approval_request.cancelled"
    assert audit_event.resource_id == str(approval.id)
