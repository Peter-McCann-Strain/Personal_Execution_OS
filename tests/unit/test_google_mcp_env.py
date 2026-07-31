"""Tests for Google MCP subprocess environment loading."""

from __future__ import annotations

import pytest

from src.app.agents.tools.google_mcp_env import load_google_mcp_env


def test_load_google_mcp_env_reads_expected_values(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "refresh-token")

    creds = load_google_mcp_env()

    assert creds.client_id == "client-id"
    assert creds.client_secret == "client-secret"
    assert creds.refresh_token == "refresh-token"


def test_load_google_mcp_env_fails_with_missing_values(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID, GOOGLE_REFRESH_TOKEN"):
        load_google_mcp_env()
