"""Logging helpers for MCP subprocess servers.

MCP stdio servers must keep stdout reserved for protocol messages. Any app logs
or library logs need to go to stderr instead.
"""

from __future__ import annotations

import logging
import sys

from src.app.core.logging import setup_logging


def configure_mcp_subprocess_logging() -> None:
    """Route subprocess logs to stderr and suppress non-essential noise."""
    setup_logging("WARNING", "production")

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if isinstance(handler, logging.StreamHandler):
            replacement = logging.StreamHandler(sys.stderr)
            replacement.setLevel(handler.level)
            replacement.setFormatter(handler.formatter)
            for log_filter in handler.filters:
                replacement.addFilter(log_filter)
            root_logger.removeHandler(handler)
            handler.close()
            root_logger.addHandler(replacement)

    logging.getLogger("httpx").setLevel(logging.WARNING)
