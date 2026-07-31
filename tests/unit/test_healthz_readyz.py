"""Liveness and core-only readiness contracts."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes import health as health_module
from src.app.api.routes.health import router


async def _mock_get_db():
    yield AsyncMock()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_db] = _mock_get_db
    app.include_router(router)
    return app


async def test_healthz_is_a_pure_process_probe() -> None:
    with (
        patch.object(health_module, "_check_database") as database,
        patch.object(health_module, "_check_redis") as redis,
        patch.object(health_module, "_check_ollama") as ollama,
        patch.object(health_module, "_check_llm_provider") as llm,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=_build_app()),
            base_url="http://test",
        ) as client:
            response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    database.assert_not_called()
    redis.assert_not_called()
    ollama.assert_not_called()
    llm.assert_not_called()


async def test_readyz_requires_only_postgres_and_redis() -> None:
    with (
        patch.object(
            health_module,
            "_check_database",
            AsyncMock(return_value={"status": "ok", "message": "ok"}),
        ),
        patch.object(
            health_module,
            "_check_redis",
            AsyncMock(return_value={"status": "ok", "message": "ok"}),
        ),
        patch.object(health_module, "_check_ollama") as ollama,
        patch.object(health_module, "_check_llm_provider") as llm,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=_build_app()),
            base_url="http://test",
        ) as client:
            response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert set(response.json()["services"]) == {"database", "redis"}
    ollama.assert_not_called()
    llm.assert_not_called()


async def test_readyz_rejects_database_failure() -> None:
    with (
        patch.object(
            health_module,
            "_check_database",
            AsyncMock(return_value={"status": "down", "message": "unreachable"}),
        ),
        patch.object(
            health_module,
            "_check_redis",
            AsyncMock(return_value={"status": "ok", "message": "ok"}),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=_build_app()),
            base_url="http://test",
        ) as client:
            response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["services"]["database"]["status"] == "down"


async def test_readyz_rejects_redis_failure() -> None:
    with (
        patch.object(
            health_module,
            "_check_database",
            AsyncMock(return_value={"status": "ok", "message": "ok"}),
        ),
        patch.object(
            health_module,
            "_check_redis",
            AsyncMock(return_value={"status": "down", "message": "unreachable"}),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=_build_app()),
            base_url="http://test",
        ) as client:
            response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["services"]["redis"]["status"] == "down"
