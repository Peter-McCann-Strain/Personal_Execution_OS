"""Integration tests for the local smoke-api CLI against the real app harness."""

from __future__ import annotations

import argparse
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from scripts.smoke_api import run_smoke_checks
from src.app.domain.models import ChatResponse


def _make_args(**overrides: object) -> argparse.Namespace:
    defaults = {
        "base_url": "http://test",
        "api_key": os.environ["CHAT_API_KEY"],
        "timeout": 5.0,
        "require_ok_health": False,
        "chat_probe": "Smoke test the deployment chat path.",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.mark.asyncio
async def test_smoke_api_runs_against_real_app_routes(integration_client, monkeypatch):
    """Run the smoke-api logic through the real FastAPI app transport."""
    client, mock_session, _mock_anthropic = integration_client

    mock_session.execute = AsyncMock(return_value=MagicMock())

    original_async_client = httpx.AsyncClient

    def async_client_factory(**kwargs):
        return original_async_client(transport=client._transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", async_client_factory)

    mock_response = ChatResponse(
        content="Smoke response.",
        agent="diary",
        metadata={
            "tool_calls": [],
            "tool_count": 0,
            "errors": 0,
            "tokens_used": 16,
        },
    )

    with (
        patch(
            "src.app.api.routes.chat.process_message",
            new_callable=AsyncMock,
            return_value=mock_response,
        ),
        patch(
            "src.app.api.routes.chat._get_conversation_context",
            return_value=None,
        ),
        patch(
            "src.app.api.routes.chat._retrieve_supporting_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        results = await run_smoke_checks(_make_args())

    assert results["openapi"]["status"] == "ok"
    assert results["docs"]["status"] == "ok"
    assert results["redoc"]["status"] == "ok"
    assert results["chat"]["agent"] == "diary"
    assert results["chat_stream"]["events"][-1] == "message_end"
    assert results["chat_context"]["inspection"]["totalTokensEstimate"] > 0
