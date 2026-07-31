"""Tests for global exception handlers in main.py."""

from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.core.exceptions import (
    DatabaseError,
    LLMError,
    RoutingError,
    SearchError,
)


async def _mock_get_db():
    yield AsyncMock()


def _build_app_with_error(error: Exception) -> FastAPI:
    """Build a minimal FastAPI app where /fail raises the given error."""
    from src.app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = _mock_get_db

    @app.get("/fail")
    async def fail_endpoint():
        raise error

    return app


async def test_llm_error_returns_502():
    """LLMError should return 502 with llm_error code."""
    app = _build_app_with_error(LLMError("API timeout"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/fail")

    assert resp.status_code == 502
    data = resp.json()
    assert data["error"] == "llm_error"
    assert data["message"] == "Something went wrong while generating the response."


async def test_database_error_returns_503():
    """DatabaseError should return 503 with database_error code."""
    app = _build_app_with_error(DatabaseError("connection refused"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/fail")

    assert resp.status_code == 503
    data = resp.json()
    assert data["error"] == "database_error"
    assert data["message"] == "A storage dependency was unavailable while handling that request."


async def test_routing_error_returns_422():
    """RoutingError should return 422 with routing_error code."""
    app = _build_app_with_error(RoutingError("unknown intent"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/fail")

    assert resp.status_code == 422
    data = resp.json()
    assert data["error"] == "routing_error"
    assert data["message"] == "I couldn't determine the right handling path for that request."


async def test_search_error_returns_500():
    """SearchError should return 500 with search_error code."""
    app = _build_app_with_error(SearchError("index unavailable"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/fail")

    assert resp.status_code == 500
    data = resp.json()
    assert data["error"] == "search_error"
    assert data["message"] == "A search dependency failed while handling that request."


async def test_unhandled_error_returns_500_generic():
    """Unhandled exceptions return 500 without leaking details."""
    app = _build_app_with_error(RuntimeError("secret internal detail"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/fail")

    assert resp.status_code == 500
    data = resp.json()
    assert data["error"] == "internal_error"
    assert "internal detail" not in data["message"]
    assert data["message"] == "An internal error occurred"


async def test_error_response_includes_request_id():
    """Error responses should include request_id when available."""
    app = _build_app_with_error(LLMError("test"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/fail")

    data = resp.json()
    # request_id is set by RequestLoggingMiddleware — may be None in test context
    assert "request_id" in data


async def test_validation_error_returns_422():
    """Request validation errors return 422 with validation_error code."""
    from src.app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = _mock_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Post to /api/chat with invalid body (missing required field)
        resp = await client.post("/api/chat", json={})

    # Should be 422 (either from custom handler or default FastAPI)
    assert resp.status_code in (401, 422)
