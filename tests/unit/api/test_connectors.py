"""Tests for persisted connector-account routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from src.app.api.deps import Principal, get_current_principal, get_db
from src.app.api.routes.connectors import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from src.app.persistence.models import AuditEvent, ConnectorOAuthState


def _make_account(*, account_id: uuid.UUID | None = None, status: str = "connected") -> MagicMock:
    now = datetime.now(UTC)
    account = MagicMock()
    account.id = account_id or uuid.uuid4()
    account.user_id = "owner"
    account.connector_type = "gmail"
    account.display_name = "Gmail"
    account.status = status
    account.scopes = ["mail.readonly"]
    account.encrypted_refresh_token = None
    account.token_last_rotated_at = None
    account.auto_use = True
    account.background_access = False
    account.sync_enabled = True
    account.last_sync_at = now
    account.metadata_ = {"provider": "google"}
    account.created_at = now
    account.updated_at = now
    return account


def _make_job(*, account_id: uuid.UUID) -> MagicMock:
    now = datetime.now(UTC)
    job = MagicMock()
    job.id = uuid.uuid4()
    job.account_id = account_id
    job.sync_type = "incremental"
    job.status = "completed"
    job.document_count = 12
    job.error_message = None
    job.metadata_ = {"source_types": ["message"]}
    job.started_at = now
    job.completed_at = now
    job.created_at = now
    return job


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


def _oauth_settings() -> SimpleNamespace:
    return SimpleNamespace(
        google_client_id="google-client-id",
        google_client_secret=SecretStr("google-client-secret"),
        google_oauth_redirect_url="https://app.example.com/api/connectors/oauth/google/callback",
        product_public_url="https://app.example.com",
        connector_token_encryption_key=SecretStr(
            "76d95e66beec8c39565fc6948be6ae840af0043bb4b05252b5bd8a56d7e57a1a"
        ),
    )


async def test_list_connector_accounts_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    account = _make_account()

    with patch(
        "src.app.api.routes.connectors.repo_list_connector_accounts",
        new_callable=AsyncMock,
        return_value=[account],
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/connectors/accounts")

    assert response.status_code == 200
    assert response.json()[0]["connector_type"] == "gmail"


async def test_start_google_oauth_creates_state_and_auth_url():
    mock_session = AsyncMock()
    app = _build_app(mock_session)

    with (
        patch("src.app.api.routes.connectors.get_settings", return_value=_oauth_settings()),
        patch("src.app.api.routes.connectors.secrets.token_urlsafe", return_value="state-secret"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/connectors/oauth/google/start",
                params={"connector_type": "gmail"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["auth_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "state=state-secret" in body["auth_url"]
    assert "gmail.readonly" in body["auth_url"]
    assert mock_session.add.await_count == 2
    added_rows = [call.args[0] for call in mock_session.add.await_args_list]
    oauth_state = next(row for row in added_rows if isinstance(row, ConnectorOAuthState))
    audit_event = next(row for row in added_rows if isinstance(row, AuditEvent))
    assert oauth_state.connector_type == "gmail"
    assert oauth_state.user_id == "owner"
    assert oauth_state.state_hash != "state-secret"
    assert audit_event.event_type == "connector.oauth_started"
    assert audit_event.metadata_["connector_type"] == "gmail"
    mock_session.commit.assert_awaited_once()


async def test_start_google_oauth_requires_strong_token_encryption_key():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    settings = _oauth_settings()
    settings.connector_token_encryption_key = SecretStr("vault-key")

    with patch("src.app.api.routes.connectors.get_settings", return_value=settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/connectors/oauth/google/start",
                params={"connector_type": "gmail"},
            )

    assert response.status_code == 503
    assert "CONNECTOR_TOKEN_ENCRYPTION_KEY" in response.json()["detail"]
    assert mock_session.add.await_count == 0
    mock_session.commit.assert_not_awaited()


async def test_google_oauth_callback_exchanges_code_and_redirects():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    oauth_state = MagicMock()
    oauth_state.status = "pending"
    oauth_state.expires_at = datetime.now(UTC) + timedelta(minutes=5)
    oauth_state.connector_type = "gmail"
    oauth_state.redirect_uri = "https://app.example.com/api/connectors/oauth/google/callback"
    oauth_state.account_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    oauth_state.user_id = "owner"

    with (
        patch("src.app.api.routes.connectors.get_settings", return_value=_oauth_settings()),
        patch(
            "src.app.api.routes.connectors._load_oauth_state",
            new_callable=AsyncMock,
            return_value=oauth_state,
        ),
        patch(
            "src.app.api.routes.connectors._exchange_google_code",
            new_callable=AsyncMock,
            return_value={"refresh_token": "refresh-token"},
        ) as exchange,
        patch(
            "src.app.api.routes.connectors._scope_callback_session",
            new_callable=AsyncMock,
        ) as scope_session,
        patch(
            "src.app.api.routes.connectors._upsert_oauth_connector_account",
            new_callable=AsyncMock,
            return_value=_make_account(account_id=oauth_state.account_id),
        ) as upsert,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/connectors/oauth/google/callback",
                params={"state": "state-secret", "code": "auth-code"},
            )

    assert response.status_code == 307
    assert "connector=gmail" in response.headers["location"]
    assert "status=connected" in response.headers["location"]
    assert oauth_state.status == "consumed"
    assert oauth_state.consumed_at is not None
    exchange.assert_awaited_once_with(
        code="auth-code",
        redirect_uri="https://app.example.com/api/connectors/oauth/google/callback",
    )
    scope_session.assert_awaited_once()
    upsert.assert_awaited_once()
    mock_session.commit.assert_awaited_once()
    added_rows = [call.args[0] for call in mock_session.add.await_args_list]
    audit_event = next(row for row in added_rows if isinstance(row, AuditEvent))
    assert audit_event.event_type == "connector.oauth_completed"
    assert audit_event.resource_id


async def test_create_connector_account_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    account = _make_account(status="disconnected")

    with patch(
        "src.app.api.routes.connectors.repo_create_connector_account",
        new_callable=AsyncMock,
        return_value=account,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/connectors/accounts",
                json={"connector_type": "gmail", "sync_enabled": True},
            )

    assert response.status_code == 201
    assert response.json()["status"] == "disconnected"
    added_rows = [call.args[0] for call in mock_session.add.await_args_list]
    audit_event = next(row for row in added_rows if isinstance(row, AuditEvent))
    assert audit_event.event_type == "connector.account_created"
    assert audit_event.metadata_["connector_type"] == "gmail"


async def test_create_connector_account_encrypts_refresh_token():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    account = _make_account()
    account.encrypted_refresh_token = "v1:encrypted"
    account.token_last_rotated_at = datetime.now(UTC)

    with (
        patch(
            "src.app.api.routes.connectors.encrypt_secret",
            return_value="v1:encrypted",
        ) as encrypt,
        patch(
            "src.app.api.routes.connectors.repo_create_connector_account",
            new_callable=AsyncMock,
            return_value=account,
        ) as create_account,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/connectors/accounts",
                json={
                    "connector_type": "gmail",
                    "sync_enabled": True,
                    "refresh_token": "raw-refresh-token",
                    "oauth_email": "owner@example.com",
                },
            )

    assert response.status_code == 201
    assert response.json()["has_refresh_token"] is True
    assert "raw-refresh-token" not in response.text
    encrypt.assert_called_once()
    create_kwargs = create_account.await_args.kwargs
    assert create_kwargs["encrypted_refresh_token"] == "v1:encrypted"
    assert create_kwargs["token_last_rotated_at"] is not None
    assert create_kwargs["metadata"]["oauth_email"] == "owner@example.com"


async def test_sync_connector_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    account = _make_account()
    job = _make_job(account_id=account.id)

    with (
        patch(
            "src.app.api.routes.connectors.repo_get_connector_account",
            new_callable=AsyncMock,
            return_value=account,
        ),
        patch(
            "src.app.api.routes.connectors.repo_create_connector_sync_job",
            new_callable=AsyncMock,
            return_value=job,
        ),
        patch(
            "src.app.api.routes.connectors.sync_connector_account",
            new_callable=AsyncMock,
            return_value=12,
        ),
        patch(
            "src.app.api.routes.connectors.repo_update_connector_sync_job",
            new_callable=AsyncMock,
        ) as update_job,
        patch(
            "src.app.api.routes.connectors.repo_update_connector_account",
            new_callable=AsyncMock,
        ) as update_account,
        patch(
            "src.app.api.routes.connectors.repo_list_connector_sync_jobs",
            new_callable=AsyncMock,
            return_value=[job],
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/connectors/accounts/{account.id}/sync",
                json={"sync_type": "incremental", "max_items": 10},
            )

    assert response.status_code == 200
    assert response.json()["document_count"] == 12
    update_job.assert_awaited()
    update_account.assert_awaited()
