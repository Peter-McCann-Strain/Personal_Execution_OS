"""Redis connection utilities — async context manager for short-lived pools."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

_clients: dict[tuple[str, bool], Redis] = {}
logger = structlog.get_logger()


def _client_key(redis_url: str, decode_responses: bool) -> tuple[str, bool]:
    return redis_url, decode_responses


def get_redis_client(redis_url: str, *, decode_responses: bool = True) -> Redis:
    """Return a shared async Redis client for the given connection settings."""
    key = _client_key(redis_url, decode_responses)
    client = _clients.get(key)
    if client is None:
        client = aioredis.from_url(redis_url, decode_responses=decode_responses)
        _clients[key] = client
    return client


@asynccontextmanager
async def redis_pool(redis_url: str, *, decode_responses: bool = True) -> AsyncIterator[Redis]:
    """Yield a shared Redis client.

    Usage::

        async with redis_pool(settings.redis_url) as conn:
            await conn.get("key")
    """
    yield get_redis_client(redis_url, decode_responses=decode_responses)


async def close_redis_clients() -> None:
    """Close all cached Redis clients."""
    try:
        for client in list(_clients.values()):
            try:
                await client.aclose()
            except Exception as exc:
                logger.warning(
                    "redis_client_close_failed",
                    error=str(exc),
                    exc_info=True,
                )
    finally:
        _clients.clear()
