"""First-run setup and local-owner browser session endpoints."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import (
    Principal,
    get_current_principal,
    get_db,
    revoke_current_session,
    validate_same_origin,
)
from src.app.api.rate_limiting import rate_limit_allowed
from src.app.config import Settings, get_settings
from src.app.core.local_auth import (
    build_session_cookie,
    generate_csrf_token,
    generate_session_secret,
    generate_session_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from src.app.persistence.models import LocalAuthSession, LocalOwnerCredential

router = APIRouter()


class SetupStatusResponse(BaseModel):
    initialized: bool
    auth_mode: str = "local_owner"


class PasswordBody(BaseModel):
    password: str = Field(min_length=12, max_length=256)


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=12, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class CurrentPasswordBody(BaseModel):
    current_password: str = Field(min_length=12, max_length=256)


class AuthSessionResponse(BaseModel):
    authenticated: bool = True
    subject: str = "owner"
    role: str = "owner"
    expires_at: str | None = None


async def _credential_exists(session: AsyncSession) -> bool:
    result = await session.execute(select(LocalOwnerCredential.id).limit(1))
    return result.scalar_one_or_none() is not None


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded[:80]
    return request.client.host[:80] if request.client else "unknown"


def _set_auth_cookies(
    response: Response,
    *,
    settings: Settings,
    session: LocalAuthSession,
    token: str,
    csrf_token: str,
    signing_secret: str,
) -> None:
    max_age = max(int((session.expires_at - datetime.now(UTC)).total_seconds()), 1)
    response.set_cookie(
        key=settings.auth_session_cookie_name,
        value=build_session_cookie(session.id, token, signing_secret=signing_secret),
        max_age=max_age,
        expires=session.expires_at,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=settings.auth_csrf_cookie_name,
        value=csrf_token,
        max_age=max_age,
        expires=session.expires_at,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_auth_cookies(response: Response, *, settings: Settings) -> None:
    response.delete_cookie(
        settings.auth_session_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        settings.auth_csrf_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=False,
        samesite="lax",
    )


async def _create_browser_session(
    session: AsyncSession,
    *,
    request: Request,
    response: Response,
    credential: LocalOwnerCredential,
    settings: Settings,
) -> LocalAuthSession:
    raw_token = generate_session_token()
    csrf_token = generate_csrf_token()
    now = datetime.now(UTC)
    record = LocalAuthSession(
        id=uuid.uuid4(),
        credential_id=credential.id,
        token_hash=hash_token(raw_token),
        csrf_token_hash=hash_token(csrf_token),
        expires_at=now + timedelta(hours=settings.auth_session_ttl_hours),
        last_seen_at=now,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:1000] or None,
    )
    session.add(record)
    await session.commit()
    _set_auth_cookies(
        response,
        settings=settings,
        session=record,
        token=raw_token,
        csrf_token=csrf_token,
        signing_secret=credential.session_signing_secret,
    )
    return record


@router.get("/setup/status", response_model=SetupStatusResponse)
async def setup_status(session: AsyncSession = Depends(get_db)) -> SetupStatusResponse:
    """Return whether the one-time local-owner setup has completed."""
    return SetupStatusResponse(initialized=await _credential_exists(session))


@router.post("/setup/initialize", response_model=AuthSessionResponse, status_code=201)
async def initialize_local_owner(
    body: PasswordBody,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> AuthSessionResponse:
    """Create the singleton owner credential and sign in exactly once."""
    validate_same_origin(request)
    if await _credential_exists(session):
        raise HTTPException(status_code=409, detail="Setup has already been completed")

    credential = LocalOwnerCredential(
        id=1,
        password_hash=await asyncio.to_thread(hash_password, body.password),
        session_signing_secret=generate_session_secret(),
        failed_login_count=0,
        initialized_at=datetime.now(UTC),
        password_updated_at=datetime.now(UTC),
    )
    session.add(credential)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Setup has already been completed") from exc

    auth_session = await _create_browser_session(
        session,
        request=request,
        response=response,
        credential=credential,
        settings=get_settings(),
    )
    return AuthSessionResponse(expires_at=auth_session.expires_at.isoformat())


@router.post("/auth/login", response_model=AuthSessionResponse)
async def login(
    body: PasswordBody,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> AuthSessionResponse:
    """Verify the owner password and issue a signed, revocable session."""
    validate_same_origin(request)
    settings = get_settings()
    allowed = await rate_limit_allowed(
        f"auth:login:{_client_ip(request)}",
        limit=settings.auth_login_attempts,
        window_seconds=settings.auth_login_window_seconds,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many login attempts")

    credential = await session.get(LocalOwnerCredential, 1)
    if credential is None:
        raise HTTPException(status_code=409, detail="Complete setup before signing in")

    now = datetime.now(UTC)
    if credential.locked_until is not None and credential.locked_until > now:
        retry_after = max(int((credential.locked_until - now).total_seconds()), 1)
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts",
            headers={"Retry-After": str(retry_after)},
        )

    password_valid = await asyncio.to_thread(
        verify_password,
        credential.password_hash,
        body.password,
    )
    if not password_valid:
        credential.failed_login_count += 1
        if credential.failed_login_count >= settings.auth_login_attempts:
            credential.failed_login_count = 0
            credential.locked_until = now + timedelta(seconds=settings.auth_login_window_seconds)
        await session.commit()
        # Keep response and timing independent of credential details.
        raise HTTPException(status_code=401, detail="Invalid credentials")

    credential.failed_login_count = 0
    credential.locked_until = None
    if password_needs_rehash(credential.password_hash):
        credential.password_hash = await asyncio.to_thread(hash_password, body.password)
        credential.password_updated_at = now

    auth_session = await _create_browser_session(
        session,
        request=request,
        response=response,
        credential=credential,
        settings=settings,
    )
    return AuthSessionResponse(expires_at=auth_session.expires_at.isoformat())


@router.get("/auth/session", response_model=AuthSessionResponse)
async def current_session(
    principal: Principal = Depends(get_current_principal),
) -> AuthSessionResponse:
    """Return the authenticated local-owner identity."""
    return AuthSessionResponse(
        subject=principal.subject,
        role=principal.role,
    )


async def _verify_credential_mutation(
    *,
    request: Request,
    session: AsyncSession,
    current_password: str,
) -> tuple[LocalOwnerCredential, Settings]:
    validate_same_origin(request)
    settings = get_settings()
    allowed = await rate_limit_allowed(
        f"auth:credential-mutation:{_client_ip(request)}",
        limit=settings.auth_login_attempts,
        window_seconds=settings.auth_login_window_seconds,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many authentication attempts")

    credential = await session.get(LocalOwnerCredential, 1)
    if credential is None:
        raise HTTPException(status_code=409, detail="Complete setup before changing credentials")
    password_valid = await asyncio.to_thread(
        verify_password,
        credential.password_hash,
        current_password,
    )
    if not password_valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return credential, settings


async def _rotate_and_revoke_all_sessions(
    *,
    response: Response,
    session: AsyncSession,
    credential: LocalOwnerCredential,
    settings: Settings,
) -> Response:
    now = datetime.now(UTC)
    credential.session_signing_secret = generate_session_secret()
    await session.execute(
        update(LocalAuthSession)
        .where(
            LocalAuthSession.credential_id == credential.id,
            LocalAuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await session.commit()
    _clear_auth_cookies(response, settings=settings)
    response.status_code = 204
    return response


@router.post("/auth/change-password", status_code=204)
async def change_password(
    body: ChangePasswordBody,
    request: Request,
    response: Response,
    _principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Change the owner password and invalidate every browser session."""
    del _principal
    credential, settings = await _verify_credential_mutation(
        request=request,
        session=session,
        current_password=body.current_password,
    )
    credential.password_hash = await asyncio.to_thread(hash_password, body.new_password)
    credential.password_updated_at = datetime.now(UTC)
    credential.failed_login_count = 0
    credential.locked_until = None
    return await _rotate_and_revoke_all_sessions(
        response=response,
        session=session,
        credential=credential,
        settings=settings,
    )


@router.post("/auth/sessions/revoke-all", status_code=204)
async def revoke_all_sessions(
    body: CurrentPasswordBody,
    request: Request,
    response: Response,
    _principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Invalidate every browser session while retaining the current password."""
    del _principal
    credential, settings = await _verify_credential_mutation(
        request=request,
        session=session,
        current_password=body.current_password,
    )
    return await _rotate_and_revoke_all_sessions(
        response=response,
        session=session,
        credential=credential,
        settings=settings,
    )


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    _principal: Principal = Depends(get_current_principal),
) -> Response:
    """Revoke the current browser session and expire both cookies."""
    del _principal
    await revoke_current_session(request)
    settings = get_settings()
    _clear_auth_cookies(response, settings=settings)
    response.status_code = 204
    return response
