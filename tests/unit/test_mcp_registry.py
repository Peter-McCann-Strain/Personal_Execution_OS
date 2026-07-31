"""Tests for MCP registry verification (P6.7)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.app.agents.tools.mcp_registry import (
    TrustEntry,
    TrustStore,
    fetch_registry_entry,
    format_publisher_changed_alert,
    verify_server_publisher,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_registry_response(
    name: str = "tavily-search",
    publisher_id: str = "publisher-1",
    version: str = "1.2.3",
) -> httpx.Response:
    payload = {
        "servers": [
            {
                "name": name,
                "version": version,
                "publisher": {"id": publisher_id, "name": publisher_id},
            }
        ]
    }
    return httpx.Response(200, json=payload)


def _mock_client_with_response(response: httpx.Response) -> MagicMock:
    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=response)
    return client


def _mock_client_raising(exc: Exception) -> MagicMock:
    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(side_effect=exc)
    return client


# ---------------------------------------------------------------------------
# Test 1: registry hit with matching cache (no change, allow connect)
# and test 2: new server (first-run bootstrap)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_server_bootstrap_trusts_on_first_use(tmp_path: Path):
    """No cache + registry hit → first_run=True, entry populated, allow_connect=True."""
    store = TrustStore(trust_dir=tmp_path)
    client = _mock_client_with_response(_fake_registry_response(name="tavily-search"))

    result = await verify_server_publisher(
        "tavily-search",
        trust_store=store,
        http_client=client,
    )

    assert result.allow_connect is True
    assert result.first_run is True
    assert result.in_registry is True
    assert result.entry is not None
    assert result.entry.publisher_id == "publisher-1"
    assert result.entry.server_version == "1.2.3"


# ---------------------------------------------------------------------------
# Test 2: registry miss (unreachable) + cache exists → soft-fail using cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cached_fallback_when_registry_unreachable(tmp_path: Path):
    """Registry unreachable + cache present → allow_connect=True with cached_fallback flag."""
    store = TrustStore(trust_dir=tmp_path)
    cached = TrustEntry(
        server_name="tavily-search",
        publisher_id="publisher-1",
        publisher_name="publisher-1",
        server_version="1.0.0",
        in_registry=True,
        last_verified_utc="2026-04-10T00:00:00+00:00",
    )
    store.save(cached)

    client = _mock_client_raising(httpx.ConnectError("dns failure"))

    result = await verify_server_publisher(
        "tavily-search",
        trust_store=store,
        http_client=client,
    )

    assert result.allow_connect is True
    assert result.cached_fallback is True
    assert result.entry is not None
    assert result.entry.publisher_id == "publisher-1"


# ---------------------------------------------------------------------------
# Test 3: publisher change detection → refuse connect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publisher_change_refuses_connect(tmp_path: Path):
    """Cached publisher != registry publisher → allow_connect=False + alert data."""
    store = TrustStore(trust_dir=tmp_path)
    cached = TrustEntry(
        server_name="tavily-search",
        publisher_id="old-publisher",
        publisher_name="old-publisher",
        server_version="1.0.0",
        in_registry=True,
        last_verified_utc="2026-04-10T00:00:00+00:00",
    )
    store.save(cached)

    client = _mock_client_with_response(_fake_registry_response(publisher_id="rogue-publisher"))

    result = await verify_server_publisher(
        "tavily-search",
        trust_store=store,
        http_client=client,
    )

    assert result.allow_connect is False
    assert result.publisher_changed is True
    assert result.old_publisher == "old-publisher"
    assert result.new_publisher == "rogue-publisher"

    alert = format_publisher_changed_alert(
        "tavily-search",
        result.old_publisher,
        result.new_publisher,
    )
    assert "tavily-search" in alert
    assert "old-publisher" in alert
    assert "rogue-publisher" in alert
    assert "rug-pull" in alert.lower() or "squatted" in alert.lower()


# ---------------------------------------------------------------------------
# Test 4: registry reachable but server not listed → soft-fail bootstrap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_empty_response_first_run(tmp_path: Path):
    """Registry returns empty + no cache → first_run with empty entry (no crash)."""
    store = TrustStore(trust_dir=tmp_path)
    empty_response = httpx.Response(200, json={"servers": []})
    client = _mock_client_with_response(empty_response)

    result = await verify_server_publisher(
        "obscure-server",
        trust_store=store,
        http_client=client,
    )

    assert result.allow_connect is True
    assert result.first_run is True
    assert result.entry is not None
    # Registry couldn't confirm the publisher — entry has no publisher_id yet.
    assert result.entry.publisher_id == ""


# ---------------------------------------------------------------------------
# Test 5: fetch_registry_entry parses response correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_registry_entry_returns_exact_match():
    """fetch_registry_entry picks the exact-name match from multi-result responses."""
    payload = {
        "servers": [
            {"name": "tavily-search-forked", "publisher": {"id": "other"}},
            {"name": "tavily-search", "publisher": {"id": "publisher-1"}},
        ]
    }
    response = httpx.Response(200, json=payload)
    client = _mock_client_with_response(response)

    entry = await fetch_registry_entry("tavily-search", client=client)

    assert entry is not None
    assert entry["name"] == "tavily-search"
    assert entry["publisher"]["id"] == "publisher-1"
