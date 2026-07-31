"""Focused first-run and cookie-session API tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.sql.dml import Update

from src.app.api.deps import get_db
from src.app.api.routes.auth import router
from src.app.persistence.models import LocalAuthSession, LocalOwnerCredential


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self) -> None:
        self.credential: LocalOwnerCredential | None = None
        self.sessions: dict[object, LocalAuthSession] = {}
        self.commit = AsyncMock()
        self.flush = AsyncMock()
        self.rollback = AsyncMock()

    async def execute(self, statement):
        if isinstance(statement, Update):
            for record in self.sessions.values():
                record.revoked_at = datetime.now(UTC)
            return _ScalarResult(None)
        return _ScalarResult(self.credential.id if self.credential else None)

    async def get(self, model, key):
        if model is LocalOwnerCredential:
            return self.credential if key == 1 else None
        if model is LocalAuthSession:
            return self.sessions.get(key)
        return None

    def add(self, record) -> None:
        if isinstance(record, LocalOwnerCredential):
            self.credential = record
        elif isinstance(record, LocalAuthSession):
            self.sessions[record.id] = record


def _build_app(session: _FakeSession) -> FastAPI:
    app = FastAPI()

    async def database() -> AsyncGenerator[_FakeSession]:
        yield session

    app.dependency_overrides[get_db] = database
    app.include_router(router, prefix="/api")
    return app


async def test_first_run_initialize_session_csrf_and_logout() -> None:
    session = _FakeSession()

    async def database():
        yield session

    with (
        patch("src.app.api.routes.auth.rate_limit_allowed", return_value=True),
        patch("src.app.api.deps.db_get_session", database),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=_build_app(session)),
            base_url="http://test",
        ) as client:
            status = await client.get("/api/setup/status")
            initialized = await client.post(
                "/api/setup/initialize",
                json={"password": "correct horse battery staple"},
                headers={"Origin": "http://test"},
            )
            status_after = await client.get("/api/setup/status")
            duplicate = await client.post(
                "/api/setup/initialize",
                json={"password": "another secure password"},
                headers={"Origin": "http://test"},
            )
            current = await client.get("/api/auth/session")
            csrf_missing = await client.post(
                "/api/auth/logout",
                headers={"Origin": "http://test"},
            )
            csrf_token = client.cookies.get("peos_csrf")
            logout = await client.post(
                "/api/auth/logout",
                headers={
                    "Origin": "http://test",
                    "X-CSRF-Token": csrf_token or "",
                },
            )

    assert status.json() == {"initialized": False, "auth_mode": "local_owner"}
    assert initialized.status_code == 201
    assert initialized.cookies.get("peos_session")
    assert initialized.cookies.get("peos_csrf")
    assert "HttpOnly" in initialized.headers.get_list("set-cookie")[0]
    assert status_after.json()["initialized"] is True
    assert duplicate.status_code == 409
    assert current.status_code == 200
    assert current.json()["subject"] == "owner"
    assert csrf_missing.status_code == 403
    assert logout.status_code == 204
    assert any(record.revoked_at is not None for record in session.sessions.values())


async def test_login_rejects_wrong_password_and_cross_origin() -> None:
    session = _FakeSession()
    app = _build_app(session)
    with patch("src.app.api.routes.auth.rate_limit_allowed", return_value=True):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/setup/initialize",
                json={"password": "correct horse battery staple"},
                headers={"Origin": "http://test"},
            )
            wrong = await client.post(
                "/api/auth/login",
                json={"password": "this is the wrong password"},
                headers={"Origin": "http://test"},
            )
            cross_origin = await client.post(
                "/api/auth/login",
                json={"password": "correct horse battery staple"},
                headers={"Origin": "https://attacker.example"},
            )

    assert wrong.status_code == 401
    assert cross_origin.status_code == 403


async def test_login_rate_limit_fails_closed() -> None:
    session = _FakeSession()
    app = _build_app(session)
    with patch("src.app.api.routes.auth.rate_limit_allowed", return_value=False):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/auth/login",
                json={"password": "correct horse battery staple"},
                headers={"Origin": "http://test"},
            )

    assert response.status_code == 429


async def test_change_password_rejects_wrong_password_and_rate_limit() -> None:
    session = _FakeSession()

    async def database():
        yield session

    app = _build_app(session)
    with (
        patch("src.app.api.routes.auth.rate_limit_allowed", return_value=True),
        patch("src.app.api.deps.db_get_session", database),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/setup/initialize",
                json={"password": "correct horse battery staple"},
                headers={"Origin": "http://test"},
            )
            csrf = client.cookies.get("peos_csrf") or ""
            wrong = await client.post(
                "/api/auth/change-password",
                json={
                    "current_password": "this is the wrong password",
                    "new_password": "a completely new secure password",
                },
                headers={"Origin": "http://test", "X-CSRF-Token": csrf},
            )

    assert wrong.status_code == 401

    with (
        patch("src.app.api.routes.auth.rate_limit_allowed", return_value=False),
        patch("src.app.api.deps.db_get_session", database),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies={
                "peos_session": client.cookies.get("peos_session") or "",
                "peos_csrf": csrf,
            },
        ) as limited_client:
            limited = await limited_client.post(
                "/api/auth/change-password",
                json={
                    "current_password": "correct horse battery staple",
                    "new_password": "a completely new secure password",
                },
                headers={"Origin": "http://test", "X-CSRF-Token": csrf},
            )

    assert limited.status_code == 429


async def test_change_password_revokes_all_sessions_and_forces_login() -> None:
    session = _FakeSession()

    async def database():
        yield session

    app = _build_app(session)
    with (
        patch("src.app.api.routes.auth.rate_limit_allowed", return_value=True),
        patch("src.app.api.deps.db_get_session", database),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as first_client:
            await first_client.post(
                "/api/setup/initialize",
                json={"password": "correct horse battery staple"},
                headers={"Origin": "http://test"},
            )
            old_cookie = first_client.cookies.get("peos_session") or ""
            csrf = first_client.cookies.get("peos_csrf") or ""
            changed = await first_client.post(
                "/api/auth/change-password",
                json={
                    "current_password": "correct horse battery staple",
                    "new_password": "a completely new secure password",
                },
                headers={"Origin": "http://test", "X-CSRF-Token": csrf},
            )

        assert changed.status_code == 204
        assert all(record.revoked_at is not None for record in session.sessions.values())

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies={"peos_session": old_cookie},
        ) as old_client:
            invalidated = await old_client.get("/api/auth/session")
            old_login = await old_client.post(
                "/api/auth/login",
                json={"password": "correct horse battery staple"},
                headers={"Origin": "http://test"},
            )
            new_login = await old_client.post(
                "/api/auth/login",
                json={"password": "a completely new secure password"},
                headers={"Origin": "http://test"},
            )

    assert invalidated.status_code == 401
    assert old_login.status_code == 401
    assert new_login.status_code == 200


async def test_revoke_all_sessions_requires_password_and_rotates_secret() -> None:
    session = _FakeSession()

    async def database():
        yield session

    app = _build_app(session)
    with (
        patch("src.app.api.routes.auth.rate_limit_allowed", return_value=True),
        patch("src.app.api.deps.db_get_session", database),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/setup/initialize",
                json={"password": "correct horse battery staple"},
                headers={"Origin": "http://test"},
            )
            previous_secret = session.credential.session_signing_secret
            csrf = client.cookies.get("peos_csrf") or ""
            revoked = await client.post(
                "/api/auth/sessions/revoke-all",
                json={"current_password": "correct horse battery staple"},
                headers={"Origin": "http://test", "X-CSRF-Token": csrf},
            )

    assert revoked.status_code == 204
    assert session.credential.session_signing_secret != previous_secret
    assert all(record.revoked_at is not None for record in session.sessions.values())
