"""Tests for src.app.core.redis shared async Redis client helpers."""

from unittest.mock import AsyncMock, patch

import pytest

import src.app.core.redis as redis_module
from src.app.core.redis import close_redis_clients, redis_pool


@pytest.fixture(autouse=True)
def _reset_cached_clients():
    """Keep unit tests isolated from the module-level Redis client cache."""
    redis_module._clients.clear()
    yield
    redis_module._clients.clear()


class TestRedisPool:
    async def test_yields_connection_and_closes(self):
        mock_conn = AsyncMock()

        with patch("src.app.core.redis.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_conn

            async with redis_pool("redis://localhost:6379") as conn:
                assert conn is mock_conn

            await close_redis_clients()

            mock_aioredis.from_url.assert_called_once_with(
                "redis://localhost:6379", decode_responses=True
            )
            mock_conn.aclose.assert_awaited_once()

    async def test_closes_on_exception(self):
        mock_conn = AsyncMock()

        with patch("src.app.core.redis.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_conn

            with pytest.raises(ValueError, match="test error"):
                async with redis_pool("redis://localhost:6379"):
                    raise ValueError("test error")

            await close_redis_clients()

            mock_conn.aclose.assert_awaited_once()

    async def test_decode_responses_default_true(self):
        mock_conn = AsyncMock()

        with patch("src.app.core.redis.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_conn

            async with redis_pool("redis://localhost:6379"):
                pass

            mock_aioredis.from_url.assert_called_once_with(
                "redis://localhost:6379", decode_responses=True
            )
            mock_conn.aclose.assert_not_awaited()

    async def test_decode_responses_can_be_disabled(self):
        mock_conn = AsyncMock()

        with patch("src.app.core.redis.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_conn

            async with redis_pool("redis://localhost:6379", decode_responses=False):
                pass

            mock_aioredis.from_url.assert_called_once_with(
                "redis://localhost:6379", decode_responses=False
            )

    async def test_shared_client_is_reused_until_shutdown(self):
        mock_conn = AsyncMock()

        with patch("src.app.core.redis.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_conn

            async with (
                redis_pool("redis://localhost:6379") as conn_one,
                redis_pool("redis://localhost:6379") as conn_two,
            ):
                assert conn_one is conn_two is mock_conn

            mock_aioredis.from_url.assert_called_once_with(
                "redis://localhost:6379", decode_responses=True
            )

            await close_redis_clients()

            mock_conn.aclose.assert_awaited_once()
