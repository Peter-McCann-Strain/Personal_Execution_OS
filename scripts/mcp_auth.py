"""OAuth 2.1 CLI for remote MCP servers (Phase 6.0).

Three commands:

- ``login <server> <metadata_url>`` — run the full browser flow: DCR +
  PKCE + token exchange. Stores encrypted refresh token on disk.
- ``logout <server>`` — delete the stored registration.
- ``status [--server <name>]`` — list tokens and expiries. Never prints
  tokens themselves.

Usage::

    uv run python -m scripts.mcp_auth login linear https://mcp.linear.app
    uv run python -m scripts.mcp_auth status
    uv run python -m scripts.mcp_auth logout linear

The runtime code path (``OAuthClient.acquire_token``) is non-interactive;
it relies on the refresh token this CLI produces.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from src.app.agents.tools.mcp_oauth import OAuthClient
from src.app.config import get_settings
from src.app.core.exceptions import MCPError


def _get_oauth_client() -> OAuthClient:
    """Instantiate the OAuth client with the master secret from settings."""
    settings = get_settings()
    secret = settings.mcp_oauth_master_secret.get_secret_value()
    if not secret:
        print(
            "ERROR: mcp_oauth_master_secret is unset. Add MCP_OAUTH_MASTER_SECRET "
            "(>=16 chars) to your .env before using this CLI.",
            file=sys.stderr,
        )
        sys.exit(2)
    return OAuthClient(secret)


async def _cmd_login(args: argparse.Namespace) -> int:
    client = _get_oauth_client()
    try:
        record = await client.run_login_flow(
            args.server,
            args.metadata_url,
            scope=args.scope,
            resource_uri=args.resource_uri or args.metadata_url,
        )
    except MCPError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        await client.aclose()
        return 1
    finally:
        pass
    expiry = datetime.fromtimestamp(record.expires_at, tz=UTC).isoformat()
    print(f"OK — logged in to '{args.server}' as client_id={record.client_id}")
    print(f"Access token expires at: {expiry}")
    print(f"Refresh token stored   : {'yes' if record.refresh_token else 'no'}")
    await client.aclose()
    return 0


def _cmd_logout(args: argparse.Namespace) -> int:
    client = _get_oauth_client()
    removed = client.logout(args.server)
    if removed:
        print(f"OK — removed OAuth registration for '{args.server}'")
        return 0
    print(f"No stored registration for '{args.server}'", file=sys.stderr)
    return 1


def _cmd_status(args: argparse.Namespace) -> int:
    client = _get_oauth_client()
    summaries = client.list_registrations()
    if args.server:
        summaries = [s for s in summaries if s.get("server") == args.server]
    if not summaries:
        print("No MCP OAuth registrations stored.")
        return 0
    header = f"{'SERVER':<24} {'EXPIRES':<26} {'REFRESH':<8} {'CLIENT_ID'}"
    print(header)
    print("-" * len(header))
    for summary in summaries:
        expires = (
            datetime.fromtimestamp(summary["expires_at"], tz=UTC).isoformat()
            if summary.get("expires_at")
            else "—"
        )
        refresh = "yes" if summary.get("has_refresh_token") else "no"
        cid = summary.get("client_id", "")
        print(f"{summary['server']:<24} {expires:<26} {refresh:<8} {cid}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp_auth",
        description="OAuth 2.1 client for remote MCP servers (Phase 6.0).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Run the browser OAuth flow.")
    p_login.add_argument("server", help="Local name for this MCP server.")
    p_login.add_argument(
        "metadata_url",
        help="Canonical resource URL of the MCP server (e.g. https://mcp.example.com).",
    )
    p_login.add_argument("--scope", default="", help="OAuth scopes to request (optional).")
    p_login.add_argument(
        "--resource-uri",
        default="",
        help="Override resource_uri (RFC 8707). Defaults to metadata_url.",
    )

    p_logout = sub.add_parser("logout", help="Remove a stored registration.")
    p_logout.add_argument("server", help="Local name of the MCP server to forget.")

    p_status = sub.add_parser("status", help="List stored tokens + expiries.")
    p_status.add_argument("--server", default="", help="Limit status to one server.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "login":
        return asyncio.run(_cmd_login(args))
    if args.command == "logout":
        return _cmd_logout(args)
    if args.command == "status":
        return _cmd_status(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
