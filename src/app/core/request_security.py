"""Exact host and origin policy for the local-first web runtime."""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.app.config import Settings

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def trusted_hosts(settings: Settings) -> frozenset[str]:
    """Return exact hostnames accepted by the API edge."""
    public_hostname = str(getattr(settings, "public_hostname", "")).strip()
    configured = {public_hostname.strip("[]").casefold()} if public_hostname else set()
    if getattr(settings, "app_env", "development") == "test":
        configured.update({"test", "testserver"})
    return frozenset(_LOCAL_HOSTS | configured)


def trusted_origins(settings: Settings) -> frozenset[str]:
    """Return exact browser origins; never derive them from request Host."""
    app_port = int(getattr(settings, "app_port", 8080))
    port_suffix = "" if app_port == 80 else f":{app_port}"
    origins = {
        f"http://localhost{port_suffix}",
        f"http://127.0.0.1{port_suffix}",
        f"http://[::1]{port_suffix}",
    }
    if getattr(settings, "app_env", "development") == "test":
        origins.add("http://test")
    configured_origins = (
        f"{getattr(settings, 'auth_trusted_origins', '')},"
        f"{getattr(settings, 'cors_allowed_origins', '')}"
    )
    origins.update(
        value.strip().rstrip("/") for value in configured_origins.split(",") if value.strip()
    )
    return frozenset(origins)


def host_from_header(raw_host: str) -> str | None:
    """Parse an HTTP Host header, including bracketed IPv6, without guessing."""
    if not raw_host or any(char in raw_host for char in "\r\n\t /\\"):
        return None
    try:
        parsed = urlsplit(f"//{raw_host}")
        if parsed.username is not None or parsed.password is not None:
            return None
        return parsed.hostname.casefold() if parsed.hostname else None
    except ValueError:
        return None


class ExactHostMiddleware:
    """Reject requests whose Host is outside the explicit local/remote allowlist."""

    def __init__(self, app: ASGIApp, *, allowed_hosts: Iterable[str]) -> None:
        self.app = app
        self.allowed_hosts = frozenset(host.casefold() for host in allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        host = host_from_header(Headers(scope=scope).get("host", ""))
        if host is None or host not in self.allowed_hosts:
            response = PlainTextResponse("Invalid host header", status_code=400)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
