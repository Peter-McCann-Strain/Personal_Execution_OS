"""Tests for the live API smoke-check CLI."""

from __future__ import annotations

import argparse

import httpx
import pytest

from scripts.smoke_api import (
    REQUIRED_OPENAPI_PATHS,
    SmokeCheckError,
    build_parser,
    run_smoke_checks,
)


def _make_args(**overrides: object) -> argparse.Namespace:
    defaults = {
        "base_url": "https://assistant.example.com/",
        "api_key": None,
        "timeout": 5.0,
        "require_ok_health": False,
        "chat_probe": "Smoke test the deployment chat path.",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _transport(
    routes: dict[tuple[str, str], httpx.Response],
    requests: list[tuple[str, str]],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        requests.append(key)
        response = routes.get(key)
        if response is None:  # pragma: no cover - indicates a broken test setup
            raise AssertionError(f"Unexpected request: {key}")
        return response

    return httpx.MockTransport(handler)


def _openapi_schema_response(
    *,
    extra_paths: dict[str, dict] | None = None,
    include_required_paths: bool = True,
) -> httpx.Response:
    paths = {path: {} for path in REQUIRED_OPENAPI_PATHS} if include_required_paths else {}
    if extra_paths:
        paths.update(extra_paths)
    return httpx.Response(
        200,
        json={
            "openapi": "3.1.0",
            "info": {"title": "Personal Execution OS"},
            "paths": paths,
        },
    )


def _preflight_response(status: str = "ok") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": status,
            "checks": [
                {"name": "provider_configuration", "status": "ok"},
                {"name": "evaluation_assets", "status": "ok"},
            ],
        },
    )


@pytest.mark.asyncio
async def test_run_smoke_checks_probes_core_api_surface_without_chat(monkeypatch):
    requests: list[tuple[str, str]] = []
    original_async_client = httpx.AsyncClient
    transport = _transport(
        {
            ("GET", "/health"): httpx.Response(200, json={"status": "ok"}),
            ("GET", "/health/preflight"): _preflight_response("warn"),
            (
                "GET",
                "/openapi.json",
            ): _openapi_schema_response(),
            (
                "GET",
                "/docs",
            ): httpx.Response(
                200,
                text="<html><body>docs</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            (
                "GET",
                "/redoc",
            ): httpx.Response(
                200,
                text="<html><body>redoc</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        },
        requests,
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    results = await run_smoke_checks(_make_args())

    assert results["health"]["status"] == "ok"
    assert results["preflight"]["status"] == "warn"
    assert results["openapi"]["title"] == "Personal Execution OS"
    assert "chat" not in results
    assert requests == [
        ("GET", "/health"),
        ("GET", "/health/preflight"),
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("GET", "/redoc"),
    ]


@pytest.mark.asyncio
async def test_run_smoke_checks_accepts_degraded_health_by_default(monkeypatch):
    requests: list[tuple[str, str]] = []
    original_async_client = httpx.AsyncClient
    transport = _transport(
        {
            ("GET", "/health"): httpx.Response(200, json={"status": "degraded"}),
            ("GET", "/health/preflight"): _preflight_response("warn"),
            (
                "GET",
                "/openapi.json",
            ): _openapi_schema_response(),
            (
                "GET",
                "/docs",
            ): httpx.Response(
                200,
                text="<html><body>docs</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            (
                "GET",
                "/redoc",
            ): httpx.Response(
                200,
                text="<html><body>redoc</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        },
        requests,
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    results = await run_smoke_checks(_make_args())

    assert results["health"]["status"] == "degraded"


@pytest.mark.asyncio
async def test_run_smoke_checks_rejects_degraded_health_when_ok_is_required(monkeypatch):
    original_async_client = httpx.AsyncClient
    transport = _transport(
        {
            ("GET", "/health"): httpx.Response(200, json={"status": "degraded"}),
            ("GET", "/health/preflight"): _preflight_response("warn"),
            (
                "GET",
                "/openapi.json",
            ): _openapi_schema_response(),
            (
                "GET",
                "/docs",
            ): httpx.Response(
                200,
                text="<html><body>docs</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            (
                "GET",
                "/redoc",
            ): httpx.Response(
                200,
                text="<html><body>redoc</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        },
        [],
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    with pytest.raises(SmokeCheckError, match="status='degraded'"):
        await run_smoke_checks(_make_args(require_ok_health=True))


@pytest.mark.asyncio
async def test_run_smoke_checks_probes_authenticated_chat_paths(monkeypatch):
    requests: list[tuple[str, str]] = []
    original_async_client = httpx.AsyncClient
    transport = _transport(
        {
            ("GET", "/health"): httpx.Response(200, json={"status": "ok"}),
            ("GET", "/health/preflight"): _preflight_response("ok"),
            (
                "GET",
                "/openapi.json",
            ): _openapi_schema_response(),
            (
                "GET",
                "/docs",
            ): httpx.Response(
                200,
                text="<html><body>docs</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            (
                "GET",
                "/redoc",
            ): httpx.Response(
                200,
                text="<html><body>redoc</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            (
                "POST",
                "/api/chat",
            ): httpx.Response(
                200,
                json={
                    "content": "Smoke response.",
                    "agent": "chat",
                    "metadata": {"request_id": "req-123"},
                },
            ),
            (
                "POST",
                "/api/chat/stream",
            ): httpx.Response(
                200,
                text=(
                    'event: message_start\ndata: {"request_id": "req-123"}\n\n'
                    'event: message_end\ndata: {"content": "Smoke response."}\n\n'
                ),
                headers={"content-type": "text/event-stream; charset=utf-8"},
            ),
            (
                "POST",
                "/api/chat/context-inspect",
            ): httpx.Response(
                200,
                json={
                    "request_id": "req-123",
                    "inspection": {
                        "totalTokensEstimate": 64,
                        "sections": [{"name": "conversation"}],
                    },
                },
            ),
        },
        requests,
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    results = await run_smoke_checks(_make_args(api_key="secret"))

    assert results["chat"]["content"] == "Smoke response."
    assert results["chat_stream"]["event_count"] == 2
    assert results["chat_stream"]["events"] == ["message_start", "message_end"]
    assert results["chat_context"]["inspection"]["totalTokensEstimate"] == 64
    assert requests == [
        ("GET", "/health"),
        ("GET", "/health/preflight"),
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("GET", "/redoc"),
        ("POST", "/api/chat"),
        ("POST", "/api/chat/stream"),
        ("POST", "/api/chat/context-inspect"),
    ]


@pytest.mark.asyncio
async def test_run_smoke_checks_rejects_openapi_payload_without_paths(monkeypatch):
    original_async_client = httpx.AsyncClient
    transport = _transport(
        {
            ("GET", "/health"): httpx.Response(200, json={"status": "ok"}),
            ("GET", "/health/preflight"): _preflight_response("ok"),
            (
                "GET",
                "/openapi.json",
            ): httpx.Response(
                200,
                json={"openapi": "3.1.0", "info": {"title": "Personal Execution OS"}},
            ),
            (
                "GET",
                "/docs",
            ): httpx.Response(
                200,
                text="<html><body>docs</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            (
                "GET",
                "/redoc",
            ): httpx.Response(
                200,
                text="<html><body>redoc</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        },
        [],
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    with pytest.raises(SmokeCheckError, match="did not include an OpenAPI schema"):
        await run_smoke_checks(_make_args())


@pytest.mark.asyncio
async def test_run_smoke_checks_rejects_missing_required_openapi_paths(monkeypatch):
    original_async_client = httpx.AsyncClient
    transport = _transport(
        {
            ("GET", "/health"): httpx.Response(200, json={"status": "ok"}),
            ("GET", "/health/preflight"): _preflight_response("ok"),
            (
                "GET",
                "/openapi.json",
            ): _openapi_schema_response(
                extra_paths={"/health": {}, "/health/preflight": {}, "/api/chat": {}},
                include_required_paths=False,
            ),
            (
                "GET",
                "/docs",
            ): httpx.Response(
                200,
                text="<html><body>docs</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            (
                "GET",
                "/redoc",
            ): httpx.Response(
                200,
                text="<html><body>redoc</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        },
        [],
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    with pytest.raises(SmokeCheckError, match="missing required paths"):
        await run_smoke_checks(_make_args())


@pytest.mark.asyncio
async def test_run_smoke_checks_rejects_missing_required_preflight_checks(monkeypatch):
    original_async_client = httpx.AsyncClient
    transport = _transport(
        {
            ("GET", "/health"): httpx.Response(200, json={"status": "ok"}),
            (
                "GET",
                "/health/preflight",
            ): httpx.Response(
                200,
                json={"status": "ok", "checks": [{"name": "evaluation_assets", "status": "ok"}]},
            ),
            ("GET", "/openapi.json"): _openapi_schema_response(),
            (
                "GET",
                "/docs",
            ): httpx.Response(
                200,
                text="<html><body>docs</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            (
                "GET",
                "/redoc",
            ): httpx.Response(
                200,
                text="<html><body>redoc</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        },
        [],
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    with pytest.raises(SmokeCheckError, match="missing required checks"):
        await run_smoke_checks(_make_args())


def test_build_parser_supports_base_url_and_chat_key_flags():
    parser = build_parser()
    args = parser.parse_args(
        [
            "--base-url",
            "https://assistant.example.com",
            "--api-key",
            "secret",
            "--require-ok-health",
            "--timeout",
            "12.5",
        ]
    )

    assert args.base_url == "https://assistant.example.com"
    assert args.api_key == "secret"
    assert args.require_ok_health is True
    assert args.timeout == 12.5
