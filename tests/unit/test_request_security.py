"""Regression tests for Host-header and browser-origin trust boundaries."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from src.app.api.deps import validate_same_origin
from src.app.config import Settings
from src.app.core.request_security import host_from_header, trusted_hosts, trusted_origins


def _production_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        app_env="production",
        app_port=8080,
        **overrides,
    )


def test_default_host_and_origin_policy_is_exact_and_local() -> None:
    settings = _production_settings()

    assert trusted_hosts(settings) == {"localhost", "127.0.0.1", "::1"}
    assert trusted_origins(settings) == {
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://[::1]:8080",
    }
    assert host_from_header("[::1]:8080") == "::1"
    assert host_from_header("attacker.example\\@localhost") is None


@pytest.mark.parametrize(
    "value",
    [
        "https://assistant.example.com",
        "assistant.example.com:443",
        "*.example.com",
        "::1",
        "assistant.example.com.",
        " assistant.example.com",
    ],
)
def test_public_hostname_rejects_urls_ports_wildcards_and_ipv6(value: str) -> None:
    with pytest.raises(ValueError, match="PUBLIC_HOSTNAME"):
        _production_settings(public_hostname=value)


def test_matching_untrusted_host_and_origin_cannot_pass_origin_validation() -> None:
    settings = _production_settings()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api/setup/initialize",
            "query_string": b"",
            "headers": [
                (b"host", b"attacker.example"),
                (b"origin", b"http://attacker.example"),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
        }
    )

    with (
        patch("src.app.api.deps.get_settings", return_value=settings),
        pytest.raises(HTTPException) as exc_info,
    ):
        validate_same_origin(request)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_malicious_host_is_rejected_before_setup_or_authenticated_mutation() -> None:
    from src.app.main import create_app

    settings = _production_settings()
    with patch("src.app.main.get_settings", return_value=settings):
        app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://attacker.example",
    ) as client:
        setup = await client.post(
            "/api/setup/initialize",
            json={"password": "correct horse battery staple"},
            headers={"Origin": "http://attacker.example"},
        )
        mutation = await client.post(
            "/api/auth/change-password",
            json={
                "current_password": "correct horse battery staple",
                "new_password": "another correct horse battery staple",
            },
            headers={
                "Origin": "http://attacker.example",
                "X-CSRF-Token": "not-a-real-token",
            },
            cookies={"peos_session": "not-a-real-session"},
        )

    assert setup.status_code == 400
    assert mutation.status_code == 400


@pytest.mark.asyncio
async def test_create_app_accepts_only_configured_public_hostname() -> None:
    from src.app.main import create_app

    settings = _production_settings(public_hostname="assistant.example.com")
    with patch("src.app.main.get_settings", return_value=settings):
        app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://assistant.example.com",
    ) as allowed_client:
        allowed = await allowed_client.get("/healthz")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://other.example.com",
    ) as rejected_client:
        rejected = await rejected_client.get("/healthz")

    assert allowed.status_code == 200
    assert rejected.status_code == 400
