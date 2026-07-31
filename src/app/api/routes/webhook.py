"""Optional Telegram webhook endpoint."""

from __future__ import annotations

import asyncio
import hmac
from typing import Any

import structlog
from aiogram import Bot, types
from fastapi import APIRouter, Request, Response

from src.app.config import get_settings

logger = structlog.get_logger()
router = APIRouter()

_background_tasks: set[asyncio.Task[Any]] = set()
_bot: Bot | None = None
_dp: Any | None = None


def set_bot_and_dispatcher(bot: Bot, dispatcher: Any) -> None:
    """Install optional Telegram runtime objects after successful startup."""
    global _bot, _dp
    _bot = bot
    _dp = dispatcher


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> Response:
    """Authenticate and enqueue one Telegram update."""
    if _bot is None or _dp is None:
        return Response(status_code=503)

    settings = get_settings()
    expected_secret = settings.telegram_webhook_secret.get_secret_value()
    provided_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if (
        not expected_secret
        or provided_secret is None
        or not hmac.compare_digest(provided_secret, expected_secret)
    ):
        logger.warning(
            "telegram_webhook_auth_failed",
            secret_present=provided_secret is not None,
        )
        return Response(status_code=403)

    update = types.Update.model_validate(await request.json())
    task = asyncio.create_task(
        _dp.feed_update(bot=_bot, update=update),
        name=f"tg_update_{update.update_id}",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return Response(status_code=200)
