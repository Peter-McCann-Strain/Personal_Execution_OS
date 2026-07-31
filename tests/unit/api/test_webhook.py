"""Tests for the Telegram webhook endpoint."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.routes.webhook import router, set_bot_and_dispatcher
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse


def _build_app() -> FastAPI:
    """Create a minimal FastAPI app with the webhook router for testing."""
    app = FastAPI()

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.include_router(router)
    return app


async def test_set_bot_and_dispatcher():
    """set_bot_and_dispatcher stores bot and dispatcher in module globals."""
    import src.app.api.routes.webhook as webhook_module

    mock_bot = MagicMock()
    mock_dispatcher = MagicMock()
    webhook_module._bot = None
    webhook_module._dp = None

    set_bot_and_dispatcher(mock_bot, mock_dispatcher)

    assert webhook_module._bot is mock_bot
    assert webhook_module._dp is mock_dispatcher

    webhook_module._bot = None
    webhook_module._dp = None


async def test_telegram_webhook_bot_not_configured():
    """POST /webhook/telegram returns 503 when the bot is not configured."""
    import src.app.api.routes.webhook as webhook_module

    webhook_module._bot = None
    webhook_module._dp = None
    app = _build_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/webhook/telegram", json={"update_id": 123})

    assert response.status_code == 503


async def test_telegram_webhook_invalid_secret():
    """POST /webhook/telegram returns 403 when the secret token is wrong."""
    import src.app.api.routes.webhook as webhook_module

    mock_bot = MagicMock()
    mock_dispatcher = MagicMock()
    webhook_module._bot = mock_bot
    webhook_module._dp = mock_dispatcher
    mock_settings = MagicMock()
    mock_settings.telegram_webhook_secret.get_secret_value.return_value = "correct-secret"
    app = _build_app()

    try:
        with patch("src.app.api.routes.webhook.get_settings", return_value=mock_settings):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/webhook/telegram",
                    json={"update_id": 123},
                    headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
                )

        assert response.status_code == 403
    finally:
        webhook_module._bot = None
        webhook_module._dp = None


async def test_telegram_webhook_missing_secret():
    """POST /webhook/telegram returns 403 when the secret header is absent."""
    import src.app.api.routes.webhook as webhook_module

    mock_bot = MagicMock()
    mock_dispatcher = MagicMock()
    webhook_module._bot = mock_bot
    webhook_module._dp = mock_dispatcher
    mock_settings = MagicMock()
    mock_settings.telegram_webhook_secret.get_secret_value.return_value = "correct-secret"
    app = _build_app()

    try:
        with patch("src.app.api.routes.webhook.get_settings", return_value=mock_settings):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/webhook/telegram", json={"update_id": 123})

        assert response.status_code == 403
    finally:
        webhook_module._bot = None
        webhook_module._dp = None


async def test_telegram_webhook_valid_secret():
    """POST /webhook/telegram dispatches updates bearing the correct token."""
    import src.app.api.routes.webhook as webhook_module

    mock_bot = MagicMock()
    mock_dispatcher = AsyncMock()
    mock_dispatcher.feed_update = AsyncMock()
    webhook_module._bot = mock_bot
    webhook_module._dp = mock_dispatcher
    mock_settings = MagicMock()
    mock_settings.telegram_webhook_secret.get_secret_value.return_value = "correct-secret"
    mock_update = MagicMock()
    app = _build_app()

    try:
        with (
            patch("src.app.api.routes.webhook.get_settings", return_value=mock_settings),
            patch(
                "src.app.api.routes.webhook.types.Update.model_validate",
                return_value=mock_update,
            ),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/webhook/telegram",
                    json={"update_id": 123},
                    headers={
                        "X-Telegram-Bot-Api-Secret-Token": "correct-secret",
                    },
                )

        assert response.status_code == 200
        await asyncio.sleep(0)
        mock_dispatcher.feed_update.assert_called_once_with(
            bot=mock_bot,
            update=mock_update,
        )
    finally:
        webhook_module._bot = None
        webhook_module._dp = None
