"""Tests for the commitments API routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.commitments import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from tests.unit.api.auth_helpers import override_current_principal


def _make_mock_commitment(
    *,
    commitment_id: uuid.UUID | None = None,
    status: str = "detected",
    temporal_normalized: datetime | None = None,
) -> MagicMock:
    now = datetime.now(UTC)
    commitment = MagicMock()
    commitment.id = commitment_id or uuid.uuid4()
    commitment.verbatim_text = "I'll send the report tomorrow."
    commitment.normalized_action = "Send the report"
    commitment.who_committed = "Alex"
    commitment.who_to = "Team"
    commitment.temporal_expression_raw = "tomorrow"
    commitment.temporal_normalized = temporal_normalized
    commitment.commitment_type = "promise"
    commitment.confidence_score = 0.92
    commitment.status = status
    commitment.created_at = now
    commitment.updated_at = now
    return commitment


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


async def test_create_commitment_success():
    mock_session = AsyncMock()
    commitment = _make_mock_commitment()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.commitments.repo_create_commitment",
        new_callable=AsyncMock,
        return_value=commitment,
    ) as mock_create:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/commitments",
                json={
                    "verbatim_text": "I'll send the report tomorrow.",
                    "normalized_action": "Send the report",
                    "who_committed": "Alex",
                    "who_to": "Team",
                    "temporal_expression": "tomorrow",
                    "confidence_score": 0.92,
                },
            )

    assert response.status_code == 201
    data = response.json()
    assert data["normalized_action"] == "Send the report"
    assert data["status"] == "detected"
    mock_create.assert_awaited_once()


async def test_get_overdue_commitments_success():
    mock_session = AsyncMock()
    overdue = _make_mock_commitment(
        status="active",
        temporal_normalized=datetime.now(UTC) - timedelta(days=1),
    )
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.commitments.repo_get_overdue_commitments",
        new_callable=AsyncMock,
        return_value=[overdue],
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/commitments/overdue")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "active"
    assert data[0]["temporal_normalized"] is not None


async def test_get_open_commitments_respects_limit():
    mock_session = AsyncMock()
    open_commitment = _make_mock_commitment(status="in_progress")
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.commitments.repo_get_open_commitments",
        new_callable=AsyncMock,
        return_value=[open_commitment],
    ) as mock_get_open:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/commitments/open", params={"limit": 7})

    assert response.status_code == 200
    assert response.json()[0]["status"] == "in_progress"
    mock_get_open.assert_awaited_once_with(mock_session, limit=7)


async def test_update_commitment_status_success():
    commitment_id = uuid.uuid4()
    mock_session = AsyncMock()
    updated = _make_mock_commitment(commitment_id=commitment_id, status="completed")
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.commitments.repo_update_commitment_status",
        new_callable=AsyncMock,
        return_value=updated,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/commitments/{commitment_id}/status",
                json={"status": "completed"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(commitment_id)
    assert data["status"] == "completed"


async def test_update_commitment_status_not_found():
    commitment_id = uuid.uuid4()
    mock_session = AsyncMock()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.commitments.repo_update_commitment_status",
        new_callable=AsyncMock,
        side_effect=ValueError(f"Commitment not found: {commitment_id}"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/commitments/{commitment_id}/status",
                json={"status": "completed"},
            )

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
