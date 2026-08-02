"""OAuth 2.1 client for remote MCP servers (Phase 6.0).

Implements the MCP 2025-11-25 authorization specification for Streamable HTTP
transport. Remote MCP servers are OAuth 2.1 Resource Servers, so this module
handles:

- **Dynamic Client Registration (RFC 7591)** — no manual client setup per
  server. We discover the authorization server via RFC 8414 metadata and
  register a new client on first use.
- **PKCE (RFC 7636)** — every authorization request uses S256 proof-of-key
  so a stolen code cannot be exchanged for a token.
- **Resource Indicators (RFC 8707)** — every ``token`` request includes the
  ``resource`` parameter pinning the access token to the MCP server's
  canonical URI. Without this, a malicious server on the same authorization
  server could redeem a token intended for us ("confused deputy").
- **Refresh tokens** — opportunistically refreshed five minutes before the
  access token expires, so a call to :meth:`OAuthClient.acquire_token` never
  blocks on an expired token unless refresh itself fails.
- **Encrypted at rest** — tokens and client credentials are stored under
  ``data/mcp_oauth/<server>.json`` as AES-GCM ciphertext. The AES key is
  derived from ``settings.mcp_oauth_master_secret`` via PBKDF2-HMAC-SHA256.

The stdio-only MCP setup does not need this module; it's exclusively used by
:mod:`src.app.core.mcp_client` when a server config declares
``transport="streamable-http"``.

CLI
---
See ``scripts/mcp_auth.py`` for ``login``, ``logout``, and ``status``. The CLI
is the only code path that opens a real browser; the runtime API
(:meth:`OAuthClient.acquire_token`) is non-interactive and relies on stored
refresh tokens.

Security invariants
-------------------
- Tokens **NEVER** land on disk unencrypted.
- ``resource=`` is included on **every** token request (authorization code
  grant AND refresh token grant).
- PKCE code verifiers are single-use and held only in memory.
- The local redirect URI is always ``http://127.0.0.1:<port>/callback`` on a
  randomly chosen free port — the authorization server will reject a
  mismatching ``redirect_uri`` at the token step.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import httpx
import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from src.app.core.exceptions import MCPError

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_STORAGE_DIR = _PROJECT_ROOT / "data" / "mcp_oauth"

# PBKDF2 params for deriving the AES-GCM key. 200k iterations is the 2024
# OWASP recommendation for SHA-256; salt is stored alongside the ciphertext.
_PBKDF2_ITERATIONS = 200_000
_AES_KEY_BYTES = 32  # AES-256
_AES_NONCE_BYTES = 12  # GCM standard
_PBKDF2_SALT_BYTES = 16

# Refresh this many seconds before expiry so callers never observe a stale
# token. Five minutes matches the shortest lifetimes we see in the wild.
_REFRESH_LEAD_SECONDS = 300

# OAuth 2.1 mandates PKCE; we always use S256.
_PKCE_METHOD = "S256"

# Authorization metadata endpoint (RFC 8414). MCP 2025-11-25 also defines
# ``/.well-known/oauth-protected-resource`` on the resource server itself,
# which we consult first to discover the authorization server URL.
_AS_METADATA_PATH = "/.well-known/oauth-authorization-server"
_RS_METADATA_PATH = "/.well-known/oauth-protected-resource"

# HTTP timeout for registration/metadata/token calls.
_HTTP_TIMEOUT_SECONDS = 15.0


# ---------------------------------------------------------------------------
# Persistence record
# ---------------------------------------------------------------------------


@dataclass
class StoredRegistration:
    """Per-server OAuth state persisted under ``data/mcp_oauth/<server>.json``.

    Encrypted at rest via AES-GCM. Never serialise this to disk directly —
    always round-trip through :meth:`OAuthClient._encrypt` /
    :meth:`OAuthClient._decrypt`.
    """

    server: str
    resource_uri: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str = ""
    client_id: str = ""
    client_secret: str = ""
    # OAuth scopes granted at the last successful authorization.
    scope: str = ""
    access_token: str = ""
    refresh_token: str = ""
    # Unix epoch seconds when the access token expires.
    expires_at: float = 0.0
    token_type: str = "Bearer"

    @property
    def needs_refresh(self) -> bool:
        """Whether the stored access token is close enough to expiry to refresh."""
        if not self.access_token:
            return True
        return (self.expires_at - time.time()) <= _REFRESH_LEAD_SECONDS

    @property
    def has_token(self) -> bool:
        """Whether any access token is stored (fresh or stale)."""
        return bool(self.access_token)


# ---------------------------------------------------------------------------
# PKCE helpers (RFC 7636)
# ---------------------------------------------------------------------------


def generate_pkce_verifier() -> str:
    """Return a URL-safe random ``code_verifier`` of 64 characters.

    RFC 7636 mandates 43-128 characters of ``[A-Z] / [a-z] / [0-9] / "-" /
    "." / "_" / "~"``. We emit 64 bytes of randomness base64url-encoded
    without padding.
    """
    raw = secrets.token_urlsafe(48)  # yields ~64 chars after stripping '='
    return raw.rstrip("=")[:128]


def derive_pkce_challenge(verifier: str) -> str:
    """Return the S256 ``code_challenge`` for ``verifier``.

    ``BASE64URL(SHA256(verifier))`` with trailing ``=`` stripped per RFC 7636.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------------
# OAuthClient
# ---------------------------------------------------------------------------


@dataclass
class _AuthorizationResult:
    """In-memory result of a browser authorization flow."""

    code: str = ""
    state: str = ""
    error: str = ""


class OAuthClient:
    """OAuth 2.1 client for remote MCP servers.

    Parameters
    ----------
    master_secret:
        Secret value used to derive the AES-GCM key via PBKDF2. Must be at
        least 16 characters. Typically read from
        ``settings.mcp_oauth_master_secret``.
    storage_dir:
        Where to persist encrypted registrations. Defaults to
        ``<project_root>/data/mcp_oauth``.
    http_client:
        Optional pre-configured ``httpx.AsyncClient`` — tests inject a
        transport-mocked client; production calls pass ``None`` and let the
        client manage its own.
    """

    def __init__(
        self,
        master_secret: str,
        *,
        storage_dir: Path | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not master_secret or len(master_secret) < 16:
            raise MCPError(
                "mcp_oauth_master_secret must be at least 16 characters — "
                "set a strong value in .env before enabling remote MCP servers."
            )
        self._master_secret = master_secret.encode("utf-8")
        self._storage_dir = storage_dir or DEFAULT_STORAGE_DIR
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._http_client = http_client
        self._owns_client = http_client is None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire_token(self, server: str, resource_uri: str) -> str:
        """Return a valid access token for ``server``.

        Reuses a cached token if it is not near expiry; otherwise attempts a
        refresh. If no refresh token is stored the caller must run the CLI
        ``login`` flow first — this method never opens a browser.
        """
        async with self._lock:
            record = self._load(server)
            if record is None:
                raise MCPError(
                    f"No OAuth registration for MCP server '{server}'. "
                    f"Run: uv run python scripts/mcp_auth.py login {server}"
                )
            if record.resource_uri != resource_uri:
                logger.warning(
                    "mcp_oauth_resource_mismatch",
                    server=server,
                    stored=record.resource_uri,
                    requested=resource_uri,
                )
                raise MCPError(
                    f"Stored resource_uri for '{server}' does not match the "
                    "configured one. Re-run `mcp_auth.py login` to rebind."
                )
            if record.needs_refresh:
                if not record.refresh_token:
                    raise MCPError(
                        f"Access token for '{server}' expired and no refresh "
                        "token is available. Run `mcp_auth.py login` again."
                    )
                await self._refresh(record)
                self._save(record)
            return record.access_token

    async def register_client(
        self,
        server: str,
        metadata_url: str,
        *,
        scope: str = "",
        resource_uri: str = "",
    ) -> StoredRegistration:
        """Perform RFC 8414 discovery + RFC 7591 Dynamic Client Registration.

        Parameters
        ----------
        server:
            Stable local name used as the on-disk file stem.
        metadata_url:
            The MCP resource server's canonical URL. Treated as both the
            default ``resource_uri`` and the base for discovering the
            authorization server via
            ``/.well-known/oauth-protected-resource`` (MCP 2025-11-25) or
            ``/.well-known/oauth-authorization-server`` (RFC 8414).
        scope:
            OAuth scope requested at registration. Empty for MCP's default.
        resource_uri:
            Override the canonical resource URI (RFC 8707). Defaults to
            ``metadata_url``.
        """
        resource_uri = resource_uri or metadata_url
        client = await self._client()

        rs_metadata = await self._fetch_metadata(client, metadata_url, _RS_METADATA_PATH)
        as_url: str | None = None
        if rs_metadata and "authorization_servers" in rs_metadata:
            servers = rs_metadata["authorization_servers"]
            if isinstance(servers, list) and servers:
                as_url = str(servers[0])
        as_metadata_base = as_url or metadata_url
        as_metadata = await self._fetch_metadata(client, as_metadata_base, _AS_METADATA_PATH)
        if not as_metadata:
            raise MCPError(
                f"Could not discover OAuth metadata for '{server}' at "
                f"{as_metadata_base}{_AS_METADATA_PATH}"
            )

        authorization_endpoint = str(as_metadata.get("authorization_endpoint", ""))
        token_endpoint = str(as_metadata.get("token_endpoint", ""))
        registration_endpoint = str(as_metadata.get("registration_endpoint", ""))
        if not authorization_endpoint or not token_endpoint:
            raise MCPError(f"AS metadata for '{server}' missing authorization or token endpoint")
        if not registration_endpoint:
            raise MCPError(
                f"AS metadata for '{server}' does not support Dynamic Client "
                "Registration (no registration_endpoint). Register a client "
                "manually and store credentials via the CLI."
            )

        redirect_uri = _default_redirect_uri()
        payload = {
            "client_name": f"personal-execution-os-{server}",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_basic",
        }
        if scope:
            payload["scope"] = scope
        response = await client.post(registration_endpoint, json=payload)
        if response.status_code >= 400:
            raise MCPError(
                f"Dynamic Client Registration failed for '{server}': "
                f"{response.status_code} {response.text}"
            )
        body = response.json()
        record = StoredRegistration(
            server=server,
            resource_uri=resource_uri,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            registration_endpoint=registration_endpoint,
            client_id=str(body.get("client_id", "")),
            client_secret=str(body.get("client_secret", "")),
            scope=scope,
        )
        if not record.client_id:
            raise MCPError(f"DCR response for '{server}' missing client_id: {body}")
        self._save(record)
        logger.info(
            "mcp_oauth_client_registered",
            server=server,
            client_id=record.client_id,
            has_secret=bool(record.client_secret),
        )
        return record

    async def exchange_code(
        self,
        record: StoredRegistration,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> StoredRegistration:
        """Exchange an authorization ``code`` for access + refresh tokens.

        Always includes ``resource=<resource_uri>`` per RFC 8707.
        """
        client = await self._client()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": record.client_id,
            "code_verifier": code_verifier,
            "resource": record.resource_uri,
        }
        if record.client_secret:
            data["client_secret"] = record.client_secret
        response = await client.post(record.token_endpoint, data=data)
        if response.status_code >= 400:
            raise MCPError(
                f"Token exchange failed for '{record.server}': "
                f"{response.status_code} {response.text}"
            )
        body = response.json()
        self._apply_token_response(record, body)
        self._save(record)
        return record

    async def run_login_flow(
        self,
        server: str,
        metadata_url: str,
        *,
        scope: str = "",
        resource_uri: str = "",
        open_browser: bool = True,
        loopback_port: int | None = None,
    ) -> StoredRegistration:
        """Full interactive login: DCR (if needed), PKCE, browser, token exchange.

        Never call this from runtime request handling — it blocks on a
        browser redirect. Use :meth:`acquire_token` instead, which relies on
        the refresh token this call produces.
        """
        resource_uri = resource_uri or metadata_url
        record = self._load(server)
        if record is None or not record.client_id:
            record = await self.register_client(
                server, metadata_url, scope=scope, resource_uri=resource_uri
            )

        verifier = generate_pkce_verifier()
        challenge = derive_pkce_challenge(verifier)
        state = secrets.token_urlsafe(24)

        port = loopback_port or _find_free_port()
        redirect_uri = f"http://127.0.0.1:{port}/callback"

        authorize_url = _build_authorize_url(
            record.authorization_endpoint,
            client_id=record.client_id,
            redirect_uri=redirect_uri,
            scope=record.scope or scope,
            state=state,
            code_challenge=challenge,
            resource_uri=record.resource_uri,
        )

        if open_browser:
            webbrowser.open(authorize_url)

        result = await asyncio.to_thread(_await_callback, port, state)
        if result.error:
            raise MCPError(f"OAuth callback returned error for '{server}': {result.error}")
        if not result.code:
            raise MCPError(f"OAuth callback for '{server}' received no code")

        await self.exchange_code(
            record, code=result.code, code_verifier=verifier, redirect_uri=redirect_uri
        )
        return record

    def logout(self, server: str) -> bool:
        """Delete the stored registration for ``server``.

        Returns ``True`` if a file was removed. Does not revoke the token
        with the authorization server — that requires a separate call on the
        revocation endpoint (out of scope for this first pass).
        """
        path = self._path(server)
        if path.exists():
            path.unlink()
            logger.info("mcp_oauth_logout", server=server)
            return True
        return False

    def list_registrations(self) -> list[dict[str, Any]]:
        """Return a safe summary (no tokens) of every stored registration."""
        summaries: list[dict[str, Any]] = []
        for path in sorted(self._storage_dir.glob("*.json")):
            server = path.stem
            try:
                record = self._load(server)
            except MCPError:
                summaries.append({"server": server, "status": "decrypt_error"})
                continue
            if record is None:
                continue
            summaries.append(
                {
                    "server": server,
                    "resource_uri": record.resource_uri,
                    "client_id": record.client_id,
                    "has_refresh_token": bool(record.refresh_token),
                    "expires_at": record.expires_at,
                    "needs_refresh": record.needs_refresh,
                }
            )
        return summaries

    async def aclose(self) -> None:
        """Close the owned httpx client (if any)."""
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _refresh(self, record: StoredRegistration) -> None:
        """Perform an RFC 6749 refresh-token grant with RFC 8707 resource indicator."""
        client = await self._client()
        data = {
            "grant_type": "refresh_token",
            "refresh_token": record.refresh_token,
            "client_id": record.client_id,
            "resource": record.resource_uri,
        }
        if record.client_secret:
            data["client_secret"] = record.client_secret
        if record.scope:
            data["scope"] = record.scope
        response = await client.post(record.token_endpoint, data=data)
        if response.status_code >= 400:
            raise MCPError(
                f"Token refresh failed for '{record.server}': "
                f"{response.status_code} {response.text}"
            )
        body = response.json()
        self._apply_token_response(record, body)

    def _apply_token_response(self, record: StoredRegistration, body: dict[str, Any]) -> None:
        """Update ``record`` from a token endpoint response body."""
        record.access_token = str(body.get("access_token", ""))
        # Refresh token MAY be rotated per RFC 6749 §6; keep the old one if
        # the server elects not to rotate.
        new_refresh = body.get("refresh_token")
        if isinstance(new_refresh, str) and new_refresh:
            record.refresh_token = new_refresh
        record.token_type = str(body.get("token_type") or record.token_type)
        expires_in = body.get("expires_in")
        if isinstance(expires_in, (int, float)):
            record.expires_at = time.time() + float(expires_in)
        else:
            # Conservative default — one hour.
            record.expires_at = time.time() + 3600.0
        if "scope" in body and isinstance(body["scope"], str):
            record.scope = body["scope"]

    async def _fetch_metadata(
        self,
        client: httpx.AsyncClient,
        base: str,
        suffix: str,
    ) -> dict[str, Any] | None:
        """Fetch JSON metadata from ``base + suffix``. Returns None on 404/non-JSON."""
        url = base.rstrip("/") + suffix
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            logger.info(
                "mcp_oauth_metadata_unreachable",
                url_length=len(url),
                error_class=type(exc).__name__,
            )
            return None
        if response.status_code != 200:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    async def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS)
        return self._http_client

    # ---- Persistence ------------------------------------------------

    def _path(self, server: str) -> Path:
        return self._storage_dir / f"{server}.json"

    def _load(self, server: str) -> StoredRegistration | None:
        path = self._path(server)
        if not path.exists():
            return None
        raw = path.read_bytes()
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise MCPError(f"Corrupt OAuth state for '{server}': {exc}") from exc
        plaintext = self._decrypt(envelope)
        payload = json.loads(plaintext.decode("utf-8"))
        return StoredRegistration(**payload)

    def _save(self, record: StoredRegistration) -> None:
        path = self._path(record.server)
        plaintext = json.dumps(asdict(record)).encode("utf-8")
        envelope = self._encrypt(plaintext)
        # Write atomically + restrict permissions — token material must never
        # end up world-readable.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(envelope))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    # ---- Crypto -----------------------------------------------------

    def _derive_key(self, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=_AES_KEY_BYTES,
            salt=salt,
            iterations=_PBKDF2_ITERATIONS,
        )
        return kdf.derive(self._master_secret)

    def _encrypt(self, plaintext: bytes) -> dict[str, str]:
        salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
        nonce = secrets.token_bytes(_AES_NONCE_BYTES)
        key = self._derive_key(salt)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
        return {
            "v": "aes-gcm-pbkdf2-v1",
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ct": base64.b64encode(ciphertext).decode("ascii"),
        }

    def _decrypt(self, envelope: dict[str, Any]) -> bytes:
        try:
            salt = base64.b64decode(envelope["salt"])
            nonce = base64.b64decode(envelope["nonce"])
            ciphertext = base64.b64decode(envelope["ct"])
        except (KeyError, ValueError) as exc:
            raise MCPError(f"Invalid OAuth envelope: {exc}") from exc
        key = self._derive_key(salt)
        try:
            return AESGCM(key).decrypt(nonce, ciphertext, associated_data=None)
        except Exception as exc:  # InvalidTag, etc.
            raise MCPError(
                "Failed to decrypt OAuth state — wrong mcp_oauth_master_secret?"
            ) from exc


# ---------------------------------------------------------------------------
# Free-function helpers
# ---------------------------------------------------------------------------


def _default_redirect_uri() -> str:
    return "http://127.0.0.1:0/callback"  # replaced in run_login_flow


def _build_authorize_url(
    authorization_endpoint: str,
    *,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
    code_challenge: str,
    resource_uri: str,
) -> str:
    """Compose the full authorization URL with PKCE + resource indicator."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": _PKCE_METHOD,
        "resource": resource_uri,
    }
    if scope:
        params["scope"] = scope
    qs = urllib.parse.urlencode(params)
    separator = "&" if "?" in authorization_endpoint else "?"
    return f"{authorization_endpoint}{separator}{qs}"


def _find_free_port() -> int:
    """Pick an ephemeral port for the loopback redirect server."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _await_callback(port: int, expected_state: str) -> _AuthorizationResult:
    """Run a single-request loopback server to capture the OAuth redirect."""
    result = _AuthorizationResult()

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if "error" in query:
                result.error = query["error"][0]
            else:
                state_values = query.get("state", [""])
                if state_values[0] != expected_state:
                    result.error = "state_mismatch"
                else:
                    result.code = query.get("code", [""])[0]
                    result.state = state_values[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Authorization received. You can close this tab.")

        def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover
            del format, args
            return

    server = HTTPServer(("127.0.0.1", port), _Handler)
    thread = Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=300.0)
    server.server_close()
    return result
