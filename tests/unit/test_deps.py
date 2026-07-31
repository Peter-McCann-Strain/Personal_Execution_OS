"""Self-hosted local-owner dependency tests."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import SecretStr

from src.app.api.deps import (
    Principal,
    get_anthropic_client,
    get_current_principal,
    get_db,
    get_llm_provider,
    scope_session_to_principal,
    verify_api_key,
)
from src.app.core.llm import DisabledLLMProvider


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        chat_api_key=SecretStr("correct-key"),
        first_owner_user_id="00000000-0000-0000-0000-000000000010",
        first_account_id="00000000-0000-0000-0000-000000000001",
    )


def _request() -> MagicMock:
    request = MagicMock()
    request.headers = {}
    return request


@pytest.mark.asyncio
async def test_verify_api_key_resolves_local_owner() -> None:
    request = _request()
    with patch("src.app.api.deps.get_settings", return_value=_settings()):
        subject = await verify_api_key(request, api_key="correct-key")

    assert subject == "owner"
    assert request.state.principal.account_id == uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert request.state.principal.plan == "community"


@pytest.mark.asyncio
async def test_bearer_key_resolves_same_local_owner() -> None:
    request = _request()
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="correct-key")
    with patch("src.app.api.deps.get_settings", return_value=_settings()):
        principal = await get_current_principal(
            request=request,
            api_key=None,
            bearer_token=credentials,
        )

    assert principal.subject == "owner"
    assert principal.auth_method == "bearer"
    assert principal.external_subject is None


@pytest.mark.asyncio
async def test_external_or_missing_credentials_are_rejected() -> None:
    with (
        patch("src.app.api.deps.get_settings", return_value=_settings()),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_current_principal(
            request=_request(),
            api_key="not-the-owner-key",
            bearer_token=None,
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_db_applies_owner_scope() -> None:
    session = AsyncMock()
    session.info = {}
    principal = Principal(
        subject="owner",
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
        account_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        role="owner",
        plan="community",
        scopes=("account:user",),
        auth_method="api_key",
    )
    request = _request()
    request.state.principal = principal

    async def fake_get_session():
        yield session

    with patch("src.app.api.deps.db_get_session", fake_get_session):
        sessions = [item async for item in get_db(request)]

    assert sessions == [session]
    assert session.info["account_id"] == principal.account_id
    assert session.info["user_id"] == principal.user_id


def test_scope_session_to_principal_sets_rls_identity() -> None:
    session = MagicMock()
    session.info = {}
    principal = Principal(
        subject="owner",
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
        account_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        role="owner",
        plan="community",
        scopes=("account:user",),
        auth_method="api_key",
    )

    scope_session_to_principal(session, principal)

    assert session.info["principal"] is principal


def test_provider_dependencies_use_provider_state() -> None:
    request = _request()
    provider = MagicMock()
    provider.configured = True
    request.app.state.llm_provider = provider

    assert get_llm_provider(request) is provider
    assert get_anthropic_client(request) is provider


@pytest.mark.parametrize("dependency", [get_llm_provider, get_anthropic_client])
def test_provider_dependencies_return_clear_503_when_disabled(dependency) -> None:
    request = _request()
    request.app.state.llm_provider = DisabledLLMProvider()

    with pytest.raises(HTTPException) as exc_info:
        dependency(request)

    assert exc_info.value.status_code == 503
    assert "requires a model provider" in exc_info.value.detail
