"""Shared test fixtures."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from src.app.core.redis import close_redis_clients

# Block real API calls in tests by ensuring placeholders stay
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_ALLOWED_USER_IDS", "12345")
os.environ.setdefault("TELEGRAM_WEBHOOK_URL", "https://test.example.com/webhook")
os.environ.setdefault("OLLAMA_HOST", "http://localhost:11434")
os.environ.setdefault("OLLAMA_EMBED_MODEL", "nomic-embed-text:v2-moe")
os.environ.setdefault("CHAT_API_KEY", "test-chat-api-key")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")


@pytest.fixture
def mock_anthropic_client() -> AsyncMock:
    """Mock Anthropic client that returns a canned routing response."""
    client = AsyncMock()
    return client


@pytest_asyncio.fixture(autouse=True)
async def _close_cached_redis_clients_async():
    """Reset cached Redis clients around async tests to prevent socket leakage."""
    await close_redis_clients()
    yield
    await close_redis_clients()


@pytest.fixture(autouse=True)
def _close_cached_redis_clients_sync():
    """Reset cached Redis clients around sync tests as well."""
    asyncio.run(close_redis_clients())
    yield
    asyncio.run(close_redis_clients())


def make_anthropic_response(text: str, input_tokens: int = 50, output_tokens: int = 100):
    """Helper to build a mock Anthropic API response."""
    content_block = MagicMock()
    content_block.text = text

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    response = MagicMock()
    response.content = [content_block]
    response.usage = usage
    return response
