"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import structlog
from anthropic import AsyncAnthropic
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.app.api.idempotency import IdempotencyMiddleware, register_idempotent_routes
from src.app.api.middleware import RequestLoggingMiddleware
from src.app.api.rate_limiting import RateLimitMiddleware
from src.app.api.routes import (
    account,
    agent_runs,
    auth,
    calendar,
    chat,
    commitments,
    connectors,
    contacts,
    content_assets,
    dashboard,
    decisions,
    email,
    episodes,
    goals,
    habits,
    health,
    memory,
    monitoring,
    notes,
    notifications,
    projects,
    reviews,
    runtime_stream,
    saved_memories,
    scheduled_actions,
    tutorials,
    web_push,
)
from src.app.api.routes import (
    settings as settings_routes,
)
from src.app.api.routes.webhook import router as webhook_router
from src.app.api.routes.webhook import set_bot_and_dispatcher
from src.app.config import get_settings
from src.app.core.exceptions import (
    EXCEPTION_STATUS_MAP,
    AppError,
    ErrorResponse,
    user_safe_error_message,
)
from src.app.core.llm import create_llm_provider
from src.app.core.logging import setup_logging
from src.app.core.otel import setup_otel
from src.app.core.preflight import run_startup_preflight
from src.app.core.redis import close_redis_clients
from src.app.core.request_security import ExactHostMiddleware, trusted_hosts
from src.app.core.telemetry import configure_telemetry, get_telemetry
from src.app.persistence.database import (
    close_engine,
    init_engine,
    init_session_factory,
)

logger = structlog.get_logger()


@dataclass(slots=True)
class _AppInitSettings:
    app_env: str = "development"
    cors_allowed_origins: str = ""
    public_hostname: str = ""


def _get_app_init_settings() -> _AppInitSettings:
    """Load only the settings needed to build the app structure.

    This is intentionally import-safe because ``app = create_app()`` runs at
    module import time. Runtime validation still happens strictly in lifespan().
    """
    try:
        settings = get_settings()
        return _AppInitSettings(
            app_env=settings.app_env,
            cors_allowed_origins=settings.cors_allowed_origins,
            public_hostname=settings.public_hostname,
        )
    except Exception:
        logger.warning("app_init_settings_unavailable", exc_info=True)
        return _AppInitSettings()


def _get_request_id() -> str | None:
    """Retrieve request_id from structlog contextvars (set by RequestLoggingMiddleware)."""
    ctx = structlog.contextvars.get_contextvars()
    return ctx.get("request_id")


def _telegram_webhook_url(configured_url: str) -> str:
    """Normalize the configured Telegram webhook URL."""
    trimmed = configured_url.rstrip("/")
    if trimmed.endswith("/webhook/telegram"):
        return trimmed
    return f"{trimmed}/webhook/telegram"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan — init DB, Telegram on startup; cleanup on shutdown."""
    settings = get_settings()
    setup_logging(settings.log_level, settings.app_env)

    logger.info("starting_app", env=settings.app_env)
    telemetry = configure_telemetry(settings)
    app.state.telemetry = telemetry

    # --- OpenTelemetry (Phase 3.1) ---
    # No-op when OTEL_EXPORTER_OTLP_ENDPOINT is empty. When configured,
    # auto-instruments FastAPI and wires an OTLP exporter with head
    # sampling — the Collector does the tail sampling (see
    # docs/OBSERVABILITY.md).
    setup_otel(app, settings)

    # --- Database ---
    engine = init_engine(settings.database_url.get_secret_value())
    session_factory = init_session_factory(engine)
    app.state.session_factory = session_factory
    logger.info("database_connected")

    # --- Optional model provider ---
    llm_provider = create_llm_provider(
        settings,
        anthropic_client_factory=AsyncAnthropic,
    )
    app.state.llm_provider = llm_provider
    # Temporary compatibility for call sites still named after the original
    # SDK. New code should depend on app.state.llm_provider.
    app.state.anthropic_client = llm_provider.client if llm_provider.configured else llm_provider
    logger.info(
        "llm_provider_initialized",
        provider=llm_provider.name,
        configured=llm_provider.configured,
    )

    # --- Telegram bot ---
    telegram_service = None
    polling_task: asyncio.Task | None = None

    if settings.telegram_configured and llm_provider.configured:
        try:
            from src.app.domain.services.telegram import TelegramService

            telegram_service = TelegramService(
                bot_token=settings.telegram_bot_token.get_secret_value(),
                allowed_user_ids=settings.allowed_user_ids,
                anthropic_api_key=settings.anthropic_api_key.get_secret_value(),
                session_factory=session_factory,
            )
            app.state.telegram_service = telegram_service

            # Wire bot + dispatcher into the webhook endpoint
            set_bot_and_dispatcher(telegram_service.bot, telegram_service.dp)

            if settings.app_env == "development":
                # Long-polling in dev — run in background so startup doesn't block
                polling_task = asyncio.create_task(
                    telegram_service.start_polling(),
                    name="telegram_polling",
                )
                logger.info("telegram_polling_started")
            else:
                # Production — set webhook so Telegram sends updates to our endpoint
                webhook_url = _telegram_webhook_url(settings.telegram_webhook_url)
                webhook_secret = settings.telegram_webhook_secret.get_secret_value()
                await telegram_service.bot.set_webhook(
                    url=webhook_url,
                    secret_token=webhook_secret,
                )
                logger.info("telegram_webhook_set")

            logger.info("telegram_initialized", mode=settings.app_env)
        except Exception as exc:
            logger.warning(
                "telegram_init_failed",
                error_class=type(exc).__name__,
                hint="Telegram is optional; the core web application remains available.",
                exc_info=True,
            )
    else:
        logger.info(
            "telegram_unavailable",
            telegram_configured=settings.telegram_configured,
            llm_configured=llm_provider.configured,
        )

    preflight_report = await run_startup_preflight(
        settings=settings,
        session_factory=session_factory,
    )
    app.state.preflight_report = preflight_report

    yield

    # --- Shutdown ---

    # Cancel polling task if running
    if polling_task is not None and not polling_task.done():
        polling_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await polling_task

    # Shutdown Telegram bot session
    if telegram_service is not None:
        try:
            await telegram_service.shutdown()
            logger.info("telegram_shutdown")
        except Exception:
            logger.warning("telegram_shutdown_failed", exc_info=True)

    # Close model provider
    try:
        await llm_provider.close()
        logger.info("llm_provider_closed", provider=llm_provider.name)
    except Exception:
        logger.warning("llm_provider_close_failed", exc_info=True)

    await close_redis_clients()
    await close_engine()
    logger.info("app_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app_settings = _get_app_init_settings()
    is_production = app_settings.app_env == "production"

    app = FastAPI(
        title="Personal Execution OS",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )

    # --- Exception handlers ---

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        logger.error(
            "app_error",
            error_code=error_code,
            error_class=type(exc).__name__,
            path=request.url.path,
        )
        get_telemetry().capture_exception(
            exc,
            context={
                "path": request.url.path,
                "error_code": error_code,
            },
        )
        body = ErrorResponse(
            error=error_code,
            message=user_safe_error_message(exc),
            request_id=_get_request_id(),
        )
        return JSONResponse(status_code=status_code, content=body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning(
            "validation_error",
            error_count=len(exc.errors()),
            path=request.url.path,
        )
        body = ErrorResponse(
            error="validation_error",
            message="Request validation failed",
            request_id=_get_request_id(),
        )
        return JSONResponse(status_code=422, content=body.model_dump())

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_error",
            path=request.url.path,
            exc_info=exc,
        )
        get_telemetry().capture_exception(exc, context={"path": request.url.path})
        body = ErrorResponse(
            error="internal_error",
            message="An internal error occurred",
            request_id=_get_request_id(),
        )
        return JSONResponse(status_code=500, content=body.model_dump())

    # --- Middleware (order matters: last added = outermost in Starlette) ---

    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    # CORS — only enabled when cors_allowed_origins is set
    if app_settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                o.strip() for o in app_settings.cors_allowed_origins.split(",") if o.strip()
            ],
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=[
                "X-API-Key",
                "Authorization",
                "Content-Type",
                "X-CSRF-Token",
            ],
        )

    app.add_middleware(
        ExactHostMiddleware,
        allowed_hosts=trusted_hosts(app_settings),
    )

    # Routes
    app.include_router(health.router, tags=["health"])
    app.include_router(auth.router, prefix="/api", tags=["auth"])
    app.include_router(account.router, prefix="/api", tags=["account"])
    app.include_router(chat.router, prefix="/api", tags=["chat"])
    app.include_router(episodes.router, prefix="/api", tags=["episodes"])
    app.include_router(dashboard.router, prefix="/api", tags=["dashboard"])
    app.include_router(settings_routes.router, prefix="/api", tags=["settings"])
    app.include_router(memory.router, prefix="/api", tags=["memory"])
    app.include_router(saved_memories.router, prefix="/api", tags=["saved-memories"])
    app.include_router(calendar.router, prefix="/api", tags=["calendar"])
    app.include_router(email.router, prefix="/api", tags=["email"])
    app.include_router(contacts.router, prefix="/api", tags=["contacts"])
    app.include_router(connectors.router, prefix="/api", tags=["connectors"])
    app.include_router(commitments.router, prefix="/api", tags=["commitments"])
    app.include_router(decisions.router, prefix="/api", tags=["decisions"])
    app.include_router(notifications.router, prefix="/api", tags=["notifications"])
    app.include_router(web_push.router, prefix="/api", tags=["notifications"])
    app.include_router(goals.router, prefix="/api", tags=["goals"])
    app.include_router(habits.router, prefix="/api", tags=["habits"])
    app.include_router(projects.router, prefix="/api", tags=["projects"])
    app.include_router(reviews.router, prefix="/api", tags=["reviews"])
    app.include_router(tutorials.router, prefix="/api", tags=["tutorials"])
    app.include_router(monitoring.router, prefix="/api", tags=["monitoring"])
    app.include_router(notes.router, prefix="/api", tags=["notes"])
    app.include_router(content_assets.router, prefix="/api", tags=["content-assets"])
    app.include_router(scheduled_actions.router, prefix="/api", tags=["scheduled-actions"])
    app.include_router(agent_runs.router, prefix="/api", tags=["agent-runs"])
    app.include_router(runtime_stream.router, prefix="/api", tags=["runtime"])
    app.include_router(webhook_router, tags=["telegram"])

    # Expose the Idempotency-Key protected-route list on app.state so tests
    # and the /docs/api.md generator can inspect it without reaching into
    # module globals.
    register_idempotent_routes(app)

    return app


app = create_app()
