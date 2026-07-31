"""Core scheduled-worker helpers retained after telephony removal."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.app.core.exceptions import ConfigError
from src.app.workers.scheduled import _send_to_users, _split_message


@pytest.mark.parametrize(
    ("message", "limit", "expected"),
    [
        ("hello", 100, ["hello"]),
        ("", 100, [""]),
        ("a" * 20, 10, ["a" * 10, "a" * 10]),
        ("line one\nline two\nline three", 18, ["line one\nline two", "line three"]),
    ],
)
def test_split_message(message: str, limit: int, expected: list[str]) -> None:
    assert _split_message(message, limit) == expected


@pytest.mark.asyncio
async def test_send_to_users_reports_missing_optional_telegram() -> None:
    with pytest.raises(ConfigError, match="Telegram bot is not available"):
        await _send_to_users({"bot": None}, "private scheduled content")


@pytest.mark.asyncio
async def test_send_to_users_delivers_each_chunk() -> None:
    bot = AsyncMock()
    settings = AsyncMock()
    settings.allowed_user_ids = [123]

    await _send_to_users(
        {"bot": bot, "settings": settings},
        "a" * 5000,
    )

    assert bot.send_message.await_count == 2
