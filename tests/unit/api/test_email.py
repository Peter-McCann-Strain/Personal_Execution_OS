"""Read-only Gmail API surface tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import Principal, get_current_principal
from src.app.api.routes.email import router


def _build_app() -> FastAPI:
    app = FastAPI()

    async def principal() -> Principal:
        return Principal(
            subject="owner",
            external_subject=None,
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
            account_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            role="owner",
            plan="community",
            scopes=("account:owner",),
            auth_method="api_key",
        )

    app.dependency_overrides[get_current_principal] = principal
    app.include_router(router, prefix="/api")
    return app


def _metadata_email(message_id: str) -> dict:
    return {
        "id": message_id,
        "threadId": "thread",
        "snippet": "A message",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Status"},
                {"name": "From", "value": "sender@example.com"},
            ]
        },
        "labelIds": ["INBOX"],
    }


async def test_inbox_search_is_read_only_and_paginated() -> None:
    service = AsyncMock()
    service.search_emails.return_value = [
        _metadata_email("one"),
        _metadata_email("two"),
    ]
    app = _build_app()

    with (
        patch("src.app.api.routes.email._check_google_configured"),
        patch("src.app.api.routes.email._make_gmail_service", return_value=service),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/email/inbox",
                params={"search": "project", "unread_only": True, "limit": 1},
            )

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "one"
    service.search_emails.assert_awaited_once_with(
        query="project is:unread",
        max_results=1,
    )
    service.close.assert_awaited_once()


async def test_email_detail_is_available() -> None:
    service = AsyncMock()
    service.get_email_detail.return_value = {
        "id": "message",
        "threadId": "thread",
        "snippet": "A message",
        "headers": {"Subject": "Status"},
        "body": "Read-only content",
    }
    app = _build_app()

    with (
        patch("src.app.api.routes.email._check_google_configured"),
        patch("src.app.api.routes.email._make_gmail_service", return_value=service),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/email/message")

    assert response.status_code == 200
    assert response.json()["body"] == "Read-only content"


async def test_google_not_configured_returns_503() -> None:
    settings = MagicMock(google_configured=False)
    app = _build_app()

    with patch("src.app.api.routes.email.get_settings", return_value=settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/email/inbox")

    assert response.status_code == 503


def test_only_get_routes_are_public() -> None:
    methods = {method for route in router.routes for method in getattr(route, "methods", set())}

    assert methods == {"GET"}
