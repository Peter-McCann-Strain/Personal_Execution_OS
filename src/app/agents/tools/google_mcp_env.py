"""Helpers for Google-backed MCP subprocesses.

These subprocesses receive only a bounded environment from the main app, so they
must not depend on the full application Settings model being loadable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GoogleMCPEnv:
    """Credential bundle required by Google MCP subprocesses."""

    client_id: str
    client_secret: str
    refresh_token: str


def load_google_mcp_env() -> GoogleMCPEnv:
    """Read the Google MCP credential contract from environment variables."""
    values = {
        "GOOGLE_CLIENT_ID": os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
        "GOOGLE_CLIENT_SECRET": os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
        "GOOGLE_REFRESH_TOKEN": os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip(),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        missing_list = ", ".join(missing)
        msg = f"Missing Google MCP environment variables: {missing_list}"
        raise RuntimeError(msg)
    return GoogleMCPEnv(
        client_id=values["GOOGLE_CLIENT_ID"],
        client_secret=values["GOOGLE_CLIENT_SECRET"],
        refresh_token=values["GOOGLE_REFRESH_TOKEN"],
    )
