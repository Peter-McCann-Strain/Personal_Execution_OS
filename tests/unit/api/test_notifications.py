"""Tests for the notification endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.notifications import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from tests.unit.api.auth_helpers import override_current_principal

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _mock_get_db():
    """Yield a mock session so routes don't need a real DB."""
    yield AsyncMock()


def _build_app(*, override_auth: bool = True) -> FastAPI:
    """Create a minimal FastAPI app with the notifications router for testing."""
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


def _make_mock_notification(
    *,
    notification_id: uuid.UUID | None = None,
    message: str = "Time to reach out to Alice",
    priority: str = "P1",
    category: str = "relationship",
    status: str = "unread",
) -> MagicMock:
    """Build a MagicMock that behaves like a NotificationRecord ORM instance."""
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = notification_id or uuid.uuid4()
    m.message = message
    m.priority = priority
    m.category = category
    m.status = status
    m.created_at = now
    return m


# ---------------------------------------------------------------------------
# list_notifications
# ---------------------------------------------------------------------------


async def test_list_notifications():
    """GET /notifications returns PaginatedResponse with correct shape."""
    mock_notif = _make_mock_notification()

    mock_session = AsyncMock()

    # First execute → count query → scalar_one() returns 1
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    # Second execute → notification rows
    notif_result = MagicMock()
    notif_result.scalars.return_value.all.return_value = [mock_notif]

    mock_session.execute = AsyncMock(side_effect=[count_result, notif_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/notifications")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "has_more" in data
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["message"] == "Time to reach out to Alice"
    assert data["items"][0]["priority"] == "P1"


# ---------------------------------------------------------------------------
# dismiss_notification
# ---------------------------------------------------------------------------


async def test_dismiss_notification():
    """PATCH /notifications/{id}/dismiss returns 200 with status ok."""
    notification_id = uuid.uuid4()
    mock_notif = _make_mock_notification(notification_id=notification_id)

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_notif)
    mock_session.commit = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(f"/api/notifications/{notification_id}/dismiss")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# dismiss_all
# ---------------------------------------------------------------------------


async def test_dismiss_all():
    """PATCH /notifications/dismiss-all returns 200 with status ok."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch("/api/notifications/dismiss-all")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# mark_all_read
# ---------------------------------------------------------------------------


async def test_mark_all_read():
    """PATCH /notifications/mark-all-read returns 200 with status ok."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch("/api/notifications/mark-all-read")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# unread_count
# ---------------------------------------------------------------------------


async def test_unread_count():
    """GET /notifications/unread-count returns total, hasP0, hasP1."""
    mock_session = AsyncMock()

    # Three session.execute calls:
    # 1) total unread → scalar_one() returns 5
    total_result = MagicMock()
    total_result.scalar_one.return_value = 5

    # 2) P0 count → scalar_one() returns 2 (> 0 → has_p0=True)
    p0_result = MagicMock()
    p0_result.scalar_one.return_value = 2

    # 3) P1 count → scalar_one() returns 0 (→ has_p1=False)
    p1_result = MagicMock()
    p1_result.scalar_one.return_value = 0

    mock_session.execute = AsyncMock(side_effect=[total_result, p0_result, p1_result])

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/notifications/unread-count")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert data["hasP0"] is True
    assert data["hasP1"] is False
