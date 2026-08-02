"""Retired standalone Google OAuth helper.

The supported public flow is Settings -> Integrations. It requests the
reviewed read-only connector scopes, binds state to the authenticated account,
and stores the resulting token through the encrypted connector vault.

The previous standalone helper requested write-capable Calendar and Gmail
scopes and printed a refresh token to the terminal. Retaining that behavior
would contradict the supported read-only boundary and make accidental token
disclosure too easy, so this command now fails closed.
"""

from __future__ import annotations


def main() -> None:
    """Explain the supported flow without opening a broad OAuth grant."""
    raise SystemExit(
        "This legacy OAuth helper is retired. Start Personal Execution OS, "
        "open Settings -> Integrations, and use the reviewed read-only Google "
        "connector flow. See docs/INTEGRATIONS.md."
    )


if __name__ == "__main__":
    main()
