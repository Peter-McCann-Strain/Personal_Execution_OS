"""FastAPI dependency injection for the self-hosted single-owner runtime."""

from __future__ import annotations

import hmac
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import get_settings
from src.app.core.llm import LLMProvider
from src.app.core.local_auth import hash_token, parse_session_cookie
from src.app.core.mcp_client import MCPClientManager
from src.app.core.request_security import trusted_origins
from src.app.persistence.database import get_session as db_get_session
from src.app.persistence.models import LocalAuthSession, LocalOwnerCredential

logger = structlog.get_logger()

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer_header = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    """The single local owner mapped onto the existing account-scoped schema."""

    subject: str
    user_id: UUID
    account_id: UUID
    role: str
    plan: str
    scopes: tuple[str, ...]
    auth_method: str
    external_subject: str | None = None


async def get_db(request: Request) -> AsyncGenerator[AsyncSession]:
    """Yield a database session scoped to the authenticated owner when present."""
    async for session in db_get_session():
        principal = getattr(getattr(request, "state", None), "principal", None)
        if isinstance(principal, Principal):
            scope_session_to_principal(session, principal)
        yield session


def scope_session_to_principal(session: AsyncSession, principal: Principal) -> None:
    """Attach local-owner identity for ORM filters and PostgreSQL RLS."""
    session.info["account_id"] = principal.account_id
    session.info["user_id"] = principal.user_id
    session.info["principal"] = principal


async def verify_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> str:
    """Verify the local owner credential."""
    principal = await get_current_principal(
        request=request,
        api_key=api_key,
        bearer_token=None,
    )
    return principal.subject


async def get_current_principal(
    request: Request,
    api_key: str | None = Security(_api_key_header),
    bearer_token: HTTPAuthorizationCredentials | None = Security(_bearer_header),
) -> Principal:
    """Resolve the local owner from an API-key or equivalent bearer header."""
    settings = get_settings()
    expected = settings.chat_api_key.get_secret_value()
    authorization = request.headers.get("Authorization", "")
    token = bearer_token.credentials if bearer_token is not None else ""
    if not token and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()

    supplied = api_key if api_key not in {None, ""} else token
    if (
        expected
        and supplied
        and hmac.compare_digest(
            supplied.encode("utf-8"),
            expected.encode("utf-8"),
        )
    ):
        return _store_principal(
            request,
            _owner_principal(auth_method="api_key" if api_key else "bearer"),
        )

    if not supplied:
        session_principal = await _verify_local_session(request)
        if session_principal is not None:
            return _store_principal(request, session_principal)

    logger.warning(
        "auth_failed",
        provided_key_present=bool(api_key),
        bearer_present=bool(token),
        owner_key_configured=bool(expected),
    )
    raise HTTPException(status_code=401, detail="Invalid or missing credentials")


def _store_principal(request: Request, principal: Principal) -> Principal:
    request.state.principal = principal
    return principal


def _owner_principal(*, auth_method: str) -> Principal:
    settings = get_settings()
    return Principal(
        subject="owner",
        user_id=UUID(str(settings.first_owner_user_id)),
        account_id=UUID(str(settings.first_account_id)),
        role="owner",
        plan="community",
        scopes=("account:user", "account:admin", "account:owner"),
        auth_method=auth_method,
    )


def validate_same_origin(request: Request) -> None:
    """Reject cross-origin cookie-authenticated unsafe requests."""
    origin = request.headers.get("Origin")
    if not origin:
        return
    settings = get_settings()
    allowed = trusted_origins(settings)
    if origin.rstrip("/") not in allowed:
        raise HTTPException(status_code=403, detail="Origin validation failed")


async def _verify_local_session(request: Request) -> Principal | None:
    """Validate signed cookie, server-side token, expiry, origin, and CSRF."""
    settings = get_settings()
    cookie_value = request.cookies.get(settings.auth_session_cookie_name, "")
    if not cookie_value:
        return None

    async for session in db_get_session():
        credential = await session.get(LocalOwnerCredential, 1)
        if credential is None:
            return None
        parsed = parse_session_cookie(
            cookie_value,
            signing_secret=credential.session_signing_secret,
        )
        if parsed is None:
            return None

        record = await session.get(LocalAuthSession, parsed.session_id)
        now = datetime.now(UTC)
        if (
            record is None
            or record.revoked_at is not None
            or record.expires_at <= now
            or not hmac.compare_digest(record.token_hash, hash_token(parsed.token))
        ):
            return None

        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            validate_same_origin(request)
            csrf_cookie = request.cookies.get(settings.auth_csrf_cookie_name, "")
            csrf_header = request.headers.get("X-CSRF-Token", "")
            if (
                not csrf_cookie
                or not csrf_header
                or not hmac.compare_digest(
                    csrf_cookie.encode("utf-8"),
                    csrf_header.encode("utf-8"),
                )
                or not hmac.compare_digest(record.csrf_token_hash, hash_token(csrf_header))
            ):
                raise HTTPException(status_code=403, detail="CSRF validation failed")

        record.last_seen_at = now
        await session.commit()
        return _owner_principal(auth_method="session")
    return None


async def revoke_current_session(request: Request) -> bool:
    """Revoke the current signed cookie session if it is valid."""
    settings = get_settings()
    cookie_value = request.cookies.get(settings.auth_session_cookie_name, "")
    if not cookie_value:
        return False
    async for session in db_get_session():
        credential = await session.get(LocalOwnerCredential, 1)
        if credential is None:
            return False
        parsed = parse_session_cookie(
            cookie_value,
            signing_secret=credential.session_signing_secret,
        )
        if parsed is None:
            return False
        record = await session.get(LocalAuthSession, parsed.session_id)
        if record is None:
            return False
        record.revoked_at = datetime.now(UTC)
        await session.commit()
        return True
    return False


def _scopes_for_role(role: str) -> tuple[str, ...]:
    """Retain account-scope semantics for internal authorization checks."""
    normalized = role.casefold()
    if normalized == "owner":
        return ("account:user", "account:admin", "account:owner")
    if normalized == "admin":
        return ("account:user", "account:admin")
    return ("account:user",)


def get_llm_provider(request: Request) -> LLMProvider:
    """Return a usable provider or a stable feature-unavailable response."""
    provider = getattr(request.app.state, "llm_provider", None)
    if provider is None or not bool(getattr(provider, "configured", True)):
        raise HTTPException(
            status_code=503,
            detail=(
                "This feature requires a model provider. Configure ANTHROPIC_API_KEY "
                "and LLM_PROVIDER=anthropic, then restart the service."
            ),
        )
    return provider


def get_anthropic_client(request: Request) -> Any:
    """Compatibility alias while route type hints migrate to LLMProvider."""
    provider = getattr(request.app.state, "llm_provider", None)
    if provider is not None:
        return get_llm_provider(request)
    client = getattr(request.app.state, "anthropic_client", None)
    if client is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "This feature requires a model provider. Configure ANTHROPIC_API_KEY "
                "and LLM_PROVIDER=anthropic, then restart the service."
            ),
        )
    return client


def get_mcp_manager(request: Request) -> MCPClientManager | None:
    """Get the optional MCP client manager."""
    return getattr(request.app.state, "mcp_manager", None)


__all__ = [
    "Principal",
    "get_anthropic_client",
    "get_current_principal",
    "get_db",
    "get_llm_provider",
    "get_mcp_manager",
    "revoke_current_session",
    "scope_session_to_principal",
    "validate_same_origin",
    "verify_api_key",
]
