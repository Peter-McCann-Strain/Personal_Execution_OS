"""Tests for account product routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import Principal, get_current_principal, get_db
from src.app.api.routes.account import router
from src.app.persistence.models import DataExport

ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


def _principal() -> Principal:
    return Principal(
        subject="user_123",
        external_subject="user_123",
        user_id=USER_ID,
        account_id=ACCOUNT_ID,
        role="owner",
        plan="pro",
        scopes=("account:user",),
        auth_method="external",
    )


def _build_app(session: AsyncMock) -> FastAPI:
    app = FastAPI()

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_principal] = _principal
    app.include_router(router, prefix="/api")
    return app


async def test_account_me_returns_principal() -> None:
    session = MagicMock()
    app = _build_app(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/account/me")

    assert response.status_code == 200
    body = response.json()
    assert body["account_id"] == str(ACCOUNT_ID)
    assert body["subject"] == "user_123"
    assert "external_subject" not in body


async def test_create_core_data_export_is_explicitly_scoped() -> None:
    session = MagicMock()
    session.info = {}
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    app = _build_app(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/account/core-data-exports")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert body["scope"] == "core_database_records"
    assert "only" in body["limitations"]
    assert body["expires_at"] is not None
    assert session.add.call_count == 2
    session.commit.assert_awaited_once()


async def test_list_core_data_exports_returns_recent_requests() -> None:
    session = MagicMock()
    session.info = {}
    row = MagicMock()
    row.id = uuid.uuid4()
    row.status = "queued"
    row.storage_url = None
    row.expires_at = None
    row.created_at = datetime(2026, 5, 18, tzinfo=UTC)
    row.completed_at = None
    result = MagicMock()
    result.scalars.return_value = [row]
    session.execute = AsyncMock(return_value=result)
    app = _build_app(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/account/core-data-exports")

    assert response.status_code == 200
    assert response.json()[0]["status"] == "queued"


async def test_download_core_data_export_generates_scoped_payload() -> None:
    export_id = uuid.uuid4()
    session = MagicMock()
    session.info = {}
    row = DataExport(
        id=export_id,
        account_id=ACCOUNT_ID,
        requested_by_user_id=USER_ID,
        status="queued",
        created_at=datetime(2026, 5, 18, tzinfo=UTC),
    )
    session.get = AsyncMock(return_value=row)
    session.add = MagicMock()
    session.commit = AsyncMock()
    app = _build_app(session)

    with patch(
        "src.app.api.routes.account.build_core_data_export_payload",
        new=AsyncMock(
            return_value={
                "format": "personal-execution-os.core-data-export.v1",
                "scope": "core_database_records",
                "tables": {"notes": []},
            }
        ),
    ) as mock_build:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/account/core-data-exports/{export_id}/download")

    assert response.status_code == 200
    assert response.json()["scope"] == "core_database_records"
    assert row.status == "completed"
    assert row.completed_at is not None
    assert row.storage_url == f"download:{export_id}"
    mock_build.assert_awaited_once_with(session, account_id=ACCOUNT_ID)
    session.commit.assert_awaited_once()


async def test_incomplete_deletion_workflow_is_not_publicly_exposed() -> None:
    session = MagicMock()
    session.info = {}
    app = _build_app(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_response = await client.get("/api/account/deletion-requests")
        create_response = await client.post(
            "/api/account/deletion-requests",
            json={"scope": "account"},
        )

    assert list_response.status_code == 404
    assert create_response.status_code == 404
