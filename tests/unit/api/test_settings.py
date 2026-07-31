"""Tests for integration diagnostics endpoints."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import Principal, get_current_principal
from src.app.api.routes.settings import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        subject="owner",
        external_subject=None,
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
        account_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        role="owner",
        plan="pro",
        scopes=("admin",),
        auth_method="api_key",
    )
    app.include_router(router, prefix="/api")
    return app


async def test_test_integration_reports_google_calendar_success() -> None:
    app = _build_app()

    with (
        patch(
            "src.app.api.routes.settings.get_settings",
            return_value=SimpleNamespace(
                google_configured=True,
                tavily_configured=False,
                posthog_configured=False,
                sentry_configured=False,
                anthropic_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
                ollama_host="http://localhost:11434",
            ),
        ),
        patch(
            "src.app.api.routes.settings.probe_google_calendar",
            new=AsyncMock(),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/settings/integrations/google_calendar/test")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_test_integration_reports_posthog_success_when_bridge_is_live() -> None:
    app = _build_app()
    app.state.telemetry = SimpleNamespace(status={"posthog": True, "sentry": False})

    with patch(
        "src.app.api.routes.settings.get_settings",
        return_value=SimpleNamespace(
            google_configured=False,
            tavily_configured=False,
            posthog_configured=True,
            sentry_configured=False,
            anthropic_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
            ollama_host="http://localhost:11434",
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/settings/integrations/posthog/test")

    assert response.status_code == 200
    assert response.json()["message"] == "PostHog telemetry enabled"


async def test_test_integration_hides_telegram_customer_probe() -> None:
    app = _build_app()
    app.state.telegram_service = SimpleNamespace(
        get_webhook_status=AsyncMock(return_value={"pending_update_count": 2})
    )

    with patch(
        "src.app.api.routes.settings.get_settings",
        return_value=SimpleNamespace(
            google_configured=False,
            tavily_configured=False,
            posthog_configured=False,
            sentry_configured=False,
            anthropic_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
            ollama_host="http://localhost:11434",
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/settings/integrations/telegram/test")

    assert response.status_code == 404
    assert "internal operator channel" in response.json()["detail"]


async def test_test_integration_rejects_unknown_keys() -> None:
    app = _build_app()

    with patch(
        "src.app.api.routes.settings.get_settings",
        return_value=SimpleNamespace(
            google_configured=False,
            tavily_configured=False,
            posthog_configured=False,
            sentry_configured=False,
            anthropic_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
            ollama_host="http://localhost:11434",
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/settings/integrations/not-real/test")

    assert response.status_code == 404
