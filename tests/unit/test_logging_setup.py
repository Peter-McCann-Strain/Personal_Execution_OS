"""Tests for structured logging setup."""

import logging

import structlog

from src.app.core.logging import setup_logging


def _reset_logging():
    """Reset logging state for clean tests."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# setup_logging — development mode uses ConsoleRenderer
# ---------------------------------------------------------------------------


def test_setup_logging_dev():
    _reset_logging()
    setup_logging("DEBUG", "development")

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1

    handler = root.handlers[0]
    assert isinstance(handler, logging.StreamHandler)

    # The formatter should be a structlog ProcessorFormatter
    formatter = handler.formatter
    assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)


# ---------------------------------------------------------------------------
# setup_logging — production mode uses JSONRenderer
# ---------------------------------------------------------------------------


def test_setup_logging_production():
    _reset_logging()
    setup_logging("INFO", "production")

    root = logging.getLogger()
    assert root.level == logging.INFO
    assert len(root.handlers) == 1

    handler = root.handlers[0]
    formatter = handler.formatter
    assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)


# ---------------------------------------------------------------------------
# setup_logging — log level mapping
# ---------------------------------------------------------------------------


def test_setup_logging_warning_level():
    _reset_logging()
    setup_logging("WARNING", "development")
    assert logging.getLogger().level == logging.WARNING


def test_setup_logging_error_level():
    _reset_logging()
    setup_logging("ERROR", "production")
    assert logging.getLogger().level == logging.ERROR


# ---------------------------------------------------------------------------
# setup_logging — noisy libraries quieted
# ---------------------------------------------------------------------------


def test_noisy_libraries_quieted():
    _reset_logging()
    setup_logging("DEBUG", "development")

    assert logging.getLogger("uvicorn.access").level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.WARNING


# ---------------------------------------------------------------------------
# setup_logging — clears existing handlers
# ---------------------------------------------------------------------------


def test_clears_existing_handlers():
    _reset_logging()
    root = logging.getLogger()
    root.addHandler(logging.StreamHandler())
    root.addHandler(logging.StreamHandler())
    assert len(root.handlers) == 2

    setup_logging("INFO", "development")
    assert len(root.handlers) == 1  # Only the new handler
