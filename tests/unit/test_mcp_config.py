"""Public-release MCP configuration must remain fail-closed."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pydantic import SecretStr

from src.app.agents.tools.mcp_config import (
    DEFAULT_MCP_SERVERS,
    _get_setting_value,
    get_enabled_servers,
    get_server_descriptions,
)
from src.app.config import Settings


def test_no_mcp_servers_are_bundled_or_enabled_by_default() -> None:
    settings = MagicMock()

    assert DEFAULT_MCP_SERVERS == {}
    assert get_enabled_servers(settings) == {}
    assert get_server_descriptions() == {}


def test_credentials_do_not_implicitly_enable_mcp_servers() -> None:
    settings = MagicMock(
        google_client_id="configured",
        google_client_secret=SecretStr("configured-secret"),
        google_refresh_token=SecretStr("configured-refresh"),
        tavily_api_key=SecretStr("configured-tavily"),
    )

    assert get_enabled_servers(settings) == {}


def test_runtime_package_download_commands_are_absent() -> None:
    source = Path("src/app/agents/tools/mcp_config.py").read_text(encoding="utf-8")

    assert '"uvx"' not in source
    assert '"npx"' not in source
    assert '"-y"' not in source


def test_network_tool_allowlist_is_empty_and_registry_probe_is_off() -> None:
    assert Settings.model_fields["mcp_tool_allowlist"].default == {}
    assert Settings.model_fields["mcp_registry_verification_enabled"].default is False


def test_compatibility_value_helper_handles_plain_secrets_and_missing() -> None:
    settings = MagicMock()
    settings.plain = "value"
    settings.secret = SecretStr("hidden")
    settings.empty = None

    assert _get_setting_value(settings, "plain") == "value"
    assert _get_setting_value(settings, "secret") == "hidden"
    assert _get_setting_value(settings, "empty") == ""
