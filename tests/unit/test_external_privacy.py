"""External telemetry and notification privacy defaults."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from src.app.core.logging import safe_exception_processor
from src.app.core.telemetry import TelemetryBridge
from src.app.domain.services.web_push import _serialize_payload


def test_exception_processor_drops_message_and_traceback() -> None:
    sentinel = "owner@example.com token-super-secret journal sentence"
    event = safe_exception_processor(
        None,
        "error",
        {
            "event": "failed",
            "error": sentinel,
            "exception": f"Traceback: {sentinel}",
            "exc_info": RuntimeError(sentinel),
        },
    )

    assert sentinel not in repr(event)
    assert event["error_class"] == "RuntimeError"


def test_sentry_receives_sanitized_exception() -> None:
    sentinel = "owner@example.com token-super-secret journal sentence"
    bridge = TelemetryBridge()
    bridge._sentry_sdk = MagicMock()

    bridge.capture_exception(RuntimeError(sentinel))

    exported = bridge._sentry_sdk.capture_exception.call_args.args[0]
    assert sentinel not in str(exported)
    assert str(exported) == "RuntimeError"


def test_web_push_body_is_generic_without_explicit_opt_in() -> None:
    sentinel = "Private acquisition reminder"
    payload = json.loads(_serialize_payload({"title": sentinel, "body": sentinel}))

    assert sentinel not in repr(payload)
    assert payload["body"] == "Open Execution OS to view"


def test_web_push_preview_requires_explicit_opt_in() -> None:
    payload = json.loads(
        _serialize_payload(
            {"title": "Reminder", "body": "Private detail"},
            include_content_preview=True,
        )
    )

    assert payload["body"] == "Private detail"
