"""Tests for configuration loading."""

import os
from unittest.mock import patch

import pytest

from src.app.config import Settings


def _base_env() -> dict[str, str]:
    return {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "sk-ant-real-key",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@host:5432/db",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "123:ABCdef",
        "TELEGRAM_ALLOWED_USER_IDS": "111,222",
        "TELEGRAM_WEBHOOK_URL": "https://example.com/webhook",
        "TELEGRAM_WEBHOOK_SECRET": "test-secret",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_EMBED_MODEL": "nomic-embed-text:v2-moe",
        "CHAT_API_KEY": "test-chat-key",
    }


def test_settings_loads_from_env():
    """Settings should load all required values from environment."""
    env = {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "sk-ant-real-key",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@host:5432/db",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "123:ABCdef",
        "TELEGRAM_ALLOWED_USER_IDS": "111,222",
        "TELEGRAM_WEBHOOK_URL": "https://example.com/webhook",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_EMBED_MODEL": "nomic-embed-text:v2-moe",
        "CHAT_API_KEY": "test-chat-key",
        "TELEGRAM_WEBHOOK_SECRET": "test-secret",
    }
    with patch.dict(os.environ, env, clear=False):
        settings = Settings()

    assert settings.app_env == "test"
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-real-key"
    assert settings.allowed_user_ids == [111, 222]


def test_settings_rejects_placeholder_api_key():
    """Settings should crash on placeholder API keys."""
    env = {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "PLACEHOLDER_ANTHROPIC_API_KEY",
        "DATABASE_URL": "PLACEHOLDER_DATABASE_URL",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "PLACEHOLDER_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS": "12345",
        "TELEGRAM_WEBHOOK_URL": "https://example.com/webhook",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_EMBED_MODEL": "nomic-embed-text:v2-moe",
        "CHAT_API_KEY": "test-chat-key",
        "TELEGRAM_WEBHOOK_SECRET": "test-secret",
    }
    with patch.dict(os.environ, env, clear=False), pytest.raises(ValueError, match="placeholder"):
        Settings()


def test_settings_boots_without_cloud_provider_configuration():
    """A clean self-hosted install should not require cloud accounts."""
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://")
    assert settings.redis_url.get_secret_value() == "redis://localhost:6379/0"
    assert settings.llm_configured is False
    assert settings.telegram_configured is False
    assert settings.google_configured is False


def test_remote_tls_can_enable_secure_auth_cookies():
    env = {
        "AUTH_COOKIE_SECURE": "true",
        "AUTH_TRUSTED_ORIGINS": "https://assistant.example.com",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = Settings(_env_file=None)

    assert settings.auth_cookie_secure is True
    assert settings.auth_trusted_origins == "https://assistant.example.com"


def test_telegram_user_ids_parsed_from_comma_string():
    """Comma-separated user IDs should parse into a list of ints."""
    env = {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "sk-ant-real-key",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@host:5432/db",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "123:ABCdef",
        "TELEGRAM_ALLOWED_USER_IDS": "100, 200, 300",
        "TELEGRAM_WEBHOOK_URL": "https://example.com/webhook",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_EMBED_MODEL": "nomic-embed-text:v2-moe",
        "CHAT_API_KEY": "test-chat-key",
        "TELEGRAM_WEBHOOK_SECRET": "test-secret",
    }
    with patch.dict(os.environ, env, clear=False):
        settings = Settings()

    assert settings.allowed_user_ids == [100, 200, 300]


def test_settings_ignore_unrelated_extra_env_vars():
    """Unknown env vars should not break startup."""
    env = {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "sk-ant-real-key",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@host:5432/db",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "123:ABCdef",
        "TELEGRAM_ALLOWED_USER_IDS": "100",
        "TELEGRAM_WEBHOOK_URL": "https://example.com/webhook",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_EMBED_MODEL": "nomic-embed-text:v2-moe",
        "CHAT_API_KEY": "test-chat-key",
        "TELEGRAM_WEBHOOK_SECRET": "test-secret",
        "POSTHOG_API_KEY": "extra-value",
        "SENTRY_DSN": "extra-value",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = Settings(_env_file=None)

    assert settings.app_env == "test"


def test_sentry_configured_false_for_invalid_dsn():
    """Invalid Sentry DSNs should be treated as not configured."""
    env = {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "sk-ant-real-key",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@host:5432/db",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "123:ABCdef",
        "TELEGRAM_ALLOWED_USER_IDS": "100",
        "TELEGRAM_WEBHOOK_URL": "https://example.com/webhook",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_EMBED_MODEL": "nomic-embed-text:v2-moe",
        "CHAT_API_KEY": "test-chat-key",
        "TELEGRAM_WEBHOOK_SECRET": "test-secret",
        "SENTRY_DSN": "https://example.com/sentry-test-dsn",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = Settings(_env_file=None)

    assert settings.sentry_configured is False


def test_sentry_configured_true_for_valid_dsn():
    """Valid-looking Sentry DSNs should enable Sentry configuration."""
    env = {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "sk-ant-real-key",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@host:5432/db",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "123:ABCdef",
        "TELEGRAM_ALLOWED_USER_IDS": "100",
        "TELEGRAM_WEBHOOK_URL": "https://example.com/webhook",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_EMBED_MODEL": "nomic-embed-text:v2-moe",
        "CHAT_API_KEY": "test-chat-key",
        "TELEGRAM_WEBHOOK_SECRET": "test-secret",
        "SENTRY_DSN": "https://public@example.com/123",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = Settings(_env_file=None)

    assert settings.sentry_configured is True


def test_posthog_configured_true_when_api_key_present():
    """PostHog needs an API key and the default explicit destination."""
    env = {
        **_base_env(),
        "POSTHOG_API_KEY": "phc_test_key",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = Settings(_env_file=None)

    assert settings.posthog_configured is True


def test_posthog_configured_false_when_host_is_blank():
    """A key without an approved destination must fail closed."""
    env = {
        **_base_env(),
        "POSTHOG_API_KEY": "phc_test_key",
        "POSTHOG_HOST": "",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = Settings(_env_file=None)

    assert settings.posthog_configured is False


def test_workflow_shadow_specialists_are_normalized():
    """Shadow specialist config should parse into normalized specialist names."""
    env = {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "sk-ant-real-key",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@host:5432/db",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "123:ABCdef",
        "TELEGRAM_ALLOWED_USER_IDS": "100",
        "TELEGRAM_WEBHOOK_URL": "https://example.com/webhook",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_EMBED_MODEL": "nomic-embed-text:v2-moe",
        "CHAT_API_KEY": "test-chat-key",
        "TELEGRAM_WEBHOOK_SECRET": "test-secret",
        "WORKFLOW_SHADOW_MODE_SPECIALISTS": " Review, MEMORY ,project ",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = Settings(_env_file=None)

    assert settings.workflow_shadow_specialist_names == ["review", "memory", "project"]


def test_workflow_live_runtime_specialists_are_normalized():
    """Live runtime specialist config should parse into normalized specialist names."""
    env = {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ANTHROPIC_API_KEY": "sk-ant-real-key",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@host:5432/db",
        "REDIS_URL": "redis://localhost:6379",
        "TELEGRAM_BOT_TOKEN": "123:ABCdef",
        "TELEGRAM_ALLOWED_USER_IDS": "100",
        "TELEGRAM_WEBHOOK_URL": "https://example.com/webhook",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_EMBED_MODEL": "nomic-embed-text:v2-moe",
        "CHAT_API_KEY": "test-chat-key",
        "TELEGRAM_WEBHOOK_SECRET": "test-secret",
        "WORKFLOW_LIVE_RUNTIME_SPECIALISTS": " Review, MEMORY ,project, plan_day ",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = Settings(_env_file=None)

    assert settings.workflow_live_runtime_specialist_names == [
        "review",
        "memory",
        "project",
        "plan_day",
    ]


def test_mcp_defaults_are_fail_closed():
    with patch.dict(os.environ, _base_env(), clear=True):
        settings = Settings(_env_file=None)

    assert settings.mcp_tool_allowlist == {}
    assert settings.mcp_registry_verification_enabled is False
