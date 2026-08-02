"""Regression coverage for MCP Python SDK v2 server/bootstrap compatibility."""

from __future__ import annotations

import io
import logging
import sys
from unittest.mock import patch

import pytest
from mcp.server import MCPServer


@pytest.mark.asyncio
async def test_native_mcp_servers_import_and_register_v2_tools() -> None:
    """All dormant native servers must remain importable under the installed SDK."""
    from src.app.agents.tools import (
        filesystem_mcp_server,
        google_calendar_mcp_server,
        google_gmail_mcp_server,
    )

    expected_tools = {
        filesystem_mcp_server.mcp: {"read_file", "list_files", "search_files"},
        google_calendar_mcp_server.mcp: {"list_events", "find_free_slots"},
        google_gmail_mcp_server.mcp: {
            "list_messages",
            "search_messages",
            "read_message",
            "get_thread",
        },
    }

    for server, names in expected_tools.items():
        assert isinstance(server, MCPServer)
        assert {tool.name for tool in await server.list_tools()} == names


def test_subprocess_logging_replaces_stdout_handler_with_stderr() -> None:
    """stdio protocol output must never share a stream with application logs."""
    from src.app.agents.tools import mcp_subprocess_logging

    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    formatter = logging.Formatter("%(levelname)s:%(message)s")
    stdout_handler = logging.StreamHandler(io.StringIO())
    stdout_handler.setLevel(logging.ERROR)
    stdout_handler.setFormatter(formatter)

    def fake_setup_logging(_level: str, _environment: str) -> None:
        root_logger.handlers = [stdout_handler]

    try:
        with patch.object(
            mcp_subprocess_logging,
            "setup_logging",
            side_effect=fake_setup_logging,
        ):
            mcp_subprocess_logging.configure_mcp_subprocess_logging()

        assert len(root_logger.handlers) == 1
        replacement = root_logger.handlers[0]
        assert isinstance(replacement, logging.StreamHandler)
        assert replacement.stream is sys.stderr
        assert replacement.level == logging.ERROR
        assert replacement.formatter is formatter
    finally:
        root_logger.handlers = original_handlers
        root_logger.setLevel(original_level)
