"""Privacy invariants for analytics and structured logging."""

from __future__ import annotations

from structlog.testing import capture_logs

from src.app.core.energy_scheduler import suggest_task_timing
from src.app.core.telemetry import TelemetryBridge


def test_analytics_identity_is_anonymous_without_installation_salt() -> None:
    bridge = TelemetryBridge()
    bridge._installation_salt = ""

    assert bridge._analytics_distinct_id("raw-owner-user-id") == "anonymous"


def test_analytics_identity_is_installation_scoped_pseudonym() -> None:
    first = TelemetryBridge()
    first._installation_salt = "installation-one-secret"
    second = TelemetryBridge()
    second._installation_salt = "installation-two-secret"

    first_id = first._analytics_distinct_id("raw-owner-user-id")
    second_id = second._analytics_distinct_id("raw-owner-user-id")

    assert first_id.startswith("installation:")
    assert "raw-owner-user-id" not in first_id
    assert first_id != second_id


def test_task_title_is_not_written_to_structured_logs() -> None:
    private_title = "Private acquisition target"
    with capture_logs() as logs:
        suggest_task_timing([{"title": private_title, "tags": ["admin"]}])

    assert private_title not in repr(logs)
    assert logs[0]["task_has_title"] is True
