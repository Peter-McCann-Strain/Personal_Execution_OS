"""Tests for the runtime stream endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import Principal, get_current_principal, get_db
from src.app.api.routes.runtime_stream import RuntimeStreamSnapshot, router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse


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

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.dependency_overrides[get_db] = _mock_db
    app.dependency_overrides[get_current_principal] = _always_principal
    app.include_router(router, prefix="/api")
    return app


async def test_runtime_stream_emits_initial_snapshot() -> None:
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    snapshot = RuntimeStreamSnapshot(
        generated_at="2026-04-14T00:15:00Z",
        workflow_revision="2026-04-14T00:14:59Z",
        workflow_total=4,
        active_workflow_count=1,
        approval_revision="2026-04-14T00:14:55Z",
        pending_approval_count=1,
        notification_revision="2026-04-14T00:14:40Z",
        unread_notification_count=3,
        proactive_unread_count=2,
        scheduled_action_revision="2026-04-14T00:14:20Z",
        scheduled_action_count=2,
        scheduled_action_run_revision="2026-04-14T00:14:21Z",
        scheduled_action_run_count=5,
        web_push_revision="2026-04-14T00:13:00Z",
        web_push_subscription_count=1,
    )

    with patch(
        "src.app.api.routes.runtime_stream._build_runtime_stream_snapshot",
        new_callable=AsyncMock,
        return_value=snapshot,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            async with client.stream(
                "GET",
                "/api/runtime/stream",
                params={
                    "poll_interval_ms": 250,
                    "heartbeat_interval_ms": 2000,
                    "max_events": 2,
                },
            ) as response:
                assert response.status_code == 200
                chunks: list[str] = []
                async for chunk in response.aiter_text():
                    chunks.append(chunk)
                    if "event: runtime_snapshot" in chunk:
                        break

    combined = "".join(chunks)
    assert "event: runtime_open" in combined
    assert "event: runtime_snapshot" in combined
    assert '"pending_approval_count":1' in combined
