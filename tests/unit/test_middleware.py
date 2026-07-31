"""Tests for RequestLoggingMiddleware — request ID injection and logging."""

import builtins
import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from src.app.api.middleware import RequestLoggingMiddleware
from src.app.core.exceptions import NotFoundError


def _build_app() -> FastAPI:
    """Create a minimal FastAPI app with the logging middleware."""
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/app-error")
    async def app_error_endpoint():
        raise NotFoundError("Missing thing")

    @app.get("/validation/{item_id}")
    async def validation_endpoint(item_id: int):
        return {"item_id": item_id}

    @app.get("/database-error")
    async def database_error_endpoint():
        raise SQLAlchemyError("DB is down")

    @app.get("/unexpected-error")
    async def unexpected_error_endpoint():
        raise RuntimeError("boom")

    return app


# ---------------------------------------------------------------------------
# X-Request-ID header
# ---------------------------------------------------------------------------


async def test_response_includes_x_request_id():
    """Every response must include the X-Request-ID header."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test")

    assert "X-Request-ID" in response.headers


async def test_x_request_id_is_valid_uuid():
    """The X-Request-ID value must be a valid UUID4."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test")

    request_id = response.headers["X-Request-ID"]
    # uuid.UUID() will raise ValueError for invalid UUIDs
    parsed = uuid.UUID(request_id)
    assert parsed.version == 4


async def test_each_request_gets_different_request_id():
    """Two sequential requests must receive distinct request IDs."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.get("/test")
        resp2 = await client.get("/test")

    id1 = resp1.headers["X-Request-ID"]
    id2 = resp2.headers["X-Request-ID"]
    assert id1 != id2


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


async def test_successful_request_returns_200():
    """A normal GET to the test endpoint returns 200 with the expected body."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_app_error_maps_to_json_response():
    """Known AppError exceptions should keep their mapped HTTP status."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/app-error")

    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "not_found"
    assert data["request_id"] is not None


async def test_validation_error_maps_to_422_response():
    """Middleware should normalize propagated validation errors into JSON."""
    middleware = RequestLoggingMiddleware(app=FastAPI())
    request = MagicMock()
    request.method = "GET"
    request.url.path = "/validation/not-an-int"
    call_next = AsyncMock(
        side_effect=RequestValidationError(
            [
                {
                    "loc": ("path", "item_id"),
                    "msg": "Input should be a valid integer",
                    "type": "int_parsing",
                }
            ],
        ),
    )

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 422
    data = response.body.decode("utf-8")
    assert "validation_error" in data
    assert "Request validation failed" in data


async def test_sqlalchemy_error_maps_to_database_error():
    """SQLAlchemy errors should be normalized to the database error contract."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/database-error")

    assert response.status_code == 503
    data = response.json()
    assert data["error"] == "database_error"
    assert "Database error" in data["message"]


async def test_unexpected_error_maps_to_internal_error():
    """Unhandled exceptions should return the internal error contract."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/unexpected-error")

    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "internal_error"
    assert data["message"] == "An internal error occurred"


async def test_import_error_while_checking_sqlalchemy_still_returns_internal_error(monkeypatch):
    """If SQLAlchemy is unavailable at runtime, the generic internal-error path should still work."""
    middleware = RequestLoggingMiddleware(app=FastAPI())
    request = MagicMock()
    request.method = "GET"
    request.url.path = "/unexpected-error"
    call_next = AsyncMock(side_effect=RuntimeError("boom"))
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "sqlalchemy.exc":
            raise ImportError("sqlalchemy not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 500
    data = response.body.decode("utf-8")
    assert "internal_error" in data
