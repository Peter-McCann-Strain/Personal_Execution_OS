"""Tests for web push delivery helpers."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import SecretStr

from src.app.domain.services.web_push import dispatch_web_push_to_user


def _settings(*, configured: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        web_push_configured=configured,
        web_push_private_key=SecretStr("private-key"),
        web_push_subject="mailto:owner@example.com",
        web_push_public_key="public-key",
        web_push_content_preview_enabled=False,
    )


def _subscription() -> MagicMock:
    record = MagicMock()
    record.id = uuid.uuid4()
    record.endpoint = "https://updates.push.services.mozilla.com/wpush/v2/example"
    record.auth_key = "auth-key"
    record.p256dh_key = "p256dh-key"
    return record


async def test_dispatch_web_push_skips_when_not_configured() -> None:
    session = AsyncMock()

    with patch(
        "src.app.domain.services.web_push.get_settings", return_value=_settings(configured=False)
    ):
        summary = await dispatch_web_push_to_user(
            session,
            user_id="owner",
            payload={"title": "Pulse update", "body": "Ready"},
        )

    assert summary.skipped == 1
    session.commit.assert_not_awaited()


async def test_dispatch_web_push_marks_success() -> None:
    session = AsyncMock()
    subscription = _subscription()
    webpush = MagicMock()

    with (
        patch("src.app.domain.services.web_push.get_settings", return_value=_settings()),
        patch(
            "src.app.domain.services.web_push.list_web_push_subscriptions",
            new_callable=AsyncMock,
            return_value=[subscription],
        ),
        patch("src.app.domain.services.web_push._load_webpush", return_value=(webpush, Exception)),
        patch("src.app.domain.services.web_push.asyncio.to_thread", new_callable=AsyncMock),
        patch(
            "src.app.domain.services.web_push.mark_web_push_subscription_success",
            new_callable=AsyncMock,
        ) as mark_success,
    ):
        summary = await dispatch_web_push_to_user(
            session,
            user_id="owner",
            payload={"title": "Pulse update", "body": "Ready"},
        )

    assert summary.delivered == 1
    mark_success.assert_awaited_once()
    session.commit.assert_awaited_once()


async def test_dispatch_web_push_revokes_gone_subscription() -> None:
    session = AsyncMock()
    subscription = _subscription()

    class PushGoneError(Exception):
        def __init__(self) -> None:
            self.response = SimpleNamespace(status_code=410)
            super().__init__("410 Gone")

    with (
        patch("src.app.domain.services.web_push.get_settings", return_value=_settings()),
        patch(
            "src.app.domain.services.web_push.list_web_push_subscriptions",
            new_callable=AsyncMock,
            return_value=[subscription],
        ),
        patch(
            "src.app.domain.services.web_push._load_webpush",
            return_value=(MagicMock(), PushGoneError),
        ),
        patch(
            "src.app.domain.services.web_push.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=PushGoneError(),
        ),
        patch(
            "src.app.domain.services.web_push.mark_web_push_subscription_failure",
            new_callable=AsyncMock,
        ) as mark_failure,
    ):
        summary = await dispatch_web_push_to_user(
            session,
            user_id="owner",
            payload={"title": "Approval needed", "body": "Confirm the pending action."},
        )

    assert summary.failed == 1
    mark_failure.assert_awaited_once()
    assert mark_failure.await_args.kwargs["revoke"] is True
    session.commit.assert_awaited_once()
