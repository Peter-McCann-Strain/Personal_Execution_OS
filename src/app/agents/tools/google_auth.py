"""Shared Google OAuth2 base class for Calendar and Gmail services.

Extracts the duplicated token refresh logic and HTTP retry decorator
into a single reusable base.
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.app.core.exceptions import (
    ConnectorBackendError,
    ConnectorError,
    ConnectorRateLimitedError,
    ConnectorTokenExpiredError,
    ConnectorUnknownError,
)

logger = structlog.get_logger()
_retry_logger = logging.getLogger("google_oauth_retry")

# Token refresh buffer — refresh 5 minutes before expiry
_TOKEN_REFRESH_BUFFER_SECONDS = 300

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def translate_google_error(exc: BaseException, connector: str) -> ConnectorError:
    """Map an arbitrary exception to a categorised ``ConnectorError``.

    * 401 / 403 / invalid_grant → :class:`ConnectorTokenExpiredError`
    * 429                       → :class:`ConnectorRateLimitedError`
    * 5xx                       → :class:`ConnectorBackendError`
    * anything else             → :class:`ConnectorUnknownError`
    """
    if isinstance(exc, ConnectorError):
        # Already categorised — preserve the inner exception type.
        if exc.connector is None:
            exc.connector = connector
        return exc

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body_text = ""
        try:
            body_text = exc.response.text or ""
        except Exception:  # response not consumable — best effort only
            body_text = ""

        if status in (401, 403) or "invalid_grant" in body_text:
            return ConnectorTokenExpiredError(
                f"{connector} access revoked or refresh token invalid (HTTP {status}).",
                connector=connector,
                original=exc,
            )
        if status == 429:
            return ConnectorRateLimitedError(
                f"{connector} rate limit hit (HTTP 429).",
                connector=connector,
                original=exc,
            )
        if 500 <= status < 600:
            return ConnectorBackendError(
                f"{connector} provider error (HTTP {status}).",
                connector=connector,
                original=exc,
            )
        return ConnectorUnknownError(
            f"{connector} request failed (HTTP {status}).",
            connector=connector,
            original=exc,
        )

    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
        return ConnectorBackendError(
            f"{connector} network error: {exc.__class__.__name__}.",
            connector=connector,
            original=exc,
        )

    return ConnectorUnknownError(
        f"{connector} request failed: {exc.__class__.__name__}: {exc}",
        connector=connector,
        original=exc,
    )


google_http_retry = retry(
    retry=retry_if_exception_type(
        (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout),
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(_retry_logger, logging.WARNING),
    reraise=True,
)


class GoogleOAuthClient:
    """Base class for Google API services with shared OAuth2 token management.

    Manages an httpx.AsyncClient and caches OAuth2 access tokens,
    refreshing them automatically before expiry.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._http_client = httpx.AsyncClient(timeout=30.0)

        # Access token cache
        self._cached_token: str | None = None
        self._token_expiry: datetime | None = None

    @google_http_retry
    async def _get_access_token(self) -> str:
        """Get a valid OAuth2 access token, using cache when possible.

        Tokens are cached for their lifetime minus a 5-minute buffer.
        Only refreshes when the cached token is expired or about to expire.
        """
        now = datetime.now(UTC)

        if (
            self._cached_token is not None
            and self._token_expiry is not None
            and now < self._token_expiry
        ):
            return self._cached_token

        response = await self._http_client.post(
            TOKEN_ENDPOINT,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        token_data = response.json()

        self._cached_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)
        self._token_expiry = now + timedelta(seconds=expires_in - _TOKEN_REFRESH_BUFFER_SECONDS)

        logger.debug("google_token_refreshed", expires_in=expires_in)
        return self._cached_token

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http_client.aclose()
