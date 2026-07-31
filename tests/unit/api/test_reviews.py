"""Tests for the reviews API routes — listing, detail, generation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.reviews import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from tests.unit.api.auth_helpers import override_current_principal

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _mock_get_db():
    """Yield a mock session so routes don't need a real DB."""
    yield AsyncMock()


def _build_app(*, override_auth: bool = True) -> FastAPI:
    """Create a minimal FastAPI app with the reviews router for testing."""
    app = FastAPI()
    app.dependency_overrides[get_db] = _mock_get_db

    if override_auth:
        override_current_principal(app)

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.include_router(router, prefix="/api")
    return app


def _make_mock_review(
    *,
    review_id: uuid.UUID | None = None,
    review_type: str = "weekly",
    period: str = "2026-03-09 to 2026-03-16",
    content: dict | None = None,
) -> MagicMock:
    """Build a MagicMock that behaves like a Review ORM instance."""
    m = MagicMock()
    m.id = review_id or uuid.uuid4()
    m.review_type = review_type
    m.period = period
    m.content = content or {
        "accomplishments": ["Completed project kickoff", "Morning runs"],
        "mood_summary": "Generally positive mood this period.",
        "average_mood": 7.5,
        "goal_progress": [
            {"title": "Ship MVP", "progress": 0.6, "status": "active"},
        ],
        "open_commitments": [
            {"action": "Follow up with Alice", "status": "detected"},
        ],
        "relationship_alerts": [],
        "patterns_noticed": ["Higher energy on workout days"],
        "recommendations": ["Keep morning routine"],
        "key_insight": "Consistency drives progress.",
    }
    m.created_at = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)
    return m


# ---------------------------------------------------------------------------
# GET /reviews  (paginated)
# ---------------------------------------------------------------------------


async def test_list_reviews_success():
    """GET /reviews returns PaginatedResponse with correct shape."""
    mock_review = _make_mock_review()

    mock_session = AsyncMock()

    # First execute: count query -> scalar_one() returns 1
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    # Second execute: review rows
    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = [mock_review]

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/reviews")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "has_more" in data
    assert data["total"] == 1
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["period"] == "2026-03-09 to 2026-03-16"
    assert item["accomplishments"] == ["Completed project kickoff", "Morning runs"]
    assert item["average_mood"] == 7.5
    assert item["key_insight"] == "Consistency drives progress."


async def test_list_reviews_paginated():
    """GET /reviews respects pagination parameters."""
    mock_session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/reviews",
            params={"limit": 10, "offset": 5, "sort": "period", "order": "asc"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["has_more"] is False


# ---------------------------------------------------------------------------
# GET /reviews/{review_id}
# ---------------------------------------------------------------------------


async def test_get_review_success():
    """GET /reviews/{id} returns the review DTO."""
    review_id = uuid.uuid4()
    mock_review = _make_mock_review(review_id=review_id)

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_review)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/reviews/{review_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(review_id)
    assert data["period"] == "2026-03-09 to 2026-03-16"
    assert isinstance(data["goal_progress"], list)
    assert isinstance(data["open_commitments"], list)


async def test_get_review_not_found():
    """GET /reviews/{id} returns 404 when review does not exist."""
    review_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/reviews/{review_id}")

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "not_found"


# ---------------------------------------------------------------------------
# POST /reviews/generate
# ---------------------------------------------------------------------------


async def test_generate_review_weekly():
    """POST /reviews/generate returns 201 with the generated review."""
    generated_id = uuid.uuid4()

    mock_session = AsyncMock()

    # Episodes query
    episodes_result = MagicMock()
    episodes_result.scalars.return_value.all.return_value = []

    # Goals query
    goals_result = MagicMock()
    goals_result.scalars.return_value.all.return_value = []

    # Commitments query
    commitments_result = MagicMock()
    commitments_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[episodes_result, goals_result, commitments_result]
    )

    # The route calls session.add(), session.flush(), session.commit()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    # After flush, the Review object gets an id and created_at assigned.
    # We need to capture the add() call to set these attributes.
    def _side_effect_add(review_obj):
        review_obj.id = generated_id
        review_obj.created_at = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)

    mock_session.add.side_effect = _side_effect_add

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/reviews/generate",
            json={"type": "weekly"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == str(generated_id)
    assert data["accomplishments"] == []
    assert data["average_mood"] is None
    assert data["goal_progress"] == []
    assert data["open_commitments"] == []
    mock_session.commit.assert_called_once()
