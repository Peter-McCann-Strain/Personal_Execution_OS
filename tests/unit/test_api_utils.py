"""Tests for shared API utility helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import literal_column, select

from src.app.api.utils import check_google_configured, format_datetime, paginated_count


def test_format_datetime_handles_none():
    """format_datetime returns None unchanged."""
    assert format_datetime(None) is None


def test_format_datetime_formats_aware_datetime():
    """format_datetime serializes datetimes to ISO-8601."""
    dt = datetime(2026, 4, 8, 12, 0, tzinfo=UTC)
    assert format_datetime(dt) == "2026-04-08T12:00:00+00:00"


@pytest.mark.asyncio
async def test_paginated_count_uses_subquery_and_scalar_one():
    """paginated_count should wrap the query in a count subquery."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = 17
    session.execute = AsyncMock(return_value=result)

    query = select(literal_column("1"))

    assert await paginated_count(session, query) == 17
    session.execute.assert_awaited_once()


def test_check_google_configured_allows_configured_settings():
    """check_google_configured should do nothing when Google is configured."""
    mock_settings = MagicMock()
    mock_settings.google_configured = True

    with patch("src.app.api.utils.get_settings", return_value=mock_settings):
        check_google_configured()


def test_check_google_configured_raises_when_unconfigured():
    """check_google_configured should raise a 503 when Google is not configured."""
    mock_settings = MagicMock()
    mock_settings.google_configured = False

    with (
        patch("src.app.api.utils.get_settings", return_value=mock_settings),
        pytest.raises(
            HTTPException,
        ) as exc_info,
    ):
        check_google_configured()

    assert exc_info.value.status_code == 503
    assert "Google is not configured" in exc_info.value.detail
