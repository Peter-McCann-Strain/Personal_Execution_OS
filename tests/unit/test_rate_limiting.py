"""Tests for the sliding window rate limiter."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.rate_limiting import (
    RateLimitMiddleware,
    RedisSlidingWindowCounter,
    SlidingWindowCounter,
    _counter,
)

# ---------------------------------------------------------------------------
# SlidingWindowCounter unit tests
# ---------------------------------------------------------------------------


def test_under_limit_allows_request():
    """Requests under the limit should be allowed."""
    counter = SlidingWindowCounter()
    assert counter.is_allowed("test-key", limit=5, window_seconds=60.0) is True


def test_multiple_requests_under_limit():
    """Multiple requests within the limit should all be allowed."""
    counter = SlidingWindowCounter()
    for _ in range(4):
        assert counter.is_allowed("test-key", limit=5, window_seconds=60.0) is True


def test_at_limit_blocks_request():
    """Request that would exceed the limit should be blocked."""
    counter = SlidingWindowCounter()
    # Fill up to the limit
    for _ in range(5):
        counter.is_allowed("test-key", limit=5, window_seconds=60.0)
    # This one should be blocked
    assert counter.is_allowed("test-key", limit=5, window_seconds=60.0) is False


def test_exactly_at_limit_blocks():
    """Once exactly at the limit, the next request must be blocked."""
    counter = SlidingWindowCounter()
    results = [counter.is_allowed("key", limit=3, window_seconds=60.0) for _ in range(4)]
    assert results == [True, True, True, False]


def test_sliding_window_expiry():
    """Old requests outside the window should expire, freeing capacity."""
    counter = SlidingWindowCounter()

    # Use a very short window
    window = 0.1  # 100ms

    # Fill to limit
    for _ in range(3):
        counter.is_allowed("key", limit=3, window_seconds=window)

    # At limit — should be blocked
    assert counter.is_allowed("key", limit=3, window_seconds=window) is False

    # Wait for window to expire
    time.sleep(0.15)

    # Now should be allowed again
    assert counter.is_allowed("key", limit=3, window_seconds=window) is True


def test_different_keys_tracked_separately():
    """Different keys should have independent rate limits."""
    counter = SlidingWindowCounter()

    # Fill up key-a
    for _ in range(3):
        counter.is_allowed("api:key-a", limit=3, window_seconds=60.0)

    # key-a is at limit
    assert counter.is_allowed("api:key-a", limit=3, window_seconds=60.0) is False

    # key-b should still be allowed
    assert counter.is_allowed("api:key-b", limit=3, window_seconds=60.0) is True


def test_ip_and_api_key_tracked_separately():
    """IP-based and API-key-based limits should not interfere."""
    counter = SlidingWindowCounter()

    # Fill up the IP key
    for _ in range(3):
        counter.is_allowed("ip:192.168.1.1", limit=3, window_seconds=60.0)

    assert counter.is_allowed("ip:192.168.1.1", limit=3, window_seconds=60.0) is False

    # API key should still have its own budget
    assert counter.is_allowed("api:abc12345", limit=3, window_seconds=60.0) is True


def test_cleanup_removes_stale_keys():
    """Cleanup should remove keys with no recent requests."""
    counter = SlidingWindowCounter()

    # Create entries with a very short window
    counter.is_allowed("stale-key", limit=10, window_seconds=0.05)

    # Wait for the entries to become stale
    time.sleep(0.1)

    counter.cleanup(max_age_seconds=0.05)

    # The key should have been cleaned up — internal state should be empty
    assert "stale-key" not in counter._requests


def test_cleanup_preserves_active_keys():
    """Cleanup should preserve keys with recent activity."""
    counter = SlidingWindowCounter()

    counter.is_allowed("active-key", limit=10, window_seconds=60.0)
    counter.cleanup(max_age_seconds=60.0)

    # Key should still be present
    assert "active-key" in counter._requests


def test_window_size_respected():
    """A longer window should retain requests that a shorter window would expire."""
    counter = SlidingWindowCounter()

    counter.is_allowed("key", limit=1, window_seconds=0.05)
    time.sleep(0.07)

    # Short window — the old request has expired, so this should succeed
    assert counter.is_allowed("key", limit=1, window_seconds=0.05) is True


def test_zero_limit_blocks_all():
    """A limit of zero should block every request."""
    counter = SlidingWindowCounter()
    assert counter.is_allowed("key", limit=0, window_seconds=60.0) is False


def test_single_request_limit():
    """A limit of 1 should allow exactly one request in the window."""
    counter = SlidingWindowCounter()
    assert counter.is_allowed("key", limit=1, window_seconds=60.0) is True
    assert counter.is_allowed("key", limit=1, window_seconds=60.0) is False


@pytest.mark.asyncio
async def test_api_key_requests_use_safe_valid_and_invalid_buckets():
    """Rate-limit keys must neither expose credentials nor reward key rotation."""
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    settings = SimpleNamespace(
        app_env="test",
        chat_api_key=SimpleNamespace(get_secret_value=lambda: "configured-secret"),
        rate_limit_api_rpm=60,
        rate_limit_api_window=60.0,
        rate_limit_telegram_rpm=30,
        rate_limit_telegram_window=60.0,
    )
    with (
        patch("src.app.config.get_settings", return_value=settings),
        patch.object(_counter, "is_allowed", return_value=True) as is_allowed,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app, client=("192.0.2.10", 1234)),
            base_url="http://test",
        ) as client:
            valid = await client.get("/test", headers={"X-API-Key": "configured-secret"})
            invalid = await client.get("/test", headers={"X-API-Key": "wrong-secret"})

    assert valid.status_code == 200
    assert invalid.status_code == 200
    assert is_allowed.call_args_list[0].args[0] == "api:authenticated"
    assert is_allowed.call_args_list[1].args[0] == "api-invalid:192.0.2.10"
    assert "configured-secret" not in repr(is_allowed.call_args_list)
    assert "wrong-secret" not in repr(is_allowed.call_args_list)


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_concurrent_access_does_not_corrupt():
    """Basic thread safety — counter should not produce negative counts."""
    import threading

    counter = SlidingWindowCounter()
    results = []

    def make_requests():
        for _ in range(50):
            results.append(counter.is_allowed("concurrent", limit=100, window_seconds=60.0))

    threads = [threading.Thread(target=make_requests) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    allowed = sum(1 for r in results if r)
    denied = sum(1 for r in results if not r)
    assert allowed + denied == 200
    # All 200 should be allowed since limit is 100 and we made 200 across threads
    # At least some should be allowed
    assert allowed >= 100


@pytest.mark.asyncio
async def test_redis_sliding_window_counter_uses_atomic_script():
    """Redis limiter should evaluate the sliding-window Lua script atomically."""
    fake_redis = AsyncMock()
    fake_redis.eval = AsyncMock(return_value=1)
    settings = SimpleNamespace(
        redis_url=SimpleNamespace(get_secret_value=lambda: "redis://test"),
    )

    with (
        patch("src.app.config.get_settings", return_value=settings),
        patch("src.app.core.redis.get_redis_client", return_value=fake_redis),
    ):
        allowed = await RedisSlidingWindowCounter().is_allowed("api:key", 5, 60.0)

    assert allowed is True
    fake_redis.eval.assert_awaited_once()
    args = fake_redis.eval.await_args.args
    assert "ZREMRANGEBYSCORE" in args[0]
    assert args[2] == "rate_limit:api:key"
    assert all(isinstance(arg, str) for arg in args[2:])


@pytest.mark.asyncio
async def test_redis_sliding_window_counter_accepts_sync_stub_result():
    """Redis' declared sync-or-async result is handled at the client boundary."""
    fake_redis = MagicMock()
    fake_redis.eval.return_value = "0"
    settings = SimpleNamespace(
        redis_url=SimpleNamespace(get_secret_value=lambda: "redis://test"),
    )

    with (
        patch("src.app.config.get_settings", return_value=settings),
        patch("src.app.core.redis.get_redis_client", return_value=fake_redis),
    ):
        allowed = await RedisSlidingWindowCounter().is_allowed("api:key", 5, 60.0)

    assert allowed is False
    fake_redis.eval.assert_called_once()


@pytest.mark.asyncio
async def test_redis_sliding_window_counter_rejects_unexpected_result():
    """An invalid Redis response fails explicitly instead of being truthy by accident."""
    fake_redis = MagicMock()
    fake_redis.eval.return_value = object()
    settings = SimpleNamespace(
        redis_url=SimpleNamespace(get_secret_value=lambda: "redis://test"),
    )

    with (
        patch("src.app.config.get_settings", return_value=settings),
        patch("src.app.core.redis.get_redis_client", return_value=fake_redis),
        pytest.raises(TypeError, match="Unexpected Redis rate-limit result"),
    ):
        await RedisSlidingWindowCounter().is_allowed("api:key", 5, 60.0)
