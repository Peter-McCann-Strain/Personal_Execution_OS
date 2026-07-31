"""Minimal provider boundary for model-backed features.

The existing agent layer still consumes Anthropic-shaped responses. This
adapter isolates client construction and invocation so another provider can be
added behind the same lifecycle without spreading more SDK-specific state.
Response normalization is intentionally a later, separately testable step.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from anthropic import AsyncAnthropic

from src.app.config import Settings
from src.app.core.exceptions import LLMError


@runtime_checkable
class LLMProvider(Protocol):
    """Runtime contract shared by model provider adapters."""

    name: str
    configured: bool

    async def complete(self, **kwargs: Any) -> Any:
        """Generate one model response."""

    async def close(self) -> None:
        """Release provider resources."""


class BaseLLMProvider(ABC):
    """Nominal base used to distinguish adapters from SDK mocks/clients."""

    name: str
    configured: bool

    @abstractmethod
    async def complete(self, **kwargs: Any) -> Any:
        """Generate one model response."""

    @abstractmethod
    async def close(self) -> None:
        """Release provider resources."""


class DisabledLLMProvider(BaseLLMProvider):
    """Explicit no-provider implementation for capture-only installations."""

    name = "disabled"
    configured = False
    client = None

    async def complete(self, **kwargs: Any) -> Any:
        del kwargs
        raise LLMError(
            "No model provider is configured. Set ANTHROPIC_API_KEY or "
            "choose a supported LLM_PROVIDER."
        )

    async def close(self) -> None:
        return None


class AnthropicLLMProvider(BaseLLMProvider):
    """Anthropic adapter preserving the current response contract."""

    name = "anthropic"
    configured = True

    def __init__(self, client: AsyncAnthropic) -> None:
        self.client = client

    async def complete(self, **kwargs: Any) -> Any:
        return await self.client.messages.create(**kwargs)

    async def close(self) -> None:
        await self.client.close()

    def __getattr__(self, name: str) -> Any:
        """Temporarily support legacy SDK-style consumers during migration."""
        return getattr(self.client, name)


def create_llm_provider(
    settings: Settings,
    *,
    anthropic_client_factory: Callable[..., AsyncAnthropic] = AsyncAnthropic,
) -> BaseLLMProvider:
    """Build the configured provider without requiring a cloud account."""
    key = settings.anthropic_api_key.get_secret_value().strip()
    provider_name = getattr(settings, "llm_provider", "anthropic")
    if provider_name == "disabled" or not key:
        return DisabledLLMProvider()
    if provider_name == "anthropic":
        return AnthropicLLMProvider(anthropic_client_factory(api_key=key))
    raise LLMError(f"Unsupported model provider: {provider_name}")
