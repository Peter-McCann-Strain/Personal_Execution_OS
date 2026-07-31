"""Post-deploy smoke checks for immutable releases.

Usage:
    uv run python -m scripts.smoke_release --base-url https://assistant.example.com
    uv run python -m scripts.smoke_release \
      --base-url https://assistant.example.com \
      --api-key "$CHAT_API_KEY" \
      --check-chat-context
"""

from __future__ import annotations

import argparse
import asyncio

import httpx

from scripts.smoke_common import SmokeCheckError, assert_status, request_json


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for smoke checks."""
    parser = argparse.ArgumentParser(
        description="Verify that a deployed Personal Execution OS release is healthy.",
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Deployment base URL, for example https://assistant.example.com",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional chat API key for authenticated probe endpoints.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP timeout in seconds for each smoke request.",
    )
    parser.add_argument(
        "--allow-degraded-health",
        action="store_true",
        help="Treat /health status=degraded as acceptable.",
    )
    parser.add_argument(
        "--require-ok-preflight",
        action="store_true",
        help="Require /health/preflight to be fully ok instead of ok/warn.",
    )
    parser.add_argument(
        "--check-chat-context",
        action="store_true",
        help="Probe /api/chat/context-inspect as an authenticated runtime check.",
    )
    parser.add_argument(
        "--chat-probe",
        default="Smoke test the deployment context path.",
        help="Probe message to send to the chat context inspection endpoint.",
    )
    return parser


async def run_smoke_checks(args: argparse.Namespace) -> dict[str, dict]:
    """Execute smoke checks and return the parsed payloads."""
    base_url = args.base_url.rstrip("/")
    default_headers = {"Accept": "application/json"}

    if args.check_chat_context and not args.api_key:
        raise SmokeCheckError("--check-chat-context requires --api-key")

    async with httpx.AsyncClient(base_url=base_url, timeout=args.timeout) as client:
        health_response, health_payload = await request_json(
            client,
            method="GET",
            path="/health",
            headers=default_headers,
        )
        allowed_health = {"ok", "degraded"} if args.allow_degraded_health else {"ok"}
        assert_status(
            name="/health",
            response=health_response,
            payload=health_payload,
            allowed_http={200},
            allowed_statuses=allowed_health,
        )

        preflight_response, preflight_payload = await request_json(
            client,
            method="GET",
            path="/health/preflight",
            headers=default_headers,
        )
        allowed_preflight = {"ok"} if args.require_ok_preflight else {"ok", "warn"}
        assert_status(
            name="/health/preflight",
            response=preflight_response,
            payload=preflight_payload,
            allowed_http={200},
            allowed_statuses=allowed_preflight,
        )
        checks = preflight_payload.get("checks", [])
        if not isinstance(checks, list):
            raise SmokeCheckError("/health/preflight did not return a checks list")
        check_names = {check.get("name") for check in checks if isinstance(check, dict)}
        missing_checks = {"provider_configuration", "evaluation_assets"}.difference(check_names)
        if missing_checks:
            raise SmokeCheckError(
                "/health/preflight is missing required checks: "
                + ", ".join(sorted(missing_checks)),
            )

        results = {
            "health": health_payload,
            "preflight": preflight_payload,
        }

        if args.check_chat_context:
            chat_headers = {
                **default_headers,
                "Content-Type": "application/json",
                "X-API-Key": args.api_key,
            }
            chat_response, chat_payload = await request_json(
                client,
                method="POST",
                path="/api/chat/context-inspect",
                headers=chat_headers,
                json_body={"content": args.chat_probe, "source": "api"},
            )
            if chat_response.status_code != 200:
                raise SmokeCheckError(
                    f"/api/chat/context-inspect returned HTTP {chat_response.status_code}: "
                    f"{chat_payload}",
                )

            inspection = chat_payload.get("inspection")
            if not isinstance(inspection, dict):
                raise SmokeCheckError("chat context inspection response missing inspection payload")

            if inspection.get("totalTokensEstimate", 0) <= 0:
                raise SmokeCheckError(
                    "chat context inspection returned a non-positive token estimate",
                )

            results["chat_context"] = chat_payload

    return results


def _print_summary(results: dict[str, dict]) -> None:
    print("Smoke checks passed:")
    print(f"- /health: {results['health']['status']}")
    print(f"- /health/preflight: {results['preflight']['status']}")
    if "chat_context" in results:
        inspection = results["chat_context"]["inspection"]
        print(
            "- /api/chat/context-inspect: ok "
            f"(tokens={inspection['totalTokensEstimate']}, "
            f"sections={len(inspection.get('sections', []))})",
        )


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        results = asyncio.run(run_smoke_checks(args))
    except SmokeCheckError as exc:
        print(f"Smoke checks failed: {exc}")
        raise SystemExit(1) from exc

    _print_summary(results)


if __name__ == "__main__":
    main()
