"""One-time Google OAuth2 flow to get a refresh token.

Usage:
    python scripts/google_oauth.py

    Or with uv:
    uv run python scripts/google_oauth.py

Prerequisites:
    1. Create a Google Cloud project at https://console.cloud.google.com
    2. Enable the Google Calendar API and Gmail API
    3. Create OAuth 2.0 credentials (Desktop application type)
    4. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env file

What this script does:
    1. Reads GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET from .env
    2. Opens your browser for Google sign-in
    3. User grants Calendar + Gmail permissions
    4. Prints the GOOGLE_REFRESH_TOKEN to paste into .env

You only need to run this once. The refresh token does not expire unless
you revoke access or the Google Cloud project is deleted.
"""

import os
import sys
from pathlib import Path

# Scopes needed for Calendar + Gmail
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
]


def _load_env() -> dict[str, str]:
    """Load key=value pairs from .env file in project root."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    env_vars: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                # Strip surrounding quotes
                value = value.strip().strip("\"'")
                env_vars[key.strip()] = value
    return env_vars


def main() -> None:
    """Run the OAuth2 flow and print the refresh token."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: google-auth-oauthlib is not installed.")
        print("Install it with: uv pip install google-auth-oauthlib")
        sys.exit(1)

    # Load credentials from environment or .env file
    env_vars = _load_env()
    client_id = os.environ.get("GOOGLE_CLIENT_ID") or env_vars.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET") or env_vars.get(
        "GOOGLE_CLIENT_SECRET", ""
    )

    if not client_id or not client_secret:
        print("ERROR: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set.")
        print()
        print("Set them in your .env file or as environment variables:")
        print("  GOOGLE_CLIENT_ID=your-client-id-here")
        print("  GOOGLE_CLIENT_SECRET=your-client-secret-here")
        print()
        print("Get these from: https://console.cloud.google.com/apis/credentials")
        sys.exit(1)

    # Build the OAuth client config (same format as a downloaded credentials.json)
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    print("Starting Google OAuth2 flow...")
    print(f"Requesting scopes: {', '.join(SCOPES)}")
    print()

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

    # Run the local server flow — opens browser automatically
    credentials = flow.run_local_server(
        port=8090,
        prompt="consent",
        access_type="offline",
    )

    if not credentials.refresh_token:
        print("ERROR: No refresh token received.")
        print()
        print("This can happen if you previously granted access. To fix:")
        print("  1. Go to https://myaccount.google.com/permissions")
        print("  2. Remove access for your app")
        print("  3. Run this script again")
        sys.exit(1)

    print()
    print("=" * 60)
    print("  SUCCESS! Add this to your .env file:")
    print("=" * 60)
    print()
    print(f"GOOGLE_REFRESH_TOKEN={credentials.refresh_token}")
    print()
    print("=" * 60)
    print()
    print("The refresh token does not expire unless you revoke access.")
    print("You should only need to run this script once.")


if __name__ == "__main__":
    main()
