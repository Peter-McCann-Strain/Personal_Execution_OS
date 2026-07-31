"""Fail-closed MCP configuration for the first public release.

No MCP subprocess server is enabled or bundled by default. In particular, the
application must never invoke package runners that can download mutable code at
runtime. A future integration boundary must require an explicit, version-pinned
administrator configuration plus the registry/security hook before it can be
added here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.app.config import Settings


# Deliberately empty. API credentials alone must never activate a subprocess,
# network client, filesystem server, or browser automation server.
DEFAULT_MCP_SERVERS: dict[str, dict[str, Any]] = {}


def get_enabled_servers(_settings: Settings) -> dict[str, dict[str, Any]]:
    """Return no servers until a pinned administrator-managed path exists."""
    return {}


def get_server_descriptions() -> dict[str, str]:
    """Return the descriptions for the deliberately empty public registry."""
    return {}


def _get_setting_value(settings: Settings, attr_name: str) -> str:
    """Extract a plain value without logging secret contents.

    Retained as a small compatibility helper for downstream private
    configurations; it does not activate any server.
    """
    value = getattr(settings, attr_name, None)
    if value is None:
        return ""
    if hasattr(value, "get_secret_value"):
        return str(value.get_secret_value())
    return str(value)
