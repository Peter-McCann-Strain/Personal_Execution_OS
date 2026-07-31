"""Tests for GoogleOAuthClient — token caching and refresh."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.app.agents.tools.google_auth import GoogleOAuthClient, translate_google_error
from src.app.core.exceptions import (
    ConnectorBackendError,
    ConnectorRateLimitedError,
    ConnectorTokenExpiredError,
    ConnectorUnknownError,
)


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def oauth_client() -> GoogleOAuthClient:
    client = GoogleOAuthClient(
        client_id="test-client-id",
        client_secret="test-client-secret",
        refresh_token="test-refresh-token",
    )
    client._http_client = AsyncMock(spec=httpx.AsyncClient)
    return client


# ---------------------------------------------------------------------------
# Token caching — valid token returned from cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_access_token_cached(oauth_client: GoogleOAuthClient):
    """Cached token returned without network call."""
    oauth_client._cached_token = "cached-access-token"
    oauth_client._token_expiry = datetime.now(UTC) + timedelta(hours=1)

    token = await oauth_client._get_access_token()
    assert token == "cached-access-token"
    oauth_client._http_client.post.assert_not_called()


# ---------------------------------------------------------------------------
# Token refresh — expired token triggers refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_access_token_expired_refreshes(oauth_client: GoogleOAuthClient):
    """Expired token triggers a refresh request."""
    oauth_client._cached_token = "old-token"
    oauth_client._token_expiry = datetime.now(UTC) - timedelta(minutes=1)  # expired

    oauth_client._http_client.post.return_value = _mock_response(
        {"access_token": "new-token", "expires_in": 3600}
    )

    token = await oauth_client._get_access_token()
    assert token == "new-token"
    assert oauth_client._cached_token == "new-token"
    assert oauth_client._token_expiry is not None
    oauth_client._http_client.post.assert_called_once()


# ---------------------------------------------------------------------------
# Token refresh — no cached token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_access_token_no_cache(oauth_client: GoogleOAuthClient):
    """No cached token triggers refresh."""
    oauth_client._http_client.post.return_value = _mock_response(
        {"access_token": "fresh-token", "expires_in": 7200}
    )

    token = await oauth_client._get_access_token()
    assert token == "fresh-token"
    oauth_client._http_client.post.assert_called_once()


# ---------------------------------------------------------------------------
# Token refresh — verifies correct request parameters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_sends_correct_params(oauth_client: GoogleOAuthClient):
    oauth_client._http_client.post.return_value = _mock_response(
        {"access_token": "t", "expires_in": 3600}
    )

    await oauth_client._get_access_token()

    call_kwargs = oauth_client._http_client.post.call_args
    assert call_kwargs.args[0] == "https://oauth2.googleapis.com/token"
    data = call_kwargs.kwargs["data"]
    assert data["client_id"] == "test-client-id"
    assert data["client_secret"] == "test-client-secret"
    assert data["refresh_token"] == "test-refresh-token"
    assert data["grant_type"] == "refresh_token"


# ---------------------------------------------------------------------------
# Token refresh — HTTP error propagates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_failure_raises(oauth_client: GoogleOAuthClient):
    """HTTP error during refresh propagates to caller."""
    oauth_client._http_client.post.return_value = MagicMock(spec=httpx.Response)
    oauth_client._http_client.post.return_value.raise_for_status.side_effect = (
        httpx.HTTPStatusError("401", request=MagicMock(), response=MagicMock())
    )

    with pytest.raises(httpx.HTTPStatusError):
        await oauth_client._get_access_token()


# ---------------------------------------------------------------------------
# Token expiry buffer — token expires 5 min before actual expiry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_expiry_buffer(oauth_client: GoogleOAuthClient):
    """Token is refreshed early due to 300s buffer."""
    oauth_client._http_client.post.return_value = _mock_response(
        {"access_token": "buffered-token", "expires_in": 3600}
    )

    await oauth_client._get_access_token()

    # Expiry should be ~ now + (3600 - 300) = now + 3300 seconds
    expected_max = datetime.now(UTC) + timedelta(seconds=3305)
    expected_min = datetime.now(UTC) + timedelta(seconds=3290)
    assert expected_min <= oauth_client._token_expiry <= expected_max


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close(oauth_client: GoogleOAuthClient):
    await oauth_client.close()
    oauth_client._http_client.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# translate_google_error — categorisation of httpx failures
# ---------------------------------------------------------------------------


def _http_status_error(status: int, body: str = "") -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError carrying a real Response."""
    request = httpx.Request("GET", "https://example.invalid/")
    response = httpx.Response(status, request=request, text=body)
    return httpx.HTTPStatusError("boom", request=request, response=response)


@pytest.mark.parametrize(
    ("status", "expected_cls", "actionable"),
    [
        (401, ConnectorTokenExpiredError, True),
        (403, ConnectorTokenExpiredError, True),
        (429, ConnectorRateLimitedError, False),
        (500, ConnectorBackendError, False),
        (502, ConnectorBackendError, False),
        (503, ConnectorBackendError, False),
        (418, ConnectorUnknownError, False),
    ],
)
def test_translate_google_error_status_codes(status, expected_cls, actionable):
    """Each HTTP status family maps to the right ConnectorError subclass."""
    exc = _http_status_error(status)
    translated = translate_google_error(exc, connector="gmail")
    assert isinstance(translated, expected_cls)
    assert translated.connector == "gmail"
    assert translated.actionable is actionable
    assert translated.original is exc


def test_translate_google_error_invalid_grant_body():
    """invalid_grant in the body is treated as an expired token even on 400."""
    exc = _http_status_error(400, body='{"error": "invalid_grant"}')
    translated = translate_google_error(exc, connector="calendar")
    assert isinstance(translated, ConnectorTokenExpiredError)
    assert translated.connector == "calendar"
    assert translated.actionable is True


def test_translate_google_error_network_failure():
    """Network-level failures are treated as backend errors."""
    exc = httpx.ConnectError("dns failure")
    translated = translate_google_error(exc, connector="gmail")
    assert isinstance(translated, ConnectorBackendError)
    assert translated.actionable is False


def test_translate_google_error_arbitrary_exception():
    """Unknown exception types fall through to ConnectorUnknownError."""
    exc = RuntimeError("something unexpected")
    translated = translate_google_error(exc, connector="gmail")
    assert isinstance(translated, ConnectorUnknownError)
    assert translated.original is exc


def test_translate_google_error_passthrough_for_already_categorised():
    """An already-categorised ConnectorError is returned untouched."""
    original = ConnectorTokenExpiredError("already done", connector=None)
    translated = translate_google_error(original, connector="gmail")
    assert translated is original
    # And we backfill the connector if it was unset.
    assert translated.connector == "gmail"
