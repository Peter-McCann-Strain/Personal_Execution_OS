"""Tests for content asset API routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.content_assets import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from tests.unit.api.auth_helpers import override_current_principal


def _make_mock_asset(
    *,
    asset_id: uuid.UUID | None = None,
    note_id: uuid.UUID | None = None,
    title: str = "NotebookLM podcast",
    status: str = "ready",
) -> MagicMock:
    now = datetime.now(UTC)
    asset = MagicMock()
    asset.id = asset_id or uuid.uuid4()
    asset.note_id = note_id
    asset.project_id = None
    asset.task_id = None
    asset.title = title
    asset.asset_type = "notebooklm_podcast"
    asset.status = status
    asset.source_pack = {"sources": ["Case study note"]}
    asset.template_prompt = "Turn this into a podcast briefing."
    asset.run_notes = None
    asset.metadata_ = {"channel": "notebooklm"}
    asset.created_at = now
    asset.updated_at = now
    return asset


def _build_app(mock_session: AsyncMock) -> FastAPI:
    app = FastAPI()

    async def _mock_db():
        yield mock_session

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.dependency_overrides[get_db] = _mock_db
    override_current_principal(app)
    app.include_router(router, prefix="/api")
    return app


async def test_list_content_assets_success():
    mock_session = AsyncMock()
    mock_asset = _make_mock_asset()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.content_assets.repo_list_content_assets",
        new_callable=AsyncMock,
        return_value=([mock_asset], 1),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/content-assets", params={"status": "ready"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["title"] == "NotebookLM podcast"


async def test_create_content_asset_success():
    mock_session = AsyncMock()
    note_id = uuid.uuid4()
    mock_asset = _make_mock_asset(note_id=note_id)
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.content_assets.repo_create_content_asset",
        new_callable=AsyncMock,
        return_value=mock_asset,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/content-assets",
                json={"note_id": str(note_id), "asset_type": "notebooklm_podcast"},
            )

    assert response.status_code == 201
    assert response.json()["note_id"] == str(note_id)


async def test_get_content_asset_not_found():
    mock_session = AsyncMock()
    asset_id = uuid.uuid4()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.content_assets.repo_get_content_asset",
        new_callable=AsyncMock,
        return_value=None,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/content-assets/{asset_id}")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_generate_content_asset_source_pack_success():
    mock_session = AsyncMock()
    asset_id = uuid.uuid4()
    mock_asset = _make_mock_asset(asset_id=asset_id)
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.content_assets.repo_generate_content_source_pack",
        new_callable=AsyncMock,
        return_value=mock_asset,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/content-assets/{asset_id}/source-pack")

    assert response.status_code == 200
    assert response.json()["id"] == str(asset_id)


async def test_update_content_asset_success():
    mock_session = AsyncMock()
    asset_id = uuid.uuid4()
    mock_asset = _make_mock_asset(asset_id=asset_id, status="needs_review")
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.content_assets.repo_update_content_asset",
        new_callable=AsyncMock,
        return_value=mock_asset,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/content-assets/{asset_id}",
                json={"status": "needs_review", "run_notes": "Ready for review"},
            )

    assert response.status_code == 200
    assert response.json()["status"] == "needs_review"
