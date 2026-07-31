"""Tests for the health check endpoint — service status aggregation and caching."""

import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes import health as health_module
from src.app.api.routes.health import (
    _check_database,
    _check_ollama,
    _check_redis,
    _check_telegram_webhook,
    router,
)


async def _mock_get_db():
    """Yield a mock session so the health route doesn't need a real DB."""
    yield AsyncMock()


def _build_app() -> FastAPI:
    """Create a minimal FastAPI app with the health router for testing."""
    app = FastAPI()
    app.dependency_overrides[get_db] = _mock_get_db
    app.include_router(router)
    return app


def _reset_cache():
    """Clear the health endpoint cache between tests."""
    health_module._cache = None


def _mock_health_settings(**overrides):
    """Return minimal settings used by the health endpoint aggregation."""
    values = {
        "google_configured": False,
        "tavily_configured": False,
        "sentry_configured": False,
        "posthog_configured": False,
        "anthropic_api_key": SimpleNamespace(get_secret_value=lambda: "test-key"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# ---------------------------------------------------------------------------
# Unit tests for _check_database
# ---------------------------------------------------------------------------


async def test_check_database_success():
    """Healthy database returns status 'ok' with latency."""
    session = AsyncMock()
    session.execute.return_value = None  # SELECT 1 returns nothing useful

    result = await _check_database(session)

    assert result["status"] == "ok"
    assert "latency_ms" in result
    assert isinstance(result["latency_ms"], float)


async def test_check_database_failure():
    """Database connection error returns status 'down' without leaking error details."""
    session = AsyncMock()
    session.execute.side_effect = Exception("connection refused")

    result = await _check_database(session)

    assert result["status"] == "down"
    assert "error" not in result


async def test_check_telegram_webhook_marks_recent_error_degraded():
    """Recent Telegram errors should surface degraded webhook health."""
    app = FastAPI()
    app.state.telegram_service = SimpleNamespace(
        get_webhook_status=AsyncMock(
            return_value={
                "url": "https://example.com/webhook/telegram",
                "pending_update_count": 0,
                "last_error_date": int(datetime.now(UTC).timestamp()) - 30,
                "last_error_message": "Bad Gateway",
                "max_connections": 40,
            }
        )
    )
    request = SimpleNamespace(app=app)

    result = await _check_telegram_webhook(request)

    assert result["status"] == "degraded"
    assert result["last_error_message"] == "Bad Gateway"


async def test_check_telegram_webhook_ignores_stale_error_when_backlog_clear():
    """Old Telegram errors should not keep webhook health in degraded mode."""
    app = FastAPI()
    app.state.telegram_service = SimpleNamespace(
        get_webhook_status=AsyncMock(
            return_value={
                "url": "https://example.com/webhook/telegram",
                "pending_update_count": 0,
                "last_error_date": int(datetime.now(UTC).timestamp()) - 7200,
                "last_error_message": "Bad Gateway",
                "max_connections": 40,
            }
        )
    )
    request = SimpleNamespace(app=app)

    result = await _check_telegram_webhook(request)

    assert result["status"] == "ok"
    assert result["last_error_message"] == "Bad Gateway"


# ---------------------------------------------------------------------------
# Integration tests for the health endpoint
# ---------------------------------------------------------------------------


async def test_all_services_healthy():
    """When all services are healthy, overall status should be 'ok'."""
    _reset_cache()

    with (
        patch.object(health_module, "_check_database") as mock_db,
        patch.object(health_module, "_check_redis") as mock_redis,
        patch.object(health_module, "_check_ollama") as mock_ollama,
        patch.object(health_module, "_check_anthropic") as mock_anthropic,
        patch.object(health_module, "get_settings", return_value=_mock_health_settings()),
    ):
        mock_db.return_value = {"status": "ok", "latency_ms": 1.5}
        mock_redis.return_value = {"status": "ok", "latency_ms": 0.8}
        mock_ollama.return_value = {"status": "ok", "latency_ms": 5.2}
        mock_anthropic.return_value = {"status": "unknown", "note": "not checked"}

        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["services"]["database"]["status"] == "ok"
        assert data["services"]["redis"]["status"] == "ok"
        assert "timestamp" in data


async def test_database_down_returns_503():
    """When database is down, overall status should be 'down' with 503."""
    _reset_cache()

    with (
        patch.object(health_module, "_check_database") as mock_db,
        patch.object(health_module, "_check_redis") as mock_redis,
        patch.object(health_module, "_check_ollama") as mock_ollama,
        patch.object(health_module, "_check_anthropic") as mock_anthropic,
        patch.object(health_module, "get_settings", return_value=_mock_health_settings()),
    ):
        mock_db.return_value = {"status": "down"}
        mock_redis.return_value = {"status": "ok", "latency_ms": 0.8}
        mock_ollama.return_value = {"status": "ok", "latency_ms": 5.2}
        mock_anthropic.return_value = {"status": "unknown", "note": "not checked"}

        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "down"


async def test_redis_down_db_up_returns_degraded():
    """When Redis is down but DB is up, status should be 'degraded' (200)."""
    _reset_cache()

    with (
        patch.object(health_module, "_check_database") as mock_db,
        patch.object(health_module, "_check_redis") as mock_redis,
        patch.object(health_module, "_check_ollama") as mock_ollama,
        patch.object(health_module, "_check_anthropic") as mock_anthropic,
        patch.object(health_module, "get_settings", return_value=_mock_health_settings()),
    ):
        mock_db.return_value = {"status": "ok", "latency_ms": 1.5}
        mock_redis.return_value = {"status": "down"}
        mock_ollama.return_value = {"status": "ok", "latency_ms": 5.2}
        mock_anthropic.return_value = {"status": "unknown", "note": "not checked"}

        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"


async def test_ollama_down_returns_degraded():
    """When Ollama is down but DB is up, status should be 'degraded'."""
    _reset_cache()

    with (
        patch.object(health_module, "_check_database") as mock_db,
        patch.object(health_module, "_check_redis") as mock_redis,
        patch.object(health_module, "_check_ollama") as mock_ollama,
        patch.object(health_module, "_check_anthropic") as mock_anthropic,
        patch.object(health_module, "get_settings", return_value=_mock_health_settings()),
    ):
        mock_db.return_value = {"status": "ok", "latency_ms": 1.5}
        mock_redis.return_value = {"status": "ok", "latency_ms": 0.8}
        mock_ollama.return_value = {"status": "down"}
        mock_anthropic.return_value = {"status": "unknown", "note": "not checked"}

        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"


async def test_anthropic_down_not_degraded():
    """Anthropic down should NOT cause degraded status (it's just a config check)."""
    _reset_cache()

    with (
        patch.object(health_module, "_check_database") as mock_db,
        patch.object(health_module, "_check_redis") as mock_redis,
        patch.object(health_module, "_check_ollama") as mock_ollama,
        patch.object(health_module, "_check_anthropic") as mock_anthropic,
        patch.object(health_module, "get_settings", return_value=_mock_health_settings()),
    ):
        mock_db.return_value = {"status": "ok", "latency_ms": 1.5}
        mock_redis.return_value = {"status": "ok", "latency_ms": 0.8}
        mock_ollama.return_value = {"status": "ok", "latency_ms": 5.2}
        mock_anthropic.return_value = {"status": "down"}

        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        # Anthropic down should not affect overall status
        assert data["status"] == "ok"


async def test_telegram_down_returns_degraded():
    """When Telegram webhook health is down but DB is up, status should be degraded."""
    _reset_cache()

    with (
        patch.object(health_module, "_check_database") as mock_db,
        patch.object(health_module, "_check_redis") as mock_redis,
        patch.object(health_module, "_check_ollama") as mock_ollama,
        patch.object(health_module, "_check_telegram_webhook") as mock_telegram,
        patch.object(health_module, "_check_anthropic") as mock_anthropic,
        patch.object(health_module, "get_settings", return_value=_mock_health_settings()),
    ):
        mock_db.return_value = {"status": "ok", "latency_ms": 1.5}
        mock_redis.return_value = {"status": "ok", "latency_ms": 0.8}
        mock_ollama.return_value = {"status": "ok", "latency_ms": 5.2}
        mock_telegram.return_value = {"status": "down"}
        mock_anthropic.return_value = {"status": "unknown", "note": "not checked"}

        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["telegram"]["status"] == "down"


async def test_cache_returns_stale_result_within_ttl():
    """Within the 10s TTL, the cache should return the previous result without re-checking."""
    _reset_cache()

    call_count = 0

    async def counting_check_db(session):
        nonlocal call_count
        call_count += 1
        return {"status": "ok", "latency_ms": 1.0}

    with (
        patch.object(health_module, "_check_database", side_effect=counting_check_db),
        patch.object(
            health_module, "_check_redis", return_value={"status": "ok", "latency_ms": 0.5}
        ),
        patch.object(
            health_module, "_check_ollama", return_value={"status": "ok", "latency_ms": 2.0}
        ),
        patch.object(
            health_module, "_check_anthropic", return_value={"status": "unknown", "note": "ok"}
        ),
        patch.object(health_module, "get_settings", return_value=_mock_health_settings()),
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First call — should hit the real checks
            resp1 = await client.get("/health")
            assert resp1.status_code == 200
            assert call_count == 1

            # Second call within TTL — should use cache
            resp2 = await client.get("/health")
            assert resp2.status_code == 200
            # The DB check should NOT have been called again
            assert call_count == 1


async def test_cache_expires_after_ttl():
    """After the TTL expires, the cache should be refreshed."""
    _reset_cache()

    call_count = 0

    async def counting_check_db(session):
        nonlocal call_count
        call_count += 1
        return {"status": "ok", "latency_ms": 1.0}

    with (
        patch.object(health_module, "_check_database", side_effect=counting_check_db),
        patch.object(
            health_module, "_check_redis", return_value={"status": "ok", "latency_ms": 0.5}
        ),
        patch.object(
            health_module, "_check_ollama", return_value={"status": "ok", "latency_ms": 2.0}
        ),
        patch.object(
            health_module, "_check_anthropic", return_value={"status": "unknown", "note": "ok"}
        ),
        patch.object(health_module, "get_settings", return_value=_mock_health_settings()),
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First call
            await client.get("/health")
            assert call_count == 1

            # Manually expire the cache by backdating the timestamp
            if health_module._cache is not None:
                cached_time, cached_result = health_module._cache
                health_module._cache = (cached_time - 20.0, cached_result)

            # Second call — cache is stale, should re-check
            await client.get("/health")
            assert call_count == 2


async def test_health_response_contains_all_services():
    """Response should contain status for core, integration, and telemetry services."""
    _reset_cache()

    with (
        patch.object(
            health_module, "_check_database", return_value={"status": "ok", "latency_ms": 1.0}
        ),
        patch.object(
            health_module, "_check_redis", return_value={"status": "ok", "latency_ms": 0.5}
        ),
        patch.object(
            health_module, "_check_ollama", return_value={"status": "ok", "latency_ms": 2.0}
        ),
        patch.object(
            health_module, "_check_anthropic", return_value={"status": "unknown", "note": "ok"}
        ),
        patch.object(health_module, "get_settings", return_value=_mock_health_settings()),
    ):
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            data = resp.json()

        assert "database" in data["services"]
        assert "redis" in data["services"]
        assert "ollama" in data["services"]
        assert "llm" in data["services"]
        assert "google_calendar" in data["services"]
        assert "gmail" in data["services"]
        assert "tavily" in data["services"]
        assert "posthog" in data["services"]
        assert "sentry" in data["services"]
        assert "telegram" in data["services"]


# ---------------------------------------------------------------------------
# ImportError branches inside _check_redis and _check_ollama
# ---------------------------------------------------------------------------


async def test_check_redis_import_error():
    """When redis package is not installed, _check_redis returns 'unknown' (line 54)."""

    # Temporarily remove redis.asyncio from sys.modules and make import fail
    orig = sys.modules.get("redis.asyncio")
    orig_redis = sys.modules.get("redis")
    sys.modules["redis.asyncio"] = None  # type: ignore[assignment]
    sys.modules["redis"] = None  # type: ignore[assignment]

    # Need to reload the module so the local import picks up the broken module
    # Actually, _check_redis does `import redis.asyncio as aioredis` each call,
    # so setting sys.modules to None will cause ImportError
    try:
        result = await _check_redis()
        assert result["status"] == "unknown"
        assert "not installed" in result["message"]
    finally:
        # Restore
        if orig is not None:
            sys.modules["redis.asyncio"] = orig
        else:
            sys.modules.pop("redis.asyncio", None)
        if orig_redis is not None:
            sys.modules["redis"] = orig_redis
        else:
            sys.modules.pop("redis", None)


async def test_check_ollama_import_error():
    """When httpx package is not installed, _check_ollama returns 'unknown' (line 74)."""
    orig = sys.modules.get("httpx")
    sys.modules["httpx"] = None  # type: ignore[assignment]

    try:
        result = await _check_ollama()
        assert result["status"] == "unknown"
        assert "not installed" in result["message"]
    finally:
        if orig is not None:
            sys.modules["httpx"] = orig
        else:
            sys.modules.pop("httpx", None)


async def test_check_redis_returns_down_when_ping_is_false(monkeypatch):
    class _FakeRedisClient:
        async def ping(self) -> bool:
            return False

        async def aclose(self) -> None:
            return None

    redis_async_module = ModuleType("redis.asyncio")
    redis_async_module.from_url = lambda *args, **kwargs: _FakeRedisClient()
    redis_module = ModuleType("redis")
    redis_module.asyncio = redis_async_module
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "redis.asyncio", redis_async_module)
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url=SimpleNamespace(get_secret_value=lambda: "redis://localhost:6379")
        ),
    )

    result = await _check_redis()

    assert result["status"] == "down"


async def test_check_redis_returns_ok_when_ping_is_true(monkeypatch):
    class _FakeRedisClient:
        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            return None

    redis_async_module = ModuleType("redis.asyncio")
    redis_async_module.from_url = lambda *args, **kwargs: _FakeRedisClient()
    redis_module = ModuleType("redis")
    redis_module.asyncio = redis_async_module
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "redis.asyncio", redis_async_module)
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url=SimpleNamespace(get_secret_value=lambda: "redis://localhost:6379")
        ),
    )

    result = await _check_redis()

    assert result["status"] == "ok"
    assert "latency_ms" in result


async def test_check_redis_returns_down_on_exception_in_production(monkeypatch):
    class _FailingRedisClient:
        async def ping(self) -> bool:
            raise RuntimeError("redis down")

        async def aclose(self) -> None:
            return None

    redis_async_module = ModuleType("redis.asyncio")
    redis_async_module.from_url = lambda *args, **kwargs: _FailingRedisClient()
    redis_module = ModuleType("redis")
    redis_module.asyncio = redis_async_module
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "redis.asyncio", redis_async_module)
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="production",
            redis_url=SimpleNamespace(get_secret_value=lambda: "redis://localhost:6379"),
        ),
    )

    result = await _check_redis()

    assert result["status"] == "down"


async def test_check_ollama_returns_down_on_non_200(monkeypatch):
    class _Response:
        status_code = 503

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return _Response()

    def _async_client_factory(*args, **kwargs):
        return _FakeClient()

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=_async_client_factory))
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: SimpleNamespace(ollama_host="http://ollama:11434"),
    )

    result = await _check_ollama()

    assert result["status"] == "down"


async def test_check_ollama_returns_ok_on_200(monkeypatch):
    class _Response:
        status_code = 200

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return _Response()

    def _async_client_factory(*args, **kwargs):
        return _FakeClient()

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=_async_client_factory))
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: SimpleNamespace(ollama_host="http://ollama:11434"),
    )

    result = await _check_ollama()

    assert result["status"] == "ok"
    assert "latency_ms" in result


async def test_check_ollama_returns_down_on_exception(monkeypatch):
    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            raise RuntimeError("ollama unreachable")

    def _async_client_factory(*args, **kwargs):
        return _FakeClient()

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=_async_client_factory))
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: SimpleNamespace(ollama_host="http://ollama:11434"),
    )

    result = await _check_ollama()

    assert result["status"] == "down"


def test_check_anthropic_returns_ok_when_configured(monkeypatch):
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: SimpleNamespace(
            anthropic_api_key=SimpleNamespace(get_secret_value=lambda: "sk-real-key")
        ),
    )

    result = health_module._check_anthropic()

    assert result["status"] == "ok"
    assert "configured" in result["message"].lower()


def test_check_anthropic_returns_down_for_placeholder_key(monkeypatch):
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: SimpleNamespace(
            anthropic_api_key=SimpleNamespace(get_secret_value=lambda: "PLACEHOLDER-KEY")
        ),
    )

    result = health_module._check_anthropic()

    assert result["status"] == "down"


def test_check_anthropic_returns_down_when_config_lookup_fails(monkeypatch):
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: (_ for _ in ()).throw(RuntimeError("config unavailable")),
    )

    result = health_module._check_anthropic()

    assert result["status"] == "down"


async def test_health_preflight_uses_app_state_report():
    from src.app.core.preflight import PreflightCheck, PreflightReport

    _reset_cache()
    report = PreflightReport(
        status="ok",
        generated_at=datetime.now(UTC),
        checks=[PreflightCheck(name="evaluation_assets", status="ok", message="ok")],
    )
    app = FastAPI()
    app.state.preflight_report = report
    app.include_router(router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/preflight")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_preflight_falls_back_to_runtime_check(monkeypatch):
    from src.app.core.preflight import PreflightCheck, PreflightReport

    _reset_cache()
    mock_report = PreflightReport(
        status="fail",
        generated_at=datetime.now(UTC),
        checks=[PreflightCheck(name="evaluation_assets", status="fail", message="broken")],
    )

    mock_run = AsyncMock(return_value=mock_report)
    monkeypatch.setattr(health_module, "run_startup_preflight", mock_run)

    app = FastAPI()
    app.include_router(router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/preflight")

    assert response.status_code == 503
    assert response.json()["status"] == "fail"
    mock_run.assert_awaited_once()
