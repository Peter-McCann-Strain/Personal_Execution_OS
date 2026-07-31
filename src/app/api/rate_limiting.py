"""Redis-backed rate limiting for the API.

Production uses a Redis sliding window so limits are shared across workers.
Tests, and local/dev Redis outages, fall back to the in-process counter.
"""

import hashlib
import threading
import time
from collections import defaultdict

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from src.app.core.exceptions import ErrorResponse

logger = structlog.get_logger()


class SlidingWindowCounter:
    """Thread-safe sliding window rate limiter.

    Stores timestamps of requests per key and counts those within
    the window to decide whether to allow or reject.
    """

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str, limit: int, window_seconds: float) -> bool:
        """Check if a request is allowed and record it if so.

        Returns True if the request is within the rate limit, False otherwise.
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            # Prune expired timestamps
            timestamps = self._requests[key]
            self._requests[key] = [t for t in timestamps if t > cutoff]

            if len(self._requests[key]) >= limit:
                return False

            self._requests[key].append(now)
            return True

    def cleanup(self, max_age_seconds: float = 120.0) -> None:
        """Remove keys with no recent requests to prevent memory leaks."""
        now = time.monotonic()
        cutoff = now - max_age_seconds

        with self._lock:
            empty_keys = [
                key
                for key, timestamps in self._requests.items()
                if not timestamps or max(timestamps) < cutoff
            ]
            for key in empty_keys:
                del self._requests[key]


# Global counter instance
_counter = SlidingWindowCounter()


class RedisSlidingWindowCounter:
    """Redis sorted-set sliding window rate limiter."""

    _LUA_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local ttl = tonumber(ARGV[5])

redis.call("ZREMRANGEBYSCORE", key, 0, now - window)
local count = redis.call("ZCARD", key)
if count >= limit then
  redis.call("EXPIRE", key, ttl)
  return 0
end

redis.call("ZADD", key, now, member)
redis.call("EXPIRE", key, ttl)
return 1
"""

    async def is_allowed(self, key: str, limit: int, window_seconds: float) -> bool:
        """Check and record a request in Redis atomically."""
        from src.app.config import get_settings
        from src.app.core.redis import get_redis_client

        settings = get_settings()
        client = get_redis_client(settings.redis_url.get_secret_value())
        now = time.time()
        ttl_seconds = max(1, int(window_seconds) + 1)
        member = f"{now}:{time.monotonic_ns()}"
        result = await client.eval(
            self._LUA_SCRIPT,
            1,
            f"rate_limit:{key}",
            now,
            window_seconds,
            limit,
            member,
            ttl_seconds,
        )
        return bool(int(result))


_redis_counter = RedisSlidingWindowCounter()


async def rate_limit_allowed(key: str, *, limit: int, window_seconds: float) -> bool:
    """Apply the shared limiter to security-sensitive non-generic actions."""
    from src.app.config import get_settings

    settings = get_settings()
    if settings.app_env == "test":
        return _counter.is_allowed(key, limit, window_seconds)
    try:
        return await _redis_counter.is_allowed(key, limit, window_seconds)
    except Exception as exc:
        if settings.app_env == "development":
            logger.warning(
                "security_rate_limit_redis_unavailable_falling_back",
                key=key,
                error_class=type(exc).__name__,
            )
            return _counter.is_allowed(key, limit, window_seconds)
        logger.error(
            "security_rate_limit_unavailable",
            key=key,
            error_class=type(exc).__name__,
            exc_info=True,
        )
        return False


# Paths exempt from rate limiting
_EXEMPT_PATHS = {
    "/health",
    "/health/preflight",
    "/healthz",
    "/readyz",
    "/docs",
    "/redoc",
    "/openapi.json",
}


def _get_rate_limits() -> tuple[int, float, int, float]:
    """Read rate limit settings lazily to avoid import-time settings access."""
    from src.app.config import get_settings

    settings = get_settings()
    return (
        settings.rate_limit_api_rpm,
        settings.rate_limit_api_window,
        settings.rate_limit_telegram_rpm,
        settings.rate_limit_telegram_window,
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit requests based on API key or Telegram user identity."""

    _fallback_warning_logged = False

    async def _is_allowed(self, key: str, limit: int, window: float) -> bool | None:
        from src.app.config import get_settings

        settings = get_settings()
        if settings.app_env == "test":
            return _counter.is_allowed(key, limit, window)

        try:
            return await _redis_counter.is_allowed(key, limit, window)
        except Exception as exc:
            if settings.app_env in {"development", "test"}:
                if not self._fallback_warning_logged:
                    logger.warning(
                        "rate_limit_redis_unavailable_falling_back",
                        app_env=settings.app_env,
                        error_class=type(exc).__name__,
                    )
                    self._fallback_warning_logged = True
                return _counter.is_allowed(key, limit, window)

            logger.error(
                "rate_limit_redis_unavailable",
                app_env=settings.app_env,
                error_class=type(exc).__name__,
                exc_info=True,
            )
            return None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip rate limiting for health checks and docs
        if path in _EXEMPT_PATHS:
            return await call_next(request)

        api_key_limit, api_key_window, telegram_limit, telegram_window = _get_rate_limits()

        # Determine rate limit key and parameters
        key: str | None = None
        limit = api_key_limit
        window = api_key_window

        # Check for API key-based requests
        api_key = request.headers.get("X-API-Key")
        if api_key:
            credential_digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:24]
            key = f"api:{credential_digest}"
            limit = api_key_limit
            window = api_key_window

        # Check for Telegram webhook (rate limit by path — single bot)
        if "/webhook/telegram" in path:
            key = "telegram:webhook"
            limit = telegram_limit
            window = telegram_window

        # If no identifiable key, use client IP as fallback
        if key is None:
            client_host = request.client.host if request.client else "unknown"
            key = f"ip:{client_host}"
            limit = api_key_limit
            window = api_key_window

        allowed = await self._is_allowed(key, limit, window)
        if allowed is None:
            body = ErrorResponse(
                error="rate_limit_unavailable",
                message="Rate limiting is temporarily unavailable.",
            )
            return JSONResponse(status_code=503, content=body.model_dump())

        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                key=key,
                path=path,
                limit=limit,
                window_seconds=window,
            )
            retry_after = int(window)
            body = ErrorResponse(
                error="rate_limited",
                message="Too many requests. Please try again later.",
            )
            return JSONResponse(
                status_code=429,
                content=body.model_dump(),
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
