"""Tests for persisted connector-account routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

import src.app.api.routes.connectors as connectors
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


def _build_app(mock_session: AsyncMock, *, external_subject: str | None = None) -> FastAPI:
    app = FastAPI()

    async def _mock_db():
        yield mock_session

    async def _always_principal() -> Principal:
        return Principal(
            subject="owner",
            external_subject=external_subject,
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


def _make_oauth_state(
    *,
    status: str = "pending",
    expires_at: datetime | None = None,
    connector_type: str = "gmail",
) -> SimpleNamespace:
    return SimpleNamespace(
        account_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        user_id="owner",
        connector_type=connector_type,
        scopes=["openid", "email"],
        redirect_uri="https://app.example.com/api/connectors/oauth/google/callback",
        status=status,
        expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=5),
        error_message=None,
        consumed_at=None,
    )


def _make_document(*, account_id: uuid.UUID) -> MagicMock:
    now = datetime.now(UTC)
    document = MagicMock()
    document.id = uuid.uuid4()
    document.account_id = account_id
    document.external_id = "message-1"
    document.source_type = "gmail_message"
    document.title = "Quarterly plan"
    document.content = "Plan body"
    document.source_url = "https://mail.google.com/message-1"
    document.metadata_ = {"labels": ["important"]}
    document.synced_at = now
    document.created_at = now
    document.updated_at = now
    return document


def _mock_http_client(*, response: MagicMock | None = None) -> tuple[MagicMock, AsyncMock]:
    client = AsyncMock()
    client.post.return_value = response or MagicMock()
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=client)
    context_manager.__aexit__ = AsyncMock(return_value=None)
    return context_manager, client


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


async def test_connector_accounts_cannot_be_created_outside_oauth():
    mock_session = AsyncMock()
    app = _build_app(mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/connectors/accounts",
            json={"connector_type": "gmail", "refresh_token": "untrusted-token"},
        )

    assert response.status_code == 405
    mock_session.commit.assert_not_awaited()


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
        ) as sync_account,
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
                json={"sync_type": "incremental", "max_items": 1000},
            )

    assert response.status_code == 200
    assert response.json()["document_count"] == 12
    assert sync_account.await_args.kwargs["max_items"] == 100
    update_job.assert_awaited()
    update_account.assert_awaited()


async def test_account_listing_uses_external_subject_and_serializes_nullable_fields():
    mock_session = AsyncMock()
    app = _build_app(mock_session, external_subject="identity-provider-user")
    account = _make_account()
    account.scopes = None
    account.last_sync_at = None
    account.metadata_ = None

    with patch(
        "src.app.api.routes.connectors.repo_list_connector_accounts",
        new_callable=AsyncMock,
        return_value=[account],
    ) as list_accounts:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/connectors/accounts")

    assert response.status_code == 200
    assert response.json()[0]["scopes"] == []
    assert response.json()[0]["last_sync_at"] is None
    assert response.json()[0]["metadata"] == {}
    list_accounts.assert_awaited_once_with(mock_session, user_id="identity-provider-user")


async def test_oauth_helpers_scope_state_exchange_and_claim_validation():
    sync_session = MagicMock()
    sync_session.add.return_value = None
    marker = object()
    await connectors._session_add(sync_session, marker)
    sync_session.add.assert_called_once_with(marker)

    mock_session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = "stored-state"
    mock_session.execute.return_value = result
    assert await connectors._load_oauth_state(mock_session, state="raw-state") == "stored-state"

    account_id = uuid.uuid4()
    mock_session.info = {}
    await connectors._scope_callback_session(
        mock_session,
        account_id=account_id,
        user_id="callback-owner",
    )
    assert mock_session.info == {
        "account_id": account_id,
        "user_id": "callback-owner",
    }
    assert mock_session.execute.await_args.args[1] == {
        "account_id": str(account_id),
        "user_id": "callback-owner",
    }

    settings = _oauth_settings()
    good_response = MagicMock()
    good_response.json.return_value = {"refresh_token": "fresh"}
    bad_response = MagicMock()
    bad_response.json.return_value = ["not", "an", "object"]
    context_manager, client = _mock_http_client()
    client.post.side_effect = [good_response, bad_response]
    with (
        patch("src.app.api.routes.connectors.get_settings", return_value=settings),
        patch("src.app.api.routes.connectors.httpx.AsyncClient", return_value=context_manager),
    ):
        payload = await connectors._exchange_google_code(
            code="authorization-code",
            redirect_uri=settings.google_oauth_redirect_url,
        )
        assert payload == {"refresh_token": "fresh"}
        with pytest.raises(ValueError, match="not an object"):
            await connectors._exchange_google_code(
                code="authorization-code",
                redirect_uri=settings.google_oauth_redirect_url,
            )

    assert connectors._google_id_claims(None) == {}
    with patch(
        "src.app.api.routes.connectors.jwt.decode",
        side_effect=connectors.jwt.PyJWTError("invalid token"),
    ):
        assert connectors._google_id_claims("broken-token") == {}
    with patch(
        "src.app.api.routes.connectors.jwt.decode",
        return_value={"sub": 42, "email": "owner@example.com", "ignored": "claim"},
    ):
        assert connectors._google_id_claims("id-token") == {
            "sub": "42",
            "email": "owner@example.com",
        }


async def test_upsert_oauth_account_covers_create_update_and_missing_refresh_token():
    session = AsyncMock()
    state = _make_oauth_state()
    created = _make_account()
    existing = _make_account()
    existing.metadata_ = {"provider": "google", "keep": True}
    rotated_at = datetime.now(UTC)

    with (
        patch(
            "src.app.api.routes.connectors.repo_list_connector_accounts",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.connectors._encrypted_refresh_token",
            return_value=("encrypted", rotated_at),
        ),
        patch(
            "src.app.api.routes.connectors.repo_create_connector_account",
            new_callable=AsyncMock,
            return_value=created,
        ) as create_account,
        patch(
            "src.app.api.routes.connectors.jwt.decode",
            return_value={"sub": "google-subject", "email": "owner@example.com"},
        ),
    ):
        result = await connectors._upsert_oauth_connector_account(
            session,
            oauth_state=state,
            token_payload={"refresh_token": "fresh", "id_token": "id-token"},
        )

    assert result is created
    assert create_account.await_args.kwargs["encrypted_refresh_token"] == "encrypted"
    assert create_account.await_args.kwargs["metadata"]["oauth_subject"] == "google-subject"
    assert create_account.await_args.kwargs["metadata"]["oauth_email"] == "owner@example.com"

    with (
        patch(
            "src.app.api.routes.connectors.repo_list_connector_accounts",
            new_callable=AsyncMock,
            return_value=[existing],
        ),
        patch(
            "src.app.api.routes.connectors.repo_update_connector_account",
            new_callable=AsyncMock,
            return_value=existing,
        ) as update_account,
    ):
        result = await connectors._upsert_oauth_connector_account(
            session,
            oauth_state=state,
            token_payload={},
        )

    assert result is existing
    assert update_account.await_args.kwargs["encrypted_refresh_token"] is None
    assert update_account.await_args.kwargs["metadata"]["keep"] is True

    with (
        patch(
            "src.app.api.routes.connectors.repo_list_connector_accounts",
            new_callable=AsyncMock,
            return_value=[],
        ),
        pytest.raises(ValueError, match="did not return a refresh token"),
    ):
        await connectors._upsert_oauth_connector_account(
            session,
            oauth_state=state,
            token_payload={},
        )

    with (
        patch(
            "src.app.api.routes.connectors.repo_list_connector_accounts",
            new_callable=AsyncMock,
            return_value=[existing],
        ),
        patch(
            "src.app.api.routes.connectors.repo_update_connector_account",
            new_callable=AsyncMock,
            return_value=None,
        ),
        pytest.raises(ValueError, match="disappeared"),
    ):
        await connectors._upsert_oauth_connector_account(
            session,
            oauth_state=state,
            token_payload={},
        )


async def test_start_google_oauth_rejects_unsupported_unconfigured_and_invalid_redirects():
    mock_session = AsyncMock()
    app = _build_app(mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unsupported = await client.post(
            "/api/connectors/oauth/google/start",
            params={"connector_type": "dropbox"},
        )
        missing_query = await client.post("/api/connectors/oauth/google/start")

        missing_client = _oauth_settings()
        missing_client.google_client_id = ""
        with patch("src.app.api.routes.connectors.get_settings", return_value=missing_client):
            no_client = await client.post(
                "/api/connectors/oauth/google/start",
                params={"connector_type": "gmail"},
            )

        missing_secret = _oauth_settings()
        missing_secret.google_client_secret = SecretStr("")
        with patch("src.app.api.routes.connectors.get_settings", return_value=missing_secret):
            no_secret = await client.post(
                "/api/connectors/oauth/google/start",
                params={"connector_type": "gmail"},
            )

        missing_redirect = _oauth_settings()
        missing_redirect.google_oauth_redirect_url = "   "
        with patch("src.app.api.routes.connectors.get_settings", return_value=missing_redirect):
            no_redirect = await client.post(
                "/api/connectors/oauth/google/start",
                params={"connector_type": "google_drive"},
            )

    assert unsupported.status_code == 400
    assert unsupported.json()["detail"] == "Unsupported Google connector"
    assert missing_query.status_code == 422
    assert no_client.status_code == 503
    assert no_secret.status_code == 503
    assert "not configured" in no_secret.json()["detail"]
    assert no_redirect.status_code == 503
    assert "GOOGLE_OAUTH_REDIRECT_URL" in no_redirect.json()["detail"]
    mock_session.commit.assert_not_awaited()


async def test_google_oauth_callback_rejects_invalid_expired_provider_error_and_missing_code():
    mock_session = AsyncMock()
    app = _build_app(mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch(
            "src.app.api.routes.connectors._load_oauth_state",
            new_callable=AsyncMock,
            return_value=None,
        ):
            invalid = await client.get(
                "/api/connectors/oauth/google/callback",
                params={"state": "unknown", "code": "code"},
            )

        expired_state = _make_oauth_state(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        with patch(
            "src.app.api.routes.connectors._load_oauth_state",
            new_callable=AsyncMock,
            return_value=expired_state,
        ):
            expired = await client.get(
                "/api/connectors/oauth/google/callback",
                params={"state": "expired", "code": "code"},
            )

        used_state = _make_oauth_state(status="consumed")
        with patch(
            "src.app.api.routes.connectors._load_oauth_state",
            new_callable=AsyncMock,
            return_value=used_state,
        ):
            used = await client.get(
                "/api/connectors/oauth/google/callback",
                params={"state": "used", "code": "code"},
            )

        provider_state = _make_oauth_state()
        with patch(
            "src.app.api.routes.connectors._load_oauth_state",
            new_callable=AsyncMock,
            return_value=provider_state,
        ):
            provider_error = await client.get(
                "/api/connectors/oauth/google/callback",
                params={"state": "provider", "error": "access_denied"},
            )

        missing_code_state = _make_oauth_state()
        with patch(
            "src.app.api.routes.connectors._load_oauth_state",
            new_callable=AsyncMock,
            return_value=missing_code_state,
        ):
            missing_code = await client.get(
                "/api/connectors/oauth/google/callback",
                params={"state": "missing-code"},
            )

    assert "connector=google" in invalid.headers["location"]
    assert "error=invalid_state" in invalid.headers["location"]
    assert expired_state.status == "failed"
    assert "error=expired_state" in expired.headers["location"]
    assert used_state.status == "failed"
    assert "error=expired_state" in used.headers["location"]
    assert provider_state.error_message == "provider_denied"
    assert "error=provider_denied" in provider_error.headers["location"]
    assert missing_code_state.error_message == "missing_code"
    assert "error=missing_code" in missing_code.headers["location"]
    assert mock_session.commit.await_count == 4


async def test_google_oauth_callback_exchange_failure_is_audited_and_redirected():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    oauth_state = _make_oauth_state()

    with (
        patch(
            "src.app.api.routes.connectors._load_oauth_state",
            new_callable=AsyncMock,
            return_value=oauth_state,
        ),
        patch(
            "src.app.api.routes.connectors._exchange_google_code",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("token endpoint unavailable"),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/connectors/oauth/google/callback",
                params={"state": "valid", "code": "code"},
            )

    assert response.status_code == 307
    assert "error=oauth_exchange_failed" in response.headers["location"]
    assert oauth_state.status == "failed"
    assert oauth_state.error_message == "oauth_exchange_failed"
    audit = next(
        call.args[0]
        for call in mock_session.add.await_args_list
        if isinstance(call.args[0], AuditEvent)
    )
    assert audit.event_type == "connector.oauth_failed"
    assert audit.metadata_["reason"] == "oauth_exchange_failed"
    assert audit.metadata_["error_type"] == "ConnectError"
    mock_session.commit.assert_awaited_once()


async def test_update_connector_updates_operator_preferences_and_audits_fields():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    account = _make_account()

    with patch(
        "src.app.api.routes.connectors.repo_update_connector_account",
        new_callable=AsyncMock,
        return_value=account,
    ) as update_account:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/connectors/accounts/{account.id}",
                json={
                    "display_name": "Primary inbox",
                    "background_access": True,
                    "sync_enabled": False,
                },
            )

    assert response.status_code == 200
    kwargs = update_account.await_args.kwargs
    assert kwargs["display_name"] == "Primary inbox"
    assert kwargs["background_access"] is True
    assert kwargs["sync_enabled"] is False
    assert "encrypted_refresh_token" not in kwargs
    assert "metadata" not in kwargs
    audit = next(
        call.args[0]
        for call in mock_session.add.await_args_list
        if isinstance(call.args[0], AuditEvent)
    )
    assert audit.metadata_["changed_fields"] == [
        "background_access",
        "display_name",
        "sync_enabled",
    ]
    assert audit.metadata_["background_access"] is True
    mock_session.commit.assert_awaited_once()


async def test_update_connector_not_found_paths_and_path_validation():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    account_id = uuid.uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch(
            "src.app.api.routes.connectors.repo_update_connector_account",
            new_callable=AsyncMock,
            return_value=None,
        ):
            missing_during_update = await client.patch(
                f"/api/connectors/accounts/{account_id}",
                json={"display_name": "Missing"},
            )

        secret_injection = await client.patch(
            f"/api/connectors/accounts/{account_id}",
            json={"refresh_token": "untrusted-token"},
        )
        invalid_id = await client.patch(
            "/api/connectors/accounts/not-a-uuid",
            json={"display_name": "Invalid"},
        )

    assert missing_during_update.status_code == 404
    assert secret_injection.status_code == 422
    assert invalid_id.status_code == 422
    mock_session.commit.assert_not_awaited()


async def test_disconnect_google_revokes_token_then_audits_and_purges():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    account = _make_account()
    account.encrypted_refresh_token = "v1:encrypted-refresh"
    revoke_response = MagicMock()
    context_manager, http_client = _mock_http_client(response=revoke_response)

    with (
        patch(
            "src.app.api.routes.connectors.repo_get_connector_account",
            new_callable=AsyncMock,
            return_value=account,
        ),
        patch("src.app.api.routes.connectors.get_settings", return_value=_oauth_settings()),
        patch(
            "src.app.api.routes.connectors.decrypt_secret", return_value="raw-refresh"
        ) as decrypt,
        patch("src.app.api.routes.connectors.httpx.AsyncClient", return_value=context_manager),
        patch(
            "src.app.api.routes.connectors.repo_purge_connector_account",
            new_callable=AsyncMock,
            return_value=True,
        ) as purge,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/connectors/accounts/{account.id}")

    assert response.status_code == 204
    decrypt.assert_called_once_with(
        "v1:encrypted-refresh",
        key=_oauth_settings().connector_token_encryption_key,
    )
    http_client.post.assert_awaited_once_with(
        connectors._GOOGLE_REVOKE_URL,
        data={"token": "raw-refresh"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    revoke_response.raise_for_status.assert_called_once()
    purge.assert_awaited_once_with(mock_session, account_id=account.id, user_id="owner")
    audit = next(
        call.args[0]
        for call in mock_session.add.await_args_list
        if isinstance(call.args[0], AuditEvent)
    )
    assert audit.event_type == "connector.account_disconnected_and_purged"
    mock_session.commit.assert_awaited_once()


async def test_disconnect_revocation_failure_preserves_local_data():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    account = _make_account()
    account.encrypted_refresh_token = "v1:encrypted-refresh"
    revoke_response = MagicMock()
    revoke_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "revocation failed",
        request=httpx.Request("POST", connectors._GOOGLE_REVOKE_URL),
        response=httpx.Response(503),
    )
    context_manager, _ = _mock_http_client(response=revoke_response)

    with (
        patch(
            "src.app.api.routes.connectors.repo_get_connector_account",
            new_callable=AsyncMock,
            return_value=account,
        ),
        patch("src.app.api.routes.connectors.get_settings", return_value=_oauth_settings()),
        patch("src.app.api.routes.connectors.decrypt_secret", return_value="raw-refresh"),
        patch("src.app.api.routes.connectors.httpx.AsyncClient", return_value=context_manager),
        patch(
            "src.app.api.routes.connectors.repo_purge_connector_account",
            new_callable=AsyncMock,
        ) as purge,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/connectors/accounts/{account.id}")

    assert response.status_code == 502
    assert "No local connector data was deleted" in response.json()["detail"]
    purge.assert_not_awaited()
    mock_session.commit.assert_not_awaited()


async def test_disconnect_handles_missing_token_non_google_and_purge_race_paths():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    account_id = uuid.uuid4()
    tokenless_google = _make_account(account_id=account_id)
    custom = _make_account(account_id=account_id)
    custom.connector_type = "notion"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch(
            "src.app.api.routes.connectors.repo_get_connector_account",
            new_callable=AsyncMock,
            return_value=None,
        ):
            missing = await client.delete(f"/api/connectors/accounts/{account_id}")

        with (
            patch(
                "src.app.api.routes.connectors.repo_get_connector_account",
                new_callable=AsyncMock,
                return_value=tokenless_google,
            ),
            patch(
                "src.app.api.routes.connectors.repo_purge_connector_account",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            tokenless = await client.delete(f"/api/connectors/accounts/{account_id}")

        with (
            patch(
                "src.app.api.routes.connectors.repo_get_connector_account",
                new_callable=AsyncMock,
                return_value=custom,
            ),
            patch(
                "src.app.api.routes.connectors.repo_purge_connector_account",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            purge_race = await client.delete(f"/api/connectors/accounts/{account_id}")

    assert missing.status_code == 404
    assert tokenless.status_code == 204
    assert purge_race.status_code == 404
    assert mock_session.commit.await_count == 1


async def test_sync_failure_marks_job_and_account_error_and_clamps_minimum():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    account = _make_account()
    job = _make_job(account_id=account.id)
    job.status = "failed"
    job.document_count = None
    job.error_message = "Connector sync failed"
    job.metadata_ = None
    job.started_at = None
    job.completed_at = None

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
            side_effect=RuntimeError("provider secret must not be persisted"),
        ) as sync_account,
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
                json={"sync_type": "full", "max_items": 0},
            )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["document_count"] == 0
    assert response.json()["metadata"] == {}
    assert response.json()["started_at"] is None
    sync_account.assert_awaited_once()
    assert sync_account.await_args.kwargs["max_items"] == 1
    update_job.assert_awaited_once_with(
        mock_session,
        job_id=job.id,
        status="failed",
        error_message="Connector sync failed",
    )
    update_account.assert_awaited_once_with(
        mock_session,
        account_id=account.id,
        user_id="owner",
        status="error",
    )
    audit = next(
        call.args[0]
        for call in mock_session.add.await_args_list
        if isinstance(call.args[0], AuditEvent)
    )
    assert audit.event_type == "connector.sync_failed"
    assert audit.metadata_["error_type"] == "RuntimeError"
    assert "provider secret" not in response.text
    assert "provider secret" not in str(audit.metadata_)
    mock_session.commit.assert_awaited_once()


async def test_sync_missing_account_and_request_validation_boundaries():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    account_id = uuid.uuid4()

    with patch(
        "src.app.api.routes.connectors.repo_get_connector_account",
        new_callable=AsyncMock,
        return_value=None,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            missing = await client.post(
                f"/api/connectors/accounts/{account_id}/sync",
                json={},
            )
            invalid_id = await client.post(
                "/api/connectors/accounts/not-a-uuid/sync",
                json={},
            )
            invalid_body = await client.post(
                f"/api/connectors/accounts/{account_id}/sync",
                json={"max_items": "many"},
            )

    assert missing.status_code == 404
    assert invalid_id.status_code == 422
    assert invalid_body.status_code == 422


async def test_lists_sync_jobs_and_documents_with_filters_and_pagination():
    mock_session = AsyncMock()
    app = _build_app(mock_session, external_subject="provider-owner")
    account_id = uuid.uuid4()
    job = _make_job(account_id=account_id)
    document = _make_document(account_id=account_id)

    with (
        patch(
            "src.app.api.routes.connectors.repo_list_connector_sync_jobs",
            new_callable=AsyncMock,
            return_value=[job],
        ) as list_jobs,
        patch(
            "src.app.api.routes.connectors.repo_list_connector_documents",
            new_callable=AsyncMock,
            return_value=([document], 7),
        ) as list_documents,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            jobs_response = await client.get(
                "/api/connectors/sync-jobs",
                params={"account_id": str(account_id), "limit": 1},
            )
            documents_response = await client.get(
                "/api/connectors/documents",
                params={
                    "account_id": str(account_id),
                    "source_type": "gmail_message",
                    "search": "quarterly",
                    "limit": 2,
                    "offset": 4,
                },
            )

    assert jobs_response.status_code == 200
    assert jobs_response.json()[0]["document_count"] == 12
    list_jobs.assert_awaited_once_with(
        mock_session,
        user_id="provider-owner",
        account_id=account_id,
        limit=1,
    )
    assert documents_response.status_code == 200
    body = documents_response.json()
    assert body["items"][0]["external_id"] == "message-1"
    assert body["items"][0]["metadata"] == {"labels": ["important"]}
    assert body["total"] == 7
    assert body["page"] == 3
    list_documents.assert_awaited_once_with(
        mock_session,
        user_id="provider-owner",
        limit=2,
        offset=4,
        account_id=account_id,
        source_type="gmail_message",
        search="quarterly",
    )


async def test_list_query_validation_rejects_out_of_bounds_values():
    mock_session = AsyncMock()
    app = _build_app(mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        jobs_zero = await client.get("/api/connectors/sync-jobs", params={"limit": 0})
        jobs_too_many = await client.get("/api/connectors/sync-jobs", params={"limit": 101})
        docs_zero = await client.get("/api/connectors/documents", params={"limit": 0})
        docs_too_many = await client.get("/api/connectors/documents", params={"limit": 101})
        docs_negative = await client.get("/api/connectors/documents", params={"offset": -1})
        docs_bad_account = await client.get(
            "/api/connectors/documents",
            params={"account_id": "bad-id"},
        )

    assert {
        jobs_zero.status_code,
        jobs_too_many.status_code,
        docs_zero.status_code,
        docs_too_many.status_code,
        docs_negative.status_code,
        docs_bad_account.status_code,
    } == {422}
