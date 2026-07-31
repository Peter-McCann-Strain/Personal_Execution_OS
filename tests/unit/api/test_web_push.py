"""Tests for owner-scoped web push routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import Principal, get_current_principal, get_db
from src.app.api.routes.web_push import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from src.app.persistence.models import AuditEvent


def _make_subscription(*, subscription_id: uuid.UUID | None = None) -> MagicMock:
    now = datetime.now(UTC)
    record = MagicMock()
    record.id = subscription_id or uuid.uuid4()
    record.status = "active"
    record.endpoint = "https://updates.push.services.mozilla.com/wpush/v2/example"
    record.expiration_time = None
    record.user_agent = "Mozilla/5.0"
    record.failure_count = 0
    record.last_seen_at = now
    record.last_success_at = now
    record.last_failure_at = None
    record.last_error = None
    record.created_at = now
    record.updated_at = now
    return record


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


async def test_get_web_push_config_enabled() -> None:
    mock_session = AsyncMock()
    app = _build_app(mock_session)

    with (
        patch("src.app.api.routes.web_push.web_push_enabled", return_value=True),
        patch("src.app.api.routes.web_push.web_push_public_key", return_value="public-key"),
        patch(
            "src.app.api.routes.web_push.count_active_web_push_subscriptions",
            new_callable=AsyncMock,
            return_value=2,
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/notifications/push/config")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "public_key": "public-key",
        "active_subscription_count": 2,
    }


async def test_list_web_push_subscriptions_success() -> None:
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    subscription = _make_subscription()

    with patch(
        "src.app.api.routes.web_push.list_web_push_subscriptions",
        new_callable=AsyncMock,
        return_value=[subscription],
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/notifications/push/subscriptions")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["status"] == "active"
    assert payload[0]["endpoint_host"] == "updates.push.services.mozilla.com"


async def test_register_web_push_subscription_success() -> None:
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    subscription = _make_subscription()

    with patch(
        "src.app.api.routes.web_push.upsert_web_push_subscription",
        new_callable=AsyncMock,
        return_value=subscription,
    ) as upsert_repo:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/notifications/push/subscriptions",
                headers={"User-Agent": "VitestBrowser/1.0"},
                json={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "auth": "auth-key",
                        "p256dh": "p256dh-key",
                    },
                    "metadata": {"client": "web_app"},
                },
            )

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    upsert_repo.assert_awaited_once()
    added_rows = [call.args[0] for call in mock_session.add.await_args_list]
    audit_event = next(row for row in added_rows if isinstance(row, AuditEvent))
    assert audit_event.event_type == "web_push.subscription_registered"
    assert audit_event.resource_id == str(subscription.id)
    assert audit_event.metadata_["endpoint_host"] == "updates.push.services.mozilla.com"


async def test_delete_web_push_subscription_success() -> None:
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    subscription_id = uuid.uuid4()

    with patch(
        "src.app.api.routes.web_push.revoke_web_push_subscription",
        new_callable=AsyncMock,
        return_value=True,
    ) as revoke_repo:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(
                f"/api/notifications/push/subscriptions/{subscription_id}",
            )

    assert response.status_code == 204
    revoke_repo.assert_awaited_once()
    added_rows = [call.args[0] for call in mock_session.add.await_args_list]
    audit_event = next(row for row in added_rows if isinstance(row, AuditEvent))
    assert audit_event.event_type == "web_push.subscription_revoked"
    assert audit_event.resource_id == str(subscription_id)
