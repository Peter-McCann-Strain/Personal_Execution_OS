"""Unit tests for the OAuth 2.1 MCP client (Phase 6.0).

Covers:

- PKCE ``code_verifier`` / ``code_challenge`` correctness (RFC 7636).
- Dynamic Client Registration happy path (RFC 7591, mocked HTTP).
- Every token request includes the ``resource`` indicator (RFC 8707).
- Token refresh flow.
- Encrypted round-trip of stored registrations.
- Cached token reused inside its validity window.

All HTTP interaction is mocked via ``httpx.MockTransport`` — no real network
traffic and no real OAuth endpoints touched.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.app.agents.tools.mcp_oauth import (
    OAuthClient,
    StoredRegistration,
    derive_pkce_challenge,
    generate_pkce_verifier,
)
from src.app.core.exceptions import MCPError

# ---------------------------------------------------------------------------
# PKCE (RFC 7636)
# ---------------------------------------------------------------------------


class TestPKCE:
    """Verify the code verifier / challenge pair round-trips correctly."""

    def test_verifier_length_in_range(self):
        v = generate_pkce_verifier()
        assert 43 <= len(v) <= 128

    def test_verifier_url_safe_charset(self):
        v = generate_pkce_verifier()
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        assert set(v) <= allowed

    def test_challenge_matches_sha256_of_verifier(self):
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # RFC 7636 §4.2 example
        expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        assert derive_pkce_challenge(verifier) == expected

    def test_challenge_stable_for_fresh_verifier(self):
        verifier = generate_pkce_verifier()
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert derive_pkce_challenge(verifier) == expected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


MASTER_SECRET = "test-oauth-master-secret-01234567"  # >=16 chars
SERVER = "acme"
RESOURCE = "https://mcp.acme.test"
AUTHZ_ENDPOINT = "https://as.acme.test/authorize"
TOKEN_ENDPOINT = "https://as.acme.test/token"
REGISTRATION_ENDPOINT = "https://as.acme.test/register"


def _metadata_handler() -> httpx.MockTransport:
    """Return a mock transport that answers DCR + metadata + token calls."""
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/oauth-protected-resource"):
            return httpx.Response(
                200,
                json={"authorization_servers": ["https://as.acme.test"]},
            )
        if url.endswith("/.well-known/oauth-authorization-server"):
            return httpx.Response(
                200,
                json={
                    "authorization_endpoint": AUTHZ_ENDPOINT,
                    "token_endpoint": TOKEN_ENDPOINT,
                    "registration_endpoint": REGISTRATION_ENDPOINT,
                },
            )
        if url == REGISTRATION_ENDPOINT:
            return httpx.Response(
                201,
                json={
                    "client_id": "client-abc",
                    "client_secret": "secret-xyz",
                },
            )
        if url == TOKEN_ENDPOINT:
            body = dict(urllib.parse.parse_qsl(request.content.decode()))
            calls.append(body)
            # Simulate a refresh token rotation on authorization_code,
            # but NOT on subsequent refresh calls.
            payload = {
                "access_token": f"at-{len(calls)}",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "mcp",
            }
            if body.get("grant_type") == "authorization_code":
                payload["refresh_token"] = "rt-1"
            return httpx.Response(200, json=payload)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    transport.calls = calls  # type: ignore[attr-defined]
    return transport


def _make_client(tmp_path: Path, transport: httpx.MockTransport | None = None) -> OAuthClient:
    http = httpx.AsyncClient(transport=transport or _metadata_handler())
    return OAuthClient(MASTER_SECRET, storage_dir=tmp_path, http_client=http)


# ---------------------------------------------------------------------------
# Master-secret guard
# ---------------------------------------------------------------------------


class TestMasterSecretGuard:
    def test_short_secret_rejected(self, tmp_path: Path):
        with pytest.raises(MCPError, match="at least 16 characters"):
            OAuthClient("too-short", storage_dir=tmp_path)

    def test_empty_secret_rejected(self, tmp_path: Path):
        with pytest.raises(MCPError):
            OAuthClient("", storage_dir=tmp_path)


# ---------------------------------------------------------------------------
# Dynamic Client Registration (RFC 7591)
# ---------------------------------------------------------------------------


class TestDynamicClientRegistration:
    async def test_happy_path_stores_credentials(self, tmp_path: Path):
        transport = _metadata_handler()
        client = _make_client(tmp_path, transport)
        record = await client.register_client(SERVER, metadata_url=RESOURCE, scope="mcp")
        assert record.client_id == "client-abc"
        assert record.client_secret == "secret-xyz"
        assert record.token_endpoint == TOKEN_ENDPOINT
        assert record.authorization_endpoint == AUTHZ_ENDPOINT
        # Persisted as encrypted envelope on disk.
        path = tmp_path / f"{SERVER}.json"
        assert path.exists()
        envelope = json.loads(path.read_text())
        assert envelope["v"] == "aes-gcm-pbkdf2-v1"
        await client.aclose()

    async def test_registration_failure_raises(self, tmp_path: Path):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.endswith("/.well-known/oauth-protected-resource"):
                return httpx.Response(200, json={"authorization_servers": []})
            if url.endswith("/.well-known/oauth-authorization-server"):
                return httpx.Response(
                    200,
                    json={
                        "authorization_endpoint": AUTHZ_ENDPOINT,
                        "token_endpoint": TOKEN_ENDPOINT,
                        "registration_endpoint": REGISTRATION_ENDPOINT,
                    },
                )
            if url == REGISTRATION_ENDPOINT:
                return httpx.Response(400, json={"error": "invalid_client_metadata"})
            return httpx.Response(404)

        client = _make_client(tmp_path, httpx.MockTransport(handler))
        with pytest.raises(MCPError, match="Dynamic Client Registration failed"):
            await client.register_client(SERVER, metadata_url=RESOURCE)
        await client.aclose()


# ---------------------------------------------------------------------------
# Resource Indicator (RFC 8707) on every token request
# ---------------------------------------------------------------------------


class TestResourceIndicator:
    async def test_exchange_code_sends_resource(self, tmp_path: Path):
        transport = _metadata_handler()
        client = _make_client(tmp_path, transport)
        record = await client.register_client(SERVER, metadata_url=RESOURCE)
        await client.exchange_code(
            record,
            code="authz-code",
            code_verifier="ver",
            redirect_uri="http://127.0.0.1:9999/callback",
        )
        calls = transport.calls  # type: ignore[attr-defined]
        # Exactly one token call so far — the exchange.
        assert len(calls) == 1
        assert calls[0]["resource"] == RESOURCE
        assert calls[0]["grant_type"] == "authorization_code"
        assert calls[0]["code_verifier"] == "ver"
        await client.aclose()

    async def test_refresh_sends_resource(self, tmp_path: Path):
        transport = _metadata_handler()
        client = _make_client(tmp_path, transport)
        record = await client.register_client(SERVER, metadata_url=RESOURCE)
        await client.exchange_code(
            record,
            code="authz-code",
            code_verifier="ver",
            redirect_uri="http://127.0.0.1:9999/callback",
        )
        # Force refresh by pushing expiry into the past.
        record.expires_at = time.time() - 10
        client._save(record)
        await client.acquire_token(SERVER, RESOURCE)
        calls = transport.calls  # type: ignore[attr-defined]
        refresh_calls = [c for c in calls if c.get("grant_type") == "refresh_token"]
        assert len(refresh_calls) == 1
        assert refresh_calls[0]["resource"] == RESOURCE
        assert refresh_calls[0]["refresh_token"] == "rt-1"
        await client.aclose()


# ---------------------------------------------------------------------------
# Token refresh path
# ---------------------------------------------------------------------------


class TestRefreshPath:
    async def test_acquire_token_triggers_refresh_when_near_expiry(self, tmp_path: Path):
        transport = _metadata_handler()
        client = _make_client(tmp_path, transport)
        record = await client.register_client(SERVER, metadata_url=RESOURCE)
        await client.exchange_code(
            record,
            code="authz-code",
            code_verifier="ver",
            redirect_uri="http://127.0.0.1:9999/callback",
        )
        # Simulate token near expiry (<5 min remaining)
        record.expires_at = time.time() + 10
        client._save(record)
        token = await client.acquire_token(SERVER, RESOURCE)
        assert token.startswith("at-")
        # Two token calls total: initial exchange + refresh.
        assert len(transport.calls) == 2  # type: ignore[attr-defined]
        await client.aclose()


# ---------------------------------------------------------------------------
# Encrypted storage round-trip
# ---------------------------------------------------------------------------


class TestStorageRoundTrip:
    async def test_encrypt_then_decrypt_preserves_all_fields(self, tmp_path: Path):
        client = _make_client(tmp_path)
        record = StoredRegistration(
            server=SERVER,
            resource_uri=RESOURCE,
            authorization_endpoint=AUTHZ_ENDPOINT,
            token_endpoint=TOKEN_ENDPOINT,
            registration_endpoint=REGISTRATION_ENDPOINT,
            client_id="client-abc",
            client_secret="secret-xyz",
            scope="mcp",
            access_token="at-42",
            refresh_token="rt-42",
            expires_at=time.time() + 3600,
            token_type="Bearer",
        )
        client._save(record)
        loaded = client._load(SERVER)
        assert loaded is not None
        assert loaded.client_id == "client-abc"
        assert loaded.access_token == "at-42"
        assert loaded.refresh_token == "rt-42"
        await client.aclose()

    async def test_wrong_master_secret_fails_to_decrypt(self, tmp_path: Path):
        client = _make_client(tmp_path)
        record = StoredRegistration(
            server=SERVER,
            resource_uri=RESOURCE,
            authorization_endpoint=AUTHZ_ENDPOINT,
            token_endpoint=TOKEN_ENDPOINT,
            client_id="client-abc",
            access_token="at-42",
        )
        client._save(record)
        # Construct a second client with a different master secret.
        other = OAuthClient(
            "alternative-master-secret-00",
            storage_dir=tmp_path,
            http_client=httpx.AsyncClient(),
        )
        with pytest.raises(MCPError, match="Failed to decrypt"):
            other._load(SERVER)
        await client.aclose()
        await other.aclose()

    async def test_ciphertext_has_no_plaintext_tokens(self, tmp_path: Path):
        client = _make_client(tmp_path)
        record = StoredRegistration(
            server=SERVER,
            resource_uri=RESOURCE,
            authorization_endpoint=AUTHZ_ENDPOINT,
            token_endpoint=TOKEN_ENDPOINT,
            client_id="client-abc",
            access_token="SUPER_SECRET_TOKEN_VALUE",
            refresh_token="SUPER_SECRET_REFRESH_VALUE",
        )
        client._save(record)
        on_disk = (tmp_path / f"{SERVER}.json").read_text()
        assert "SUPER_SECRET_TOKEN_VALUE" not in on_disk
        assert "SUPER_SECRET_REFRESH_VALUE" not in on_disk
        await client.aclose()


# ---------------------------------------------------------------------------
# Cached token reuse
# ---------------------------------------------------------------------------


class TestTokenReuse:
    async def test_fresh_token_is_reused(self, tmp_path: Path):
        transport = _metadata_handler()
        client = _make_client(tmp_path, transport)
        record = await client.register_client(SERVER, metadata_url=RESOURCE)
        await client.exchange_code(
            record,
            code="authz-code",
            code_verifier="ver",
            redirect_uri="http://127.0.0.1:9999/callback",
        )
        # Token is fresh — acquire_token should NOT hit the token endpoint.
        token_a = await client.acquire_token(SERVER, RESOURCE)
        token_b = await client.acquire_token(SERVER, RESOURCE)
        assert token_a == token_b
        # Only one token call total (the initial exchange).
        assert len(transport.calls) == 1  # type: ignore[attr-defined]
        await client.aclose()


# ---------------------------------------------------------------------------
# Resource URI mismatch guard
# ---------------------------------------------------------------------------


class TestResourceMismatchGuard:
    async def test_different_resource_uri_rejected(self, tmp_path: Path):
        transport = _metadata_handler()
        client = _make_client(tmp_path, transport)
        record = await client.register_client(SERVER, metadata_url=RESOURCE)
        await client.exchange_code(
            record,
            code="authz-code",
            code_verifier="ver",
            redirect_uri="http://127.0.0.1:9999/callback",
        )
        with pytest.raises(MCPError, match="resource_uri"):
            await client.acquire_token(SERVER, "https://phisher.test")
        await client.aclose()
