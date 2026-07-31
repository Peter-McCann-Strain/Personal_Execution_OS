"""Test-environment bootstrap for schemathesis contract tests.

Schemathesis loads the schema from the ASGI app, which in turn invokes the
app's lifespan — that lifespan connects to Postgres, Redis, Telegram, etc.
For contract tests we deliberately replace lifespan with a no-op and override
auth + DB session deps with mocks so every route is reachable without touching
external infrastructure.
"""

from __future__ import annotations

import os

# Set test env *before* importing the app, mirroring tests/conftest.py.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_ALLOWED_USER_IDS", "12345")
os.environ.setdefault("TELEGRAM_WEBHOOK_URL", "https://test.example.com/webhook")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("CHAT_API_KEY", "test-chat-api-key")

# Schemathesis fuzzes dozens of requests per operation — raise the rate limit
# ceiling so the in-memory limiter doesn't make 429 look like a contract bug.
os.environ.setdefault("RATE_LIMIT_API_RPM", "1000000")
os.environ.setdefault("RATE_LIMIT_API_WINDOW", "1")
os.environ.setdefault("RATE_LIMIT_TELEGRAM_RPM", "1000000")
os.environ.setdefault("RATE_LIMIT_TELEGRAM_WINDOW", "1")
