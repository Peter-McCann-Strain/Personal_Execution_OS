"""Tests for the release smoke-check CLI."""

from __future__ import annotations

import argparse

import httpx
import pytest

from scripts.smoke_release import SmokeCheckError, build_parser, run_smoke_checks


def _make_args(**overrides: object) -> argparse.Namespace:
    defaults = {
        "base_url": "https://assistant.example.com/",
        "api_key": None,
        "timeout": 5.0,
        "allow_degraded_health": False,
        "require_ok_preflight": False,
        "check_chat_context": False,
        "chat_probe": "Smoke test the deployment context path.",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _transport(routes: dict[tuple[str, str], httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        response = routes.get(key)
        if response is None:  # pragma: no cover - indicates a broken test setup
            raise AssertionError(f"Unexpected request: {key}")
        return response

    return httpx.MockTransport(handler)


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
async def test_run_smoke_checks_passes_for_ok_health_and_warn_preflight(monkeypatch):
    original_async_client = httpx.AsyncClient
    transport = _transport(
        {
            ("GET", "/health"): httpx.Response(200, json={"status": "ok"}),
            ("GET", "/health/preflight"): _preflight_response("warn"),
        }
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    results = await run_smoke_checks(_make_args())

    assert results["health"]["status"] == "ok"
    assert results["preflight"]["status"] == "warn"


@pytest.mark.asyncio
async def test_run_smoke_checks_rejects_degraded_health_by_default(monkeypatch):
    original_async_client = httpx.AsyncClient
    transport = _transport(
        {
            ("GET", "/health"): httpx.Response(200, json={"status": "degraded"}),
            ("GET", "/health/preflight"): _preflight_response("ok"),
        }
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    with pytest.raises(SmokeCheckError, match="status='degraded'"):
        await run_smoke_checks(_make_args())


@pytest.mark.asyncio
async def test_run_smoke_checks_accepts_degraded_health_when_requested(monkeypatch):
    original_async_client = httpx.AsyncClient
    transport = _transport(
        {
            ("GET", "/health"): httpx.Response(200, json={"status": "degraded"}),
            ("GET", "/health/preflight"): _preflight_response("ok"),
        }
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    results = await run_smoke_checks(_make_args(allow_degraded_health=True))
    assert results["health"]["status"] == "degraded"


@pytest.mark.asyncio
async def test_run_smoke_checks_can_probe_chat_context(monkeypatch):
    original_async_client = httpx.AsyncClient
    transport = _transport(
        {
            ("GET", "/health"): httpx.Response(200, json={"status": "ok"}),
            ("GET", "/health/preflight"): _preflight_response("ok"),
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
        }
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    results = await run_smoke_checks(
        _make_args(api_key="secret", check_chat_context=True),
    )

    assert results["chat_context"]["inspection"]["totalTokensEstimate"] == 64


@pytest.mark.asyncio
async def test_run_smoke_checks_requires_api_key_for_chat_probe():
    with pytest.raises(SmokeCheckError, match="requires --api-key"):
        await run_smoke_checks(_make_args(check_chat_context=True))


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
        }
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    with pytest.raises(SmokeCheckError, match="missing required checks"):
        await run_smoke_checks(_make_args())


def test_build_parser_supports_ops_flags():
    parser = build_parser()
    args = parser.parse_args(
        [
            "--base-url",
            "https://assistant.example.com",
            "--allow-degraded-health",
            "--check-chat-context",
            "--api-key",
            "secret",
        ]
    )

    assert args.base_url == "https://assistant.example.com"
    assert args.allow_degraded_health is True
    assert args.check_chat_context is True
    assert args.api_key == "secret"
