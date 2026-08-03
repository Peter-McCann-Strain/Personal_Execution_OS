"""Tests for the FastAPI application factory and lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# create_app — basic structure
# ---------------------------------------------------------------------------


def _make_lifespan_settings(**overrides):
    settings = SimpleNamespace(
        app_env="test",
        log_level="WARNING",
        database_url=SecretStr("postgresql+asyncpg://test:test@localhost/test"),
        anthropic_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
        telegram_configured=False,
        telegram_bot_token=SimpleNamespace(get_secret_value=lambda: "123:abc"),
        allowed_user_ids=[12345],
        telegram_webhook_url="https://example.com",
        telegram_webhook_secret=SimpleNamespace(get_secret_value=lambda: "secret"),
        google_configured=False,
        tavily_configured=False,
        redis_url=SimpleNamespace(get_secret_value=lambda: "redis://localhost:6379"),
        chat_api_key=SimpleNamespace(get_secret_value=lambda: "test-chat-key"),
        voice_calling_configured=False,
        voice_reflection_enabled=False,
        voice_reflection_configured=False,
        voice_reflection_webhook_configured=False,
        voice_provider_config_version="",
        telemetry_installation_salt=SecretStr(""),
        evaluation_export_dir="data/evaluation/exports",
        otel_semconv_opt_in="gen_ai_latest_experimental",
        otel_configured=False,
        startup_preflight_fail_fast=False,
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


class AsyncSpy:
    def __init__(self, *, result=None, exc: Exception | None = None):
        self.result = result
        self.exc = exc
        self.calls: list[tuple[tuple, dict]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.result

    def assert_awaited_once(self) -> None:
        assert len(self.calls) == 1

    def assert_awaited_once_with(self, *args, **kwargs) -> None:
        assert self.calls == [((args), kwargs)]


def _make_preflight_session_factory(installed_extensions: tuple[str, ...] = ("pg_trgm", "vector")):
    result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: list(installed_extensions)),
    )
    execute = AsyncSpy(result=result)

    @asynccontextmanager
    async def _session_context():
        yield SimpleNamespace(execute=execute)

    def _factory():
        return _session_context()

    return _factory


class TestCreateApp:
    """Test create_app() returns a properly configured FastAPI app."""

    def test_returns_fastapi_instance(self):
        """create_app should return a FastAPI instance."""
        with patch("src.app.main.get_settings") as mock_settings:
            settings = MagicMock()
            settings.app_env = "test"
            settings.cors_allowed_origins = ""
            mock_settings.return_value = settings

            from src.app.main import create_app

            app = create_app()
        assert isinstance(app, FastAPI)

    def test_title_and_version(self):
        """App should have correct title and version."""
        with patch("src.app.main.get_settings") as mock_settings:
            settings = MagicMock()
            settings.app_env = "test"
            settings.cors_allowed_origins = ""
            mock_settings.return_value = settings

            from src.app.main import create_app

            app = create_app()
        assert app.title == "Personal Execution OS"
        assert app.version == "0.1.1"

    def test_docs_enabled_in_non_production(self):
        """Docs URLs should be available in non-production envs."""
        with patch("src.app.main.get_settings") as mock_settings:
            settings = MagicMock()
            settings.app_env = "development"
            settings.cors_allowed_origins = ""
            mock_settings.return_value = settings

            from src.app.main import create_app

            app = create_app()
        assert app.docs_url == "/docs"
        assert app.redoc_url == "/redoc"
        assert app.openapi_url == "/openapi.json"

    def test_docs_disabled_in_production(self):
        """Docs URLs should be None in production."""
        with patch("src.app.main.get_settings") as mock_settings:
            settings = MagicMock()
            settings.app_env = "production"
            settings.cors_allowed_origins = ""
            mock_settings.return_value = settings

            from src.app.main import create_app

            app = create_app()
        assert app.docs_url is None
        assert app.redoc_url is None
        assert app.openapi_url is None

    def test_cors_middleware_added_when_configured(self):
        """CORS middleware should be added when cors_allowed_origins is set."""
        with patch("src.app.main.get_settings") as mock_settings:
            settings = MagicMock()
            settings.app_env = "test"
            settings.cors_allowed_origins = "http://localhost:3000, http://example.com"
            mock_settings.return_value = settings

            from src.app.main import create_app

            app = create_app()
        # Middleware stack should contain CORS
        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes

    def test_routers_registered(self):
        """All expected routers should be registered."""
        with patch("src.app.main.get_settings") as mock_settings:
            settings = MagicMock()
            settings.app_env = "test"
            settings.cors_allowed_origins = ""
            mock_settings.return_value = settings

            from src.app.main import create_app

            app = create_app()

        route_paths = set(app.openapi()["paths"])
        # Check some key routes exist
        assert "/health" in route_paths
        assert "/api/setup/status" in route_paths
        assert "/api/auth/login" in route_paths
        assert "/webhook/telegram" in route_paths
        assert "/api/monitoring/voice-calls" not in route_paths
        assert "/api/voice/test-call" not in route_paths


# ---------------------------------------------------------------------------
# _get_request_id
# ---------------------------------------------------------------------------


class TestGetRequestId:
    def test_returns_none_when_no_context(self):
        """_get_request_id should return None when no request_id is in context."""
        import structlog

        structlog.contextvars.clear_contextvars()
        from src.app.main import _get_request_id

        result = _get_request_id()
        assert result is None

    def test_returns_request_id_from_context(self):
        """_get_request_id should return request_id from structlog contextvars."""
        import structlog

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id="test-123")
        from src.app.main import _get_request_id

        result = _get_request_id()
        assert result == "test-123"
        structlog.contextvars.clear_contextvars()


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


class TestExceptionHandlers:
    """Test that exception handlers are correctly wired."""

    def _make_test_app(self):
        """Create a test app with a minimal lifespan to avoid real init."""
        from src.app.core.exceptions import LLMError, NotFoundError

        @asynccontextmanager
        async def noop_lifespan(app):
            yield

        with patch("src.app.main.get_settings") as mock_settings:
            settings = MagicMock()
            settings.app_env = "test"
            settings.cors_allowed_origins = ""
            mock_settings.return_value = settings

            from src.app.main import create_app

            app = create_app()

        # Override lifespan to avoid real DB/Telegram/etc init
        app.router.lifespan_context = noop_lifespan

        # Add test routes that raise different errors
        @app.get("/test/app-error")
        async def raise_app_error():
            raise LLMError("Test LLM error")

        @app.get("/test/not-found")
        async def raise_not_found():
            raise NotFoundError("Resource not found")

        @app.get("/test/validation")
        async def validation_endpoint(required_param: int):
            return {"value": required_param}

        return app

    def test_app_error_handler(self):
        """AppError subclasses should return appropriate status codes."""
        app = self._make_test_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/test/app-error")
        assert response.status_code == 502  # LLMError maps to 502
        data = response.json()
        assert data["error"] == "llm_error"
        assert data["message"] == "Something went wrong while generating the response."

    def test_not_found_error_handler(self):
        """NotFoundError should return 404."""
        app = self._make_test_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/test/not-found")
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "not_found"

    def test_validation_error_handler(self):
        """RequestValidationError should return 422."""
        app = self._make_test_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Missing required_param should cause validation error
        response = client.get("/test/validation")
        assert response.status_code == 422
        data = response.json()
        assert data["error"] == "validation_error"

    def test_unhandled_error_handler(self):
        """Unhandled exceptions should return 500 with internal_error.

        Note: BaseHTTPMiddleware catches exceptions before they reach
        @app.exception_handler(Exception), so we test the handler directly.
        """

        @asynccontextmanager
        async def noop_lifespan(app):
            yield

        # Create an app WITHOUT the BaseHTTPMiddleware so the
        # @app.exception_handler(Exception) actually fires.
        with patch("src.app.main.get_settings") as mock_settings:
            settings = MagicMock()
            settings.app_env = "test"
            settings.cors_allowed_origins = ""
            mock_settings.return_value = settings

            from src.app.main import create_app

            app = create_app()

        app.router.lifespan_context = noop_lifespan

        # Remove all user middleware so BaseHTTPMiddleware doesn't intercept
        app.user_middleware.clear()
        # Rebuild middleware stack
        app.middleware_stack = app.build_middleware_stack()

        @app.get("/test/unhandled")
        async def raise_unhandled():
            raise RuntimeError("unexpected boom")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test/unhandled")
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "internal_error"
        assert data["message"] == "An internal error occurred"


# ---------------------------------------------------------------------------
# Lifespan — startup and shutdown
# ---------------------------------------------------------------------------


class TestLifespan:
    """Test the lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_basic_startup_shutdown(self):
        """Lifespan should init DB, Anthropic client and shut down cleanly."""
        from src.app.main import lifespan

        mock_engine = MagicMock()
        mock_session_factory = _make_preflight_session_factory()
        mock_anthropic_close = AsyncSpy()
        mock_anthropic = SimpleNamespace(close=mock_anthropic_close)
        mock_settings = _make_lifespan_settings()
        mock_close = AsyncSpy()

        app = FastAPI()

        with (
            patch("src.app.main.get_settings", return_value=mock_settings),
            patch("src.app.main.setup_logging") as mock_logging,
            patch("src.app.main.init_engine", return_value=mock_engine) as mock_init_engine,
            patch(
                "src.app.main.init_session_factory", return_value=mock_session_factory
            ) as mock_init_sf,
            patch("src.app.main.close_engine", new=mock_close),
            patch("src.app.main.AsyncAnthropic", return_value=mock_anthropic),
        ):
            async with lifespan(app):
                # Verify startup happened
                mock_logging.assert_called_once_with("WARNING", "test")
                mock_init_engine.assert_called_once_with(
                    mock_settings.database_url.get_secret_value()
                )
                mock_init_sf.assert_called_once_with(mock_engine)
                assert app.state.session_factory is mock_session_factory
                assert app.state.anthropic_client is mock_anthropic

            # Verify shutdown happened
            mock_anthropic_close.assert_awaited_once()
            mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_with_telegram_dev_mode(self):
        """Lifespan should start polling in development mode."""
        from src.app.main import lifespan

        mock_engine = MagicMock()
        mock_session_factory = _make_preflight_session_factory()
        mock_anthropic = SimpleNamespace(close=AsyncSpy())
        mock_settings = _make_lifespan_settings(
            app_env="development",
            telegram_configured=True,
        )
        mock_close = AsyncSpy()

        mock_telegram_service = MagicMock()
        mock_telegram_service.bot = MagicMock()
        mock_telegram_service.dp = MagicMock()
        mock_telegram_service.start_polling = AsyncSpy()
        mock_telegram_service.shutdown = AsyncSpy()

        mock_telegram_cls = MagicMock(return_value=mock_telegram_service)

        app = FastAPI()

        with (
            patch("src.app.main.get_settings", return_value=mock_settings),
            patch("src.app.main.logger.warning"),
            patch("src.app.main.setup_logging"),
            patch("src.app.main.init_engine", return_value=mock_engine),
            patch("src.app.main.init_session_factory", return_value=mock_session_factory),
            patch("src.app.main.close_engine", new=mock_close),
            patch("src.app.main.AsyncAnthropic", return_value=mock_anthropic),
            patch("src.app.main.set_bot_and_dispatcher") as mock_set_bot,
            patch.dict(
                "sys.modules",
                {
                    "src.app.domain.services.telegram": MagicMock(
                        TelegramService=mock_telegram_cls
                    ),
                },
            ),
        ):
            async with lifespan(app):
                assert app.state.telegram_service is mock_telegram_service
                mock_set_bot.assert_called_once_with(
                    mock_telegram_service.bot, mock_telegram_service.dp
                )

            # Verify telegram shutdown
            mock_telegram_service.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_with_telegram_production_mode(self):
        """Lifespan should set webhook in production mode."""
        from src.app.main import lifespan

        mock_engine = MagicMock()
        mock_session_factory = _make_preflight_session_factory()
        mock_anthropic = SimpleNamespace(close=AsyncSpy())
        mock_settings = _make_lifespan_settings(
            app_env="production",
            telegram_configured=True,
            telegram_webhook_url="https://example.com",
            telegram_webhook_secret=SimpleNamespace(get_secret_value=lambda: "secret"),
            voice_reflection_enabled=True,
            voice_reflection_configured=True,
            voice_reflection_webhook_configured=True,
            voice_provider_config_version=(
                "evening_voice_reflection:v1:2026-04-13:scheduled_reflection:pstn_outbound"
            ),
        )
        mock_close = AsyncSpy()

        mock_bot = SimpleNamespace(set_webhook=AsyncSpy())
        mock_telegram_service = MagicMock()
        mock_telegram_service.bot = mock_bot
        mock_telegram_service.dp = MagicMock()
        mock_telegram_service.shutdown = AsyncSpy()

        mock_telegram_cls = MagicMock(return_value=mock_telegram_service)

        app = FastAPI()

        with (
            patch("src.app.main.get_settings", return_value=mock_settings),
            patch("src.app.main.setup_logging"),
            patch("src.app.main.init_engine", return_value=mock_engine),
            patch("src.app.main.init_session_factory", return_value=mock_session_factory),
            patch("src.app.main.close_engine", new=mock_close),
            patch("src.app.main.AsyncAnthropic", return_value=mock_anthropic),
            patch(
                "src.app.main.run_startup_preflight",
                new=AsyncSpy(result=SimpleNamespace(status="ok", checks=[])),
            ),
            patch("src.app.main.set_bot_and_dispatcher"),
            patch.dict(
                "sys.modules",
                {
                    "src.app.domain.services.telegram": MagicMock(
                        TelegramService=mock_telegram_cls
                    ),
                },
            ),
        ):
            async with lifespan(app):
                mock_bot.set_webhook.assert_awaited_once_with(
                    url="https://example.com/webhook/telegram",
                    secret_token="secret",
                )

    @pytest.mark.asyncio
    async def test_lifespan_telegram_init_failure_keeps_core_available(self):
        """An optional Telegram failure must not take down the core app."""
        from src.app.main import lifespan

        mock_engine = MagicMock()
        mock_session_factory = _make_preflight_session_factory()
        mock_anthropic = SimpleNamespace(close=AsyncSpy())
        mock_settings = _make_lifespan_settings(telegram_configured=True)

        app = FastAPI()

        def _raise_telegram_init(**_kwargs):
            raise RuntimeError("telegram init boom")

        with (
            patch("src.app.main.get_settings", return_value=mock_settings),
            patch("src.app.main.setup_logging"),
            patch("src.app.main.init_engine", return_value=mock_engine),
            patch("src.app.main.init_session_factory", return_value=mock_session_factory),
            patch("src.app.main.close_engine", new=AsyncSpy()),
            patch("src.app.main.AsyncAnthropic", return_value=mock_anthropic),
            patch.dict(
                "sys.modules",
                {
                    "src.app.domain.services.telegram": SimpleNamespace(
                        TelegramService=_raise_telegram_init
                    ),
                },
            ),
        ):
            async with lifespan(app):
                assert not hasattr(app.state, "telegram_service")

    @pytest.mark.asyncio
    async def test_lifespan_does_not_start_mcp(self):
        """Public lifespan uses direct integrations and never starts MCP."""
        from src.app.main import lifespan

        mock_engine = MagicMock()
        mock_session_factory = _make_preflight_session_factory()
        mock_anthropic = SimpleNamespace(close=AsyncSpy())
        mock_settings = _make_lifespan_settings(google_configured=True)
        app = FastAPI()

        with (
            patch("src.app.main.get_settings", return_value=mock_settings),
            patch("src.app.main.setup_logging"),
            patch("src.app.main.init_engine", return_value=mock_engine),
            patch("src.app.main.init_session_factory", return_value=mock_session_factory),
            patch("src.app.main.close_engine", new=AsyncSpy()),
            patch("src.app.main.AsyncAnthropic", return_value=mock_anthropic),
        ):
            async with lifespan(app):
                assert not hasattr(app.state, "mcp_manager")

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_handles_anthropic_close_error(self):
        """Lifespan should handle Anthropic client close errors."""
        from src.app.main import lifespan

        mock_engine = MagicMock()
        mock_session_factory = _make_preflight_session_factory()

        async def _raise_close_failed():
            raise RuntimeError("close failed")

        async def _close_engine():
            return None

        mock_anthropic = SimpleNamespace(close=_raise_close_failed)
        mock_settings = _make_lifespan_settings()

        app = FastAPI()

        with (
            patch("src.app.main.get_settings", return_value=mock_settings),
            patch("src.app.main.logger.warning"),
            patch("src.app.main.setup_logging"),
            patch("src.app.main.init_engine", return_value=mock_engine),
            patch("src.app.main.init_session_factory", return_value=mock_session_factory),
            patch("src.app.main.close_engine", new=_close_engine),
            patch("src.app.main.AsyncAnthropic", return_value=mock_anthropic),
        ):
            # Should not raise despite close() failure
            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_lifespan_telegram_not_configured(self):
        """Lifespan should log when Telegram is not configured."""
        from src.app.main import lifespan

        mock_engine = MagicMock()
        mock_session_factory = _make_preflight_session_factory()

        async def _close_anthropic():
            return None

        async def _close_engine():
            return None

        mock_anthropic = SimpleNamespace(close=_close_anthropic)
        mock_settings = _make_lifespan_settings()

        app = FastAPI()

        with (
            patch("src.app.main.get_settings", return_value=mock_settings),
            patch("src.app.main.setup_logging"),
            patch("src.app.main.init_engine", return_value=mock_engine),
            patch("src.app.main.init_session_factory", return_value=mock_session_factory),
            patch("src.app.main.close_engine", new=_close_engine),
            patch("src.app.main.AsyncAnthropic", return_value=mock_anthropic),
        ):
            async with lifespan(app):
                # Telegram should not be initialised
                assert not hasattr(app.state, "telegram_service")

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_telegram_failure(self):
        """Lifespan should handle telegram shutdown failure."""
        from src.app.main import lifespan

        mock_engine = MagicMock()
        mock_session_factory = _make_preflight_session_factory()

        async def _close_anthropic():
            return None

        async def _close_engine():
            return None

        async def _shutdown_telegram():
            raise RuntimeError("shutdown boom")

        mock_anthropic = SimpleNamespace(close=_close_anthropic)
        mock_settings = _make_lifespan_settings(
            app_env="development",
            telegram_configured=True,
        )

        mock_telegram_service = MagicMock()
        mock_telegram_service.bot = MagicMock()
        mock_telegram_service.dp = MagicMock()
        mock_telegram_service.start_polling = AsyncSpy()
        mock_telegram_service.shutdown = _shutdown_telegram

        mock_telegram_cls = MagicMock(return_value=mock_telegram_service)

        app = FastAPI()

        with (
            patch("src.app.main.get_settings", return_value=mock_settings),
            patch("src.app.main.logger.warning"),
            patch("src.app.main.setup_logging"),
            patch("src.app.main.init_engine", return_value=mock_engine),
            patch("src.app.main.init_session_factory", return_value=mock_session_factory),
            patch("src.app.main.close_engine", new=_close_engine),
            patch("src.app.main.AsyncAnthropic", return_value=mock_anthropic),
            patch("src.app.main.set_bot_and_dispatcher"),
            patch.dict(
                "sys.modules",
                {
                    "src.app.domain.services.telegram": MagicMock(
                        TelegramService=mock_telegram_cls
                    ),
                },
            ),
        ):
            # Should not raise despite shutdown failure
            async with lifespan(app):
                pass
