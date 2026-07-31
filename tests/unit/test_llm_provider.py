"""Provider boundary contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from src.app.core.exceptions import LLMError
from src.app.core.llm import (
    AnthropicLLMProvider,
    DisabledLLMProvider,
    create_llm_provider,
)


def _settings(*, provider: str = "anthropic", key: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        llm_provider=provider,
        anthropic_api_key=SecretStr(key),
    )


def test_missing_key_selects_disabled_provider() -> None:
    provider = create_llm_provider(_settings())
    assert isinstance(provider, DisabledLLMProvider)
    assert provider.configured is False


@pytest.mark.asyncio
async def test_disabled_provider_fails_only_when_model_feature_is_used() -> None:
    provider = DisabledLLMProvider()
    with pytest.raises(LLMError, match="No model provider"):
        await provider.complete(model="logical-role")
    await provider.close()


@pytest.mark.asyncio
async def test_anthropic_adapter_delegates_completion_and_close() -> None:
    response = MagicMock()
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    client.close = AsyncMock()
    factory = MagicMock(return_value=client)

    provider = create_llm_provider(
        _settings(key="test-key"),
        anthropic_client_factory=factory,
    )

    assert isinstance(provider, AnthropicLLMProvider)
    assert await provider.complete(model="test-model", messages=[]) is response
    await provider.close()
    client.messages.create.assert_awaited_once_with(model="test-model", messages=[])
    client.close.assert_awaited_once()
