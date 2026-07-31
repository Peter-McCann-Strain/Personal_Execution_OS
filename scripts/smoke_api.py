"""Attach-to-a-running-server smoke checks for the API surface.

Usage:
    uv run python -m scripts.smoke_api --base-url http://127.0.0.1:8000
    uv run smoke-api --base-url http://127.0.0.1:8000 --api-key "$CHAT_API_KEY"
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import httpx

from scripts.smoke_common import SmokeCheckError, assert_status, request_json, request_text

REQUIRED_OPENAPI_PATHS = {
    "/health",
    "/health/preflight",
    "/api/chat",
    "/api/chat/stream",
    "/api/chat/context-inspect",
    "/api/calendar/events",
    "/api/calendar/free-slots",
    "/api/contacts",
    "/api/contacts/search",
    "/api/email/inbox",
    "/api/email/{message_id}",
    "/api/monitoring/actions",
    "/api/monitoring/llm-stats",
    "/api/notifications",
    "/api/notifications/unread-count",
    "/api/projects",
    "/api/projects/{project_id}",
}


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for API smoke checks."""
    parser = argparse.ArgumentParser(
        description="Verify that a running Personal Execution OS API is reachable and healthy.",
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="API base URL, for example http://127.0.0.1:8000",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional API key for authenticated chat probes.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP timeout in seconds for each smoke request.",
    )
    parser.add_argument(
        "--require-ok-health",
        action="store_true",
        help="Require /health to be fully ok instead of ok/degraded.",
    )
    parser.add_argument(
        "--chat-probe",
        default="Smoke test the deployment chat path.",
        help="Probe message for chat and context-inspect requests.",
    )
    return parser


def _parse_sse_events(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse a simple SSE body into ordered (event, data) pairs."""
    parsed: list[tuple[str, dict[str, Any]]] = []

    for chunk in body.split("\n\n"):
        if not chunk.strip():
            continue

        event_name = "message"
        data_parts: list[str] = []

        for line in chunk.splitlines():
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_parts.append(line.split(":", 1)[1].strip())

        if not data_parts:
            continue

        data_text = "\n".join(data_parts)
        if data_text == "[DONE]":
            continue

        parsed.append((event_name, json.loads(data_text)))

    return parsed


def _summary_lines(results: dict[str, dict[str, Any]]) -> list[str]:
    lines = [
        "Smoke checks passed:",
        f"- /health: {results['health']['status']}",
        f"- /health/preflight: {results['preflight']['status']}",
        f"- /openapi.json: {results['openapi']['status']}",
        f"- /docs: {results['docs']['status']}",
        f"- /redoc: {results['redoc']['status']}",
    ]
    if "chat" in results:
        lines.append(
            (
                f"- /api/chat: {results['chat']['agent']} "
                f"({results['chat']['metadata'].get('request_id')})"
            ),
        )
        lines.append(
            f"- /api/chat/stream: {results['chat_stream']['event_count']} SSE events",
        )
        lines.append(
            (
                "- /api/chat/context-inspect: "
                f"tokens={results['chat_context']['inspection']['totalTokensEstimate']}"
            ),
        )
    return lines


async def run_smoke_checks(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    """Execute smoke checks and return the parsed payloads."""
    base_url = args.base_url.rstrip("/")
    default_headers = {"Accept": "application/json"}

    async with httpx.AsyncClient(base_url=base_url, timeout=args.timeout) as client:
        health_response, health_payload = await request_json(
            client,
            method="GET",
            path="/health",
            headers=default_headers,
        )
        allowed_health = {"ok"} if args.require_ok_health else {"ok", "degraded"}
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
        assert_status(
            name="/health/preflight",
            response=preflight_response,
            payload=preflight_payload,
            allowed_http={200},
            allowed_statuses={"ok", "warn"},
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

        openapi_response, openapi_payload = await request_json(
            client,
            method="GET",
            path="/openapi.json",
            headers=default_headers,
        )
        if "openapi" not in openapi_payload or "paths" not in openapi_payload:
            raise SmokeCheckError("/openapi.json response did not include an OpenAPI schema")
        missing_paths = sorted(REQUIRED_OPENAPI_PATHS.difference(openapi_payload["paths"]))
        if missing_paths:
            raise SmokeCheckError(
                f"/openapi.json is missing required paths: {', '.join(missing_paths)}",
            )
        assert_status(
            name="/openapi.json",
            response=openapi_response,
            payload={"status": "ok"},
            allowed_http={200},
            allowed_statuses={"ok"},
        )

        docs_response, docs_body = await request_text(
            client,
            method="GET",
            path="/docs",
            headers={"Accept": "text/html"},
        )
        if docs_response.status_code != 200:
            raise SmokeCheckError(f"/docs returned HTTP {docs_response.status_code}")
        if "text/html" not in docs_response.headers.get("content-type", ""):
            raise SmokeCheckError("/docs did not return HTML")
        if "<html" not in docs_body.lower():
            raise SmokeCheckError("/docs returned an unexpected HTML payload")

        redoc_response, redoc_body = await request_text(
            client,
            method="GET",
            path="/redoc",
            headers={"Accept": "text/html"},
        )
        if redoc_response.status_code != 200:
            raise SmokeCheckError(f"/redoc returned HTTP {redoc_response.status_code}")
        if "text/html" not in redoc_response.headers.get("content-type", ""):
            raise SmokeCheckError("/redoc did not return HTML")
        if "<html" not in redoc_body.lower():
            raise SmokeCheckError("/redoc returned an unexpected HTML payload")

        results: dict[str, dict[str, Any]] = {
            "health": health_payload,
            "preflight": preflight_payload,
            "openapi": {"status": "ok", "title": openapi_payload.get("info", {}).get("title")},
            "docs": {"status": "ok"},
            "redoc": {"status": "ok"},
        }

        if args.api_key:
            chat_headers = {
                **default_headers,
                "Content-Type": "application/json",
                "X-API-Key": args.api_key,
            }
            probe_body = {"content": args.chat_probe, "source": "api"}

            chat_response, chat_payload = await request_json(
                client,
                method="POST",
                path="/api/chat",
                headers=chat_headers,
                json_body=probe_body,
            )
            if chat_response.status_code != 200:
                raise SmokeCheckError(
                    f"/api/chat returned HTTP {chat_response.status_code}: {chat_payload}",
                )
            if not isinstance(chat_payload.get("content"), str) or not chat_payload.get("content"):
                raise SmokeCheckError("/api/chat returned an empty response")

            stream_response = await client.post(
                "/api/chat/stream",
                headers=chat_headers,
                json=probe_body,
            )
            if stream_response.status_code != 200:
                raise SmokeCheckError(
                    f"/api/chat/stream returned HTTP {stream_response.status_code}",
                )
            if "text/event-stream" not in stream_response.headers.get("content-type", ""):
                raise SmokeCheckError("/api/chat/stream did not return SSE content")

            stream_events = _parse_sse_events(stream_response.text)
            event_names = [event for event, _payload in stream_events]
            if "message_start" not in event_names or "message_end" not in event_names:
                raise SmokeCheckError("/api/chat/stream did not emit the expected SSE events")
            final_payload = next(
                payload for event, payload in reversed(stream_events) if event == "message_end"
            )
            if not final_payload.get("content"):
                raise SmokeCheckError("/api/chat/stream returned an empty final payload")

            context_response, context_payload = await request_json(
                client,
                method="POST",
                path="/api/chat/context-inspect",
                headers=chat_headers,
                json_body=probe_body,
            )
            if context_response.status_code != 200:
                raise SmokeCheckError(
                    (
                        f"/api/chat/context-inspect returned HTTP "
                        f"{context_response.status_code}: {context_payload}"
                    ),
                )

            inspection = context_payload.get("inspection")
            if not isinstance(inspection, dict):
                raise SmokeCheckError("/api/chat/context-inspect missing inspection payload")
            if inspection.get("totalTokensEstimate", 0) <= 0:
                raise SmokeCheckError(
                    "/api/chat/context-inspect returned a non-positive token estimate",
                )

            results["chat"] = chat_payload
            results["chat_stream"] = {
                "status": "ok",
                "event_count": len(stream_events),
                "events": event_names,
            }
            results["chat_context"] = context_payload

    return results


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        results = asyncio.run(run_smoke_checks(args))
    except SmokeCheckError as exc:
        print(f"Smoke checks failed: {exc}")
        raise SystemExit(1) from exc

    for line in _summary_lines(results):
        print(line)


if __name__ == "__main__":
    main()
