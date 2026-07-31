"""Shared helpers for live API smoke checks."""

from __future__ import annotations

from typing import Any

import httpx


class SmokeCheckError(RuntimeError):
    """Raised when a smoke check fails."""


async def request_json(
    client: httpx.AsyncClient,
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    json_body: dict | None = None,
) -> tuple[httpx.Response, dict[str, Any]]:
    """Issue an HTTP request and require a JSON object response."""
    response = await client.request(method, path, headers=headers, json=json_body)

    try:
        payload = response.json()
    except ValueError as exc:
        raise SmokeCheckError(
            f"{path} returned non-JSON content (status {response.status_code})",
        ) from exc

    if not isinstance(payload, dict):
        raise SmokeCheckError(f"{path} returned unexpected JSON payload: {type(payload)!r}")

    return response, payload


async def request_text(
    client: httpx.AsyncClient,
    *,
    method: str,
    path: str,
    headers: dict[str, str],
) -> tuple[httpx.Response, str]:
    """Issue an HTTP request and return the response body as text."""
    response = await client.request(method, path, headers=headers)
    return response, response.text


def assert_status(
    *,
    name: str,
    response: httpx.Response,
    payload: dict[str, Any],
    allowed_http: set[int],
    allowed_statuses: set[str],
) -> None:
    """Validate HTTP status code and top-level payload status."""
    if response.status_code not in allowed_http:
        raise SmokeCheckError(
            f"{name} returned HTTP {response.status_code}: {payload}",
        )

    status = payload.get("status")
    if status not in allowed_statuses:
        raise SmokeCheckError(
            f"{name} reported status={status!r}; expected one of {sorted(allowed_statuses)}",
        )
