"""Persisted connector-account and sync routes."""

from __future__ import annotations

import hashlib
import inspect
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import Principal, get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.config import get_settings
from src.app.core.exceptions import NotFoundError
from src.app.core.secret_box import (
    SecretBoxError,
    decrypt_secret,
    encrypt_secret,
    validate_secret_box_key,
)
from src.app.domain.services.connector_sync import (
    connector_account_metadata,
    connector_default_display_name,
    sync_connector_account,
)
from src.app.persistence.models import (
    AuditEvent,
    ConnectorAccount,
    ConnectorDocument,
    ConnectorOAuthState,
    ConnectorSyncJob,
)
from src.app.persistence.repositories.connectors import (
    create_connector_account as repo_create_connector_account,
)
from src.app.persistence.repositories.connectors import (
    create_connector_sync_job as repo_create_connector_sync_job,
)
from src.app.persistence.repositories.connectors import (
    get_connector_account as repo_get_connector_account,
)
from src.app.persistence.repositories.connectors import (
    list_connector_accounts as repo_list_connector_accounts,
)
from src.app.persistence.repositories.connectors import (
    list_connector_documents as repo_list_connector_documents,
)
from src.app.persistence.repositories.connectors import (
    list_connector_sync_jobs as repo_list_connector_sync_jobs,
)
from src.app.persistence.repositories.connectors import (
    purge_connector_account as repo_purge_connector_account,
)
from src.app.persistence.repositories.connectors import (
    update_connector_account as repo_update_connector_account,
)
from src.app.persistence.repositories.connectors import (
    update_connector_sync_job as repo_update_connector_sync_job,
)

router = APIRouter()

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_OAUTH_STATE_TTL_SECONDS = 600
_GOOGLE_CONNECTOR_SCOPES: dict[str, list[str]] = {
    "gmail": [
        "openid",
        "email",
        "https://www.googleapis.com/auth/gmail.readonly",
    ],
    "google_calendar": [
        "openid",
        "email",
        "https://www.googleapis.com/auth/calendar.events.readonly",
    ],
    "google_drive": [
        "openid",
        "email",
        "https://www.googleapis.com/auth/drive.readonly",
    ],
}


class ConnectorAccountDTO(BaseModel):
    id: str
    user_id: str
    connector_type: str
    display_name: str
    status: str
    scopes: list[str]
    has_refresh_token: bool
    token_last_rotated_at: str | None
    auto_use: bool
    background_access: bool
    sync_enabled: bool
    last_sync_at: str | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class ConnectorSyncJobDTO(BaseModel):
    id: str
    account_id: str
    sync_type: str
    status: str
    document_count: int
    error_message: str | None
    metadata: dict[str, Any]
    started_at: str | None
    completed_at: str | None
    created_at: str


class ConnectorDocumentDTO(BaseModel):
    id: str
    account_id: str
    external_id: str
    source_type: str
    title: str
    content: str
    source_url: str | None
    metadata: dict[str, Any]
    synced_at: str
    created_at: str
    updated_at: str


class UpdateConnectorAccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    auto_use: bool | None = None
    background_access: bool | None = None
    sync_enabled: bool | None = None


class SyncConnectorBody(BaseModel):
    sync_type: str = "incremental"
    max_items: int = 25


class StartGoogleOAuthResponse(BaseModel):
    auth_url: str
    state_expires_at: str


def _account_to_dto(account: ConnectorAccount) -> ConnectorAccountDTO:
    return ConnectorAccountDTO(
        id=str(account.id),
        user_id=account.user_id,
        connector_type=account.connector_type,
        display_name=account.display_name,
        status=account.status,
        scopes=[str(scope) for scope in account.scopes or []],
        has_refresh_token=bool(account.encrypted_refresh_token),
        token_last_rotated_at=(
            account.token_last_rotated_at.isoformat() if account.token_last_rotated_at else None
        ),
        auto_use=bool(account.auto_use),
        background_access=bool(account.background_access),
        sync_enabled=bool(account.sync_enabled),
        last_sync_at=account.last_sync_at.isoformat() if account.last_sync_at else None,
        metadata=account.metadata_ or {},
        created_at=account.created_at.isoformat(),
        updated_at=account.updated_at.isoformat(),
    )


def _job_to_dto(job: ConnectorSyncJob) -> ConnectorSyncJobDTO:
    return ConnectorSyncJobDTO(
        id=str(job.id),
        account_id=str(job.account_id),
        sync_type=job.sync_type,
        status=job.status,
        document_count=int(job.document_count or 0),
        error_message=job.error_message,
        metadata=job.metadata_ or {},
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        created_at=job.created_at.isoformat(),
    )


def _document_to_dto(document: ConnectorDocument) -> ConnectorDocumentDTO:
    return ConnectorDocumentDTO(
        id=str(document.id),
        account_id=str(document.account_id),
        external_id=document.external_id,
        source_type=document.source_type,
        title=document.title,
        content=document.content,
        source_url=document.source_url,
        metadata=document.metadata_ or {},
        synced_at=document.synced_at.isoformat(),
        created_at=document.created_at.isoformat(),
        updated_at=document.updated_at.isoformat(),
    )


def _connector_metadata(
    *,
    base: dict[str, Any] | None = None,
    oauth_subject: str | None = None,
    oauth_email: str | None = None,
) -> dict[str, Any]:
    metadata = dict(base or connector_account_metadata())
    if oauth_subject:
        metadata["oauth_subject"] = oauth_subject
    if oauth_email:
        metadata["oauth_email"] = oauth_email
    return metadata


def _encrypted_refresh_token(refresh_token: str | None) -> tuple[str | None, datetime | None]:
    if not refresh_token:
        return None, None
    settings = get_settings()
    return (
        encrypt_secret(
            refresh_token,
            key=settings.connector_token_encryption_key,
        ),
        datetime.now(UTC),
    )


async def _session_add(session: AsyncSession, instance: object) -> None:
    result = session.add(instance)
    if inspect.isawaitable(result):
        await result


async def _record_audit_event(
    session: AsyncSession,
    *,
    account_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    event_type: str,
    resource_type: str | None = "connector_account",
    resource_id: str | None = None,
    actor_type: str = "user",
    metadata: dict[str, Any] | None = None,
) -> None:
    await _session_add(
        session,
        AuditEvent(
            account_id=account_id,
            user_id=user_id,
            event_type=event_type,
            actor_type=actor_type,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_=metadata or {},
        ),
    )


def _principal_user_ref(principal: Principal) -> str:
    return principal.external_subject or principal.subject


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _google_redirect_uri() -> str:
    settings = get_settings()
    configured = settings.google_oauth_redirect_url.strip()
    if configured:
        return configured
    raise HTTPException(
        status_code=503,
        detail=(
            "Google OAuth requires GOOGLE_OAUTH_REDIRECT_URL to be set to this "
            "installation's callback URL."
        ),
    )


def _require_connector_encryption_key() -> None:
    settings = get_settings()
    try:
        validate_secret_box_key(settings.connector_token_encryption_key)
    except SecretBoxError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Google OAuth is disabled until CONNECTOR_TOKEN_ENCRYPTION_KEY "
                "is set to a random value of at least 32 bytes. Generate and "
                "store the key before connecting an account."
            ),
        ) from exc


def _frontend_oauth_redirect(
    *,
    connector_type: str,
    status: str,
    error: str | None = None,
) -> str:
    params = {
        "section": "integrations",
        "connector": connector_type,
        "status": status,
    }
    if error:
        params["error"] = error
    return f"/settings?{urlencode(params)}"


def _google_authorize_url(*, connector_type: str, state: str, redirect_uri: str) -> str:
    settings = get_settings()
    scopes = _GOOGLE_CONNECTOR_SCOPES[connector_type]
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"


async def _load_oauth_state(
    session: AsyncSession,
    *,
    state: str,
) -> ConnectorOAuthState | None:
    result = await session.execute(
        select(ConnectorOAuthState).where(ConnectorOAuthState.state_hash == _state_hash(state))
    )
    return result.scalar_one_or_none()


async def _scope_callback_session(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    user_id: str,
) -> None:
    session.info["account_id"] = account_id
    session.info["user_id"] = user_id
    await session.execute(
        text(
            "SELECT "
            "set_config('app.account_id', :account_id, true), "
            "set_config('app.user_id', :user_id, true)"
        ),
        {"account_id": str(account_id), "user_id": user_id},
    )


async def _exchange_google_code(*, code: str, redirect_uri: str) -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret.get_secret_value(),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            msg = "Google token response was not an object"
            raise ValueError(msg)
        return payload


def _google_id_claims(id_token: object) -> dict[str, str]:
    if not isinstance(id_token, str) or not id_token:
        return {}
    try:
        claims = jwt.decode(id_token, options={"verify_signature": False, "verify_aud": False})
    except jwt.PyJWTError:
        return {}
    return {
        key: str(value)
        for key, value in claims.items()
        if key in {"sub", "email"} and value is not None
    }


async def _upsert_oauth_connector_account(
    session: AsyncSession,
    *,
    oauth_state: ConnectorOAuthState,
    token_payload: dict[str, Any],
) -> ConnectorAccount:
    refresh_token = token_payload.get("refresh_token")
    claims = _google_id_claims(token_payload.get("id_token"))
    existing_accounts = await repo_list_connector_accounts(
        session,
        user_id=oauth_state.user_id,
        connector_type=oauth_state.connector_type,
    )
    existing = existing_accounts[0] if existing_accounts else None

    encrypted_refresh_token: str | None = None
    token_last_rotated_at: datetime | None = None
    if isinstance(refresh_token, str) and refresh_token:
        encrypted_refresh_token, token_last_rotated_at = _encrypted_refresh_token(refresh_token)
    elif existing is None:
        msg = "Google did not return a refresh token; reconnect with consent required."
        raise ValueError(msg)

    metadata = _connector_metadata(
        base=existing.metadata_ if existing is not None else None,
        oauth_subject=claims.get("sub"),
        oauth_email=claims.get("email"),
    )
    metadata["oauth_completed_at"] = datetime.now(UTC).isoformat()

    if existing is not None:
        updated = await repo_update_connector_account(
            session,
            account_id=existing.id,
            user_id=oauth_state.user_id,
            scopes=oauth_state.scopes or [],
            status="connected",
            sync_enabled=True,
            encrypted_refresh_token=encrypted_refresh_token,
            token_last_rotated_at=token_last_rotated_at,
            metadata=metadata,
        )
        if updated is None:
            msg = "Connector account disappeared during OAuth callback."
            raise ValueError(msg)
        return updated

    return await repo_create_connector_account(
        session,
        user_id=oauth_state.user_id,
        connector_type=oauth_state.connector_type,
        display_name=connector_default_display_name(oauth_state.connector_type),
        scopes=oauth_state.scopes or [],
        auto_use=True,
        background_access=False,
        sync_enabled=True,
        status="connected",
        encrypted_refresh_token=encrypted_refresh_token,
        token_last_rotated_at=token_last_rotated_at,
        metadata=metadata,
    )


@router.post("/connectors/oauth/google/start", response_model=StartGoogleOAuthResponse)
async def start_google_oauth(
    connector_type: str = Query(...),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> StartGoogleOAuthResponse:
    """Create an OAuth state and return the Google consent URL."""
    if connector_type not in _GOOGLE_CONNECTOR_SCOPES:
        raise HTTPException(status_code=400, detail="Unsupported Google connector")

    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret.get_secret_value():
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")
    _require_connector_encryption_key()

    state = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(seconds=_OAUTH_STATE_TTL_SECONDS)
    redirect_uri = _google_redirect_uri()
    oauth_state = ConnectorOAuthState(
        account_id=principal.account_id,
        user_id=_principal_user_ref(principal),
        connector_type=connector_type,
        state_hash=_state_hash(state),
        scopes=_GOOGLE_CONNECTOR_SCOPES[connector_type],
        redirect_uri=redirect_uri,
        status="pending",
        expires_at=expires_at,
    )
    await _session_add(session, oauth_state)
    await _record_audit_event(
        session,
        account_id=principal.account_id,
        user_id=principal.user_id,
        event_type="connector.oauth_started",
        resource_type="connector_oauth_state",
        resource_id=None,
        metadata={
            "connector_type": connector_type,
            "scopes": _GOOGLE_CONNECTOR_SCOPES[connector_type],
            "expires_at": expires_at.isoformat(),
        },
    )
    await session.commit()
    return StartGoogleOAuthResponse(
        auth_url=_google_authorize_url(
            connector_type=connector_type,
            state=state,
            redirect_uri=redirect_uri,
        ),
        state_expires_at=expires_at.isoformat(),
    )


@router.get("/connectors/oauth/google/callback")
async def google_oauth_callback(
    state: str = Query(...),
    code: str | None = Query(None),
    error: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Complete Google OAuth and store the encrypted refresh token."""
    oauth_state = await _load_oauth_state(session, state=state)
    if oauth_state is None:
        return RedirectResponse(
            _frontend_oauth_redirect(
                connector_type="google",
                status="error",
                error="invalid_state",
            )
        )

    if oauth_state.status != "pending" or oauth_state.expires_at <= datetime.now(UTC):
        oauth_state.status = "failed"
        oauth_state.error_message = "OAuth state expired or already used"
        await _record_audit_event(
            session,
            account_id=oauth_state.account_id,
            user_id=None,
            event_type="connector.oauth_failed",
            resource_type="connector_oauth_state",
            actor_type="system",
            metadata={
                "connector_type": oauth_state.connector_type,
                "user_ref": oauth_state.user_id,
                "reason": "expired_state",
            },
        )
        await session.commit()
        return RedirectResponse(
            _frontend_oauth_redirect(
                connector_type=oauth_state.connector_type,
                status="error",
                error="expired_state",
            )
        )

    if error or not code:
        failure_code = "provider_denied" if error else "missing_code"
        oauth_state.status = "failed"
        oauth_state.error_message = failure_code
        await _record_audit_event(
            session,
            account_id=oauth_state.account_id,
            user_id=None,
            event_type="connector.oauth_failed",
            resource_type="connector_oauth_state",
            actor_type="system",
            metadata={
                "connector_type": oauth_state.connector_type,
                "user_ref": oauth_state.user_id,
                "reason": failure_code,
            },
        )
        await session.commit()
        return RedirectResponse(
            _frontend_oauth_redirect(
                connector_type=oauth_state.connector_type,
                status="error",
                error=failure_code,
            )
        )

    try:
        token_payload = await _exchange_google_code(
            code=code,
            redirect_uri=oauth_state.redirect_uri,
        )
        await _scope_callback_session(
            session,
            account_id=oauth_state.account_id,
            user_id=oauth_state.user_id,
        )
        account = await _upsert_oauth_connector_account(
            session,
            oauth_state=oauth_state,
            token_payload=token_payload,
        )
        oauth_state.status = "consumed"
        oauth_state.consumed_at = datetime.now(UTC)
        await _record_audit_event(
            session,
            account_id=oauth_state.account_id,
            user_id=None,
            event_type="connector.oauth_completed",
            resource_id=str(account.id),
            actor_type="system",
            metadata={
                "connector_type": oauth_state.connector_type,
                "user_ref": oauth_state.user_id,
                "has_refresh_token": bool(account.encrypted_refresh_token),
            },
        )
        await session.commit()
    except Exception as exc:
        oauth_state.status = "failed"
        oauth_state.error_message = "oauth_exchange_failed"
        await _record_audit_event(
            session,
            account_id=oauth_state.account_id,
            user_id=None,
            event_type="connector.oauth_failed",
            resource_type="connector_oauth_state",
            actor_type="system",
            metadata={
                "connector_type": oauth_state.connector_type,
                "user_ref": oauth_state.user_id,
                "reason": "oauth_exchange_failed",
                "error_type": type(exc).__name__,
            },
        )
        await session.commit()
        return RedirectResponse(
            _frontend_oauth_redirect(
                connector_type=oauth_state.connector_type,
                status="error",
                error="oauth_exchange_failed",
            )
        )

    return RedirectResponse(
        _frontend_oauth_redirect(
            connector_type=oauth_state.connector_type,
            status="connected",
        )
    )


@router.get("/connectors/accounts", response_model=list[ConnectorAccountDTO])
async def list_connector_accounts(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> list[ConnectorAccountDTO]:
    """List persisted connector accounts."""
    user_id = _principal_user_ref(principal)
    accounts = await repo_list_connector_accounts(session, user_id=user_id)
    return [_account_to_dto(account) for account in accounts]


@router.patch("/connectors/accounts/{account_id}", response_model=ConnectorAccountDTO)
async def update_connector_account(
    account_id: uuid.UUID,
    body: UpdateConnectorAccountBody,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ConnectorAccountDTO:
    """Update operator-controlled connector preferences."""
    user_id = _principal_user_ref(principal)
    account = await repo_update_connector_account(
        session,
        account_id=account_id,
        user_id=user_id,
        display_name=body.display_name,
        auto_use=body.auto_use,
        background_access=body.background_access,
        sync_enabled=body.sync_enabled,
    )
    if account is None:
        raise NotFoundError(f"Connector account not found: {account_id}")
    fields_set: set[str] = set(
        getattr(body, "model_fields_set", getattr(body, "__fields_set__", set()))
    )
    await _record_audit_event(
        session,
        account_id=principal.account_id,
        user_id=principal.user_id,
        event_type="connector.account_updated",
        resource_id=str(account.id),
        metadata={
            "connector_type": account.connector_type,
            "changed_fields": sorted(str(field) for field in fields_set),
            "sync_enabled": body.sync_enabled,
            "background_access": body.background_access,
        },
    )
    await session.commit()
    return _account_to_dto(account)


@router.delete("/connectors/accounts/{account_id}", status_code=204)
async def disconnect_connector_account(
    account_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke provider access and permanently purge all local indexed copies."""
    user_id = _principal_user_ref(principal)
    account = await repo_get_connector_account(
        session,
        account_id=account_id,
        user_id=user_id,
    )
    if account is None:
        raise NotFoundError(f"Connector account not found: {account_id}")

    if account.connector_type.startswith("google") or account.connector_type == "gmail":
        encrypted_token = account.encrypted_refresh_token
        if encrypted_token:
            settings = get_settings()
            token = decrypt_secret(
                encrypted_token,
                key=settings.connector_token_encryption_key,
            )
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        _GOOGLE_REVOKE_URL,
                        data={"token": token},
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    response.raise_for_status()
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Google token revocation failed. No local connector data "
                        "was deleted; retry disconnect."
                    ),
                ) from exc

    await _record_audit_event(
        session,
        account_id=principal.account_id,
        user_id=principal.user_id,
        event_type="connector.account_disconnected_and_purged",
        resource_id=str(account.id),
        metadata={"connector_type": account.connector_type},
    )
    purged = await repo_purge_connector_account(
        session,
        account_id=account_id,
        user_id=user_id,
    )
    if not purged:
        raise NotFoundError(f"Connector account not found: {account_id}")
    await session.commit()
    return Response(status_code=204)


@router.post("/connectors/accounts/{account_id}/sync", response_model=ConnectorSyncJobDTO)
async def sync_connector(
    account_id: uuid.UUID,
    body: SyncConnectorBody,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ConnectorSyncJobDTO:
    """Run a connector sync immediately and persist indexed documents."""
    user_id = _principal_user_ref(principal)
    account = await repo_get_connector_account(session, account_id=account_id, user_id=user_id)
    if account is None:
        raise NotFoundError(f"Connector account not found: {account_id}")

    job = await repo_create_connector_sync_job(
        session,
        account_id=account_id,
        sync_type=body.sync_type,
        status="running",
    )
    try:
        document_count = await sync_connector_account(
            session,
            account=account,
            max_items=max(1, min(body.max_items, 100)),
        )
        await repo_update_connector_sync_job(
            session,
            job_id=job.id,
            status="completed",
            document_count=document_count,
        )
        await repo_update_connector_account(
            session,
            account_id=account_id,
            user_id=user_id,
            status="connected",
            last_sync_at=account.last_sync_at,
        )
        await _record_audit_event(
            session,
            account_id=principal.account_id,
            user_id=principal.user_id,
            event_type="connector.sync_completed",
            resource_id=str(account_id),
            metadata={
                "connector_type": account.connector_type,
                "sync_type": body.sync_type,
                "job_id": str(job.id),
                "document_count": document_count,
            },
        )
        await session.commit()
    except Exception as exc:
        safe_error = "Connector sync failed"
        await repo_update_connector_sync_job(
            session,
            job_id=job.id,
            status="failed",
            error_message=safe_error,
        )
        await repo_update_connector_account(
            session,
            account_id=account_id,
            user_id=user_id,
            status="error",
        )
        await _record_audit_event(
            session,
            account_id=principal.account_id,
            user_id=principal.user_id,
            event_type="connector.sync_failed",
            resource_id=str(account_id),
            metadata={
                "connector_type": account.connector_type,
                "sync_type": body.sync_type,
                "job_id": str(job.id),
                "error_type": type(exc).__name__,
            },
        )
        await session.commit()
    refreshed_job = (
        await repo_list_connector_sync_jobs(
            session,
            user_id=user_id,
            account_id=account_id,
            limit=1,
        )
    )[0]
    return _job_to_dto(refreshed_job)


@router.get("/connectors/sync-jobs", response_model=list[ConnectorSyncJobDTO])
async def list_connector_sync_jobs(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    account_id: uuid.UUID | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
) -> list[ConnectorSyncJobDTO]:
    """List connector sync history."""
    user_id = _principal_user_ref(principal)
    jobs = await repo_list_connector_sync_jobs(
        session,
        user_id=user_id,
        account_id=account_id,
        limit=limit,
    )
    return [_job_to_dto(job) for job in jobs]


@router.get("/connectors/documents", response_model=PaginatedResponse[ConnectorDocumentDTO])
async def list_connector_documents(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    account_id: uuid.UUID | None = Query(None),
    source_type: str | None = Query(None),
    search: str | None = Query(None),
) -> PaginatedResponse[ConnectorDocumentDTO]:
    """List normalized connector documents."""
    user_id = _principal_user_ref(principal)
    documents, total = await repo_list_connector_documents(
        session,
        user_id=user_id,
        limit=limit,
        offset=offset,
        account_id=account_id,
        source_type=source_type,
        search=search,
    )
    return paginate(
        items=[_document_to_dto(document) for document in documents],
        total=total,
        offset=offset,
        limit=limit,
    )
