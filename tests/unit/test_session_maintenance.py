"""Tests for nightly session maintenance worker."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.workers.session_maintenance import (
    _compact_text,
    compact_stale_artifact_payloads,
    compact_stale_interaction_transcripts,
    delete_resolved_workflow_checkpoints,
    run_session_maintenance,
)


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ExecuteResult:
    def __init__(self, *, rows=None, rowcount=None):
        self._rows = rows or []
        self.rowcount = rowcount

    def scalars(self):
        return _ScalarResult(self._rows)


def _make_session_factory(session: AsyncMock):
    @asynccontextmanager
    async def factory():
        yield session

    return factory


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.session_maintenance_enabled = True
    settings.session_maintenance_transcript_retention_days = 90
    settings.session_maintenance_artifact_compaction_days = 30
    settings.session_maintenance_checkpoint_retention_days = 30
    settings.session_maintenance_payload_char_threshold = 500
    settings.session_maintenance_transcript_preview_chars = 80
    return settings


class TestCompactText:
    def test_compact_text_preserves_preview(self):
        result = _compact_text(
            "This is a long transcript that should be compacted.", preview_chars=18
        )
        assert result.startswith("[session-maintenance-compacted]")
        assert "This is a long..." in result

    def test_compact_text_is_idempotent(self):
        original = "[session-maintenance-compacted] preserved preview"
        assert _compact_text(original, preview_chars=20) == original


@pytest.mark.asyncio
class TestCompactStaleInteractionTranscripts:
    async def test_compacts_old_transcripts(self):
        record = SimpleNamespace(
            user_message="User transcript " * 20,
            response_content="Assistant transcript " * 20,
        )
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_ExecuteResult(rows=[record]))

        count = await compact_stale_interaction_transcripts(
            session,
            before=datetime.now(UTC) - timedelta(days=90),
            preview_chars=40,
        )

        assert count == 1
        assert record.user_message.startswith("[session-maintenance-compacted]")
        assert record.response_content.startswith("[session-maintenance-compacted]")
        session.flush.assert_awaited_once()

    async def test_skips_already_compacted_transcripts(self):
        record = SimpleNamespace(
            user_message="[session-maintenance-compacted] user preview",
            response_content="[session-maintenance-compacted] assistant preview",
        )
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_ExecuteResult(rows=[record]))

        count = await compact_stale_interaction_transcripts(
            session,
            before=datetime.now(UTC) - timedelta(days=90),
            preview_chars=40,
        )

        assert count == 0
        session.flush.assert_not_awaited()


@pytest.mark.asyncio
class TestCompactStaleArtifactPayloads:
    async def test_compacts_large_response_envelope_payloads(self):
        record = SimpleNamespace(
            artifact_type="response_envelope",
            payload={
                "response_id": "resp-123",
                "workflow_status": "completed",
                "content_blocks": [
                    {"type": "field", "title": "Subject", "text": "A" * 300},
                    {
                        "type": "bullet_list",
                        "title": "Sources (2)",
                        "items": ["First source " * 20, "Second source " * 20],
                    },
                ],
                "tool_events": [{"name": "search"}, {"name": "calendar"}],
                "citations": [{"label": "FastAPI"}, {"label": "Redis"}],
                "quality": {"final_response_quality": 0.94},
            },
        )
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_ExecuteResult(rows=[record]))

        count = await compact_stale_artifact_payloads(
            session,
            before=datetime.now(UTC) - timedelta(days=30),
            payload_char_threshold=200,
            preview_chars=60,
        )

        assert count == 1
        assert record.payload["_compacted_by"] == "session_maintenance_v1"
        assert record.payload["preserved"]["response_id"] == "resp-123"
        assert record.payload["preserved"]["tool_event_count"] == 2
        assert record.payload["preserved"]["tool_names"] == ["search", "calendar"]
        assert record.payload["preserved"]["citation_labels"] == ["FastAPI", "Redis"]
        assert "content_preview" in record.payload["preserved"]
        assert "Subject:" in record.payload["preserved"]["content_preview"]
        session.flush.assert_awaited_once()

    async def test_skips_small_payloads(self):
        record = SimpleNamespace(
            artifact_type="tool_summary",
            payload={"tool_count": 1, "errors": 0},
        )
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_ExecuteResult(rows=[record]))

        count = await compact_stale_artifact_payloads(
            session,
            before=datetime.now(UTC) - timedelta(days=30),
            payload_char_threshold=500,
            preview_chars=60,
        )

        assert count == 0
        session.flush.assert_not_awaited()

    async def test_compacts_research_and_email_artifacts_preserving_structured_fields(self):
        research_record = SimpleNamespace(
            artifact_type="research_report",
            payload={
                "title": "Research: Hosted vector search options",
                "key_takeaway": "Pgvector is the strongest default for this stack.",
                "recommendation": "Use Pgvector first unless recall quality clearly fails.",
                "citations": [{"label": "Claude Code"}, {"label": "Redis"}],
                "safety_flags": ["untrusted_external_input"],
                "padding": "X" * 900,
            },
        )
        email_record = SimpleNamespace(
            artifact_type="email_triage",
            payload={
                "classification": "ACTION_REQUIRED",
                "sender": "Alice Chen",
                "subject_summary": "Deployment timeline update",
                "suggested_action": "Reply with the revised deployment timeline",
                "response_deadline": "today 5pm",
                "user_reply": "Alice needs the new deployment timeline today.",
                "safety_flags": ["untrusted_external_email"],
                "padding": "Y" * 900,
            },
        )
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_ExecuteResult(rows=[research_record, email_record])
        )

        count = await compact_stale_artifact_payloads(
            session,
            before=datetime.now(UTC) - timedelta(days=30),
            payload_char_threshold=200,
            preview_chars=60,
        )

        assert count == 2
        assert (
            research_record.payload["preserved"]["title"]
            == "Research: Hosted vector search options"
        )
        assert research_record.payload["preserved"]["recommendation"].startswith("Use Pgvector")
        assert research_record.payload["preserved"]["citation_count"] == 2
        assert email_record.payload["preserved"]["sender"] == "Alice Chen"
        assert email_record.payload["preserved"]["suggested_action"].startswith("Reply with")
        assert email_record.payload["preserved"]["response_deadline"] == "today 5pm"
        session.flush.assert_awaited_once()

    async def test_compacts_tool_summary_preserving_tool_statuses(self):
        record = SimpleNamespace(
            artifact_type="tool_summary",
            payload={
                "tool_calls": [
                    {"name": "filesystem__read_file", "status": "executed"},
                    {"name": "google-calendar__create_event", "status": "planned"},
                ],
                "tool_events": [
                    {"name": "filesystem__read_file", "status": "executed"},
                    {"name": "google-calendar__create_event", "status": "planned"},
                ],
                "tool_count": 2,
                "errors": 0,
                "padding": "Z" * 900,
            },
        )
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_ExecuteResult(rows=[record]))

        count = await compact_stale_artifact_payloads(
            session,
            before=datetime.now(UTC) - timedelta(days=30),
            payload_char_threshold=200,
            preview_chars=60,
        )

        assert count == 1
        assert record.payload["preserved"]["tool_names"] == [
            "filesystem__read_file",
            "google-calendar__create_event",
        ]
        assert record.payload["preserved"]["tool_statuses"] == ["executed", "planned"]
        session.flush.assert_awaited_once()


@pytest.mark.asyncio
class TestDeleteResolvedWorkflowCheckpoints:
    async def test_returns_deleted_row_count(self):
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_ExecuteResult(rowcount=3))

        count = await delete_resolved_workflow_checkpoints(
            session,
            before=datetime.now(UTC) - timedelta(days=30),
        )

        assert count == 3
        session.execute.assert_awaited_once()


@pytest.mark.asyncio
class TestRunSessionMaintenance:
    async def test_disabled_returns_early(self):
        settings = _make_settings()
        settings.session_maintenance_enabled = False
        session = AsyncMock()
        ctx = {
            "settings": settings,
            "session_factory": _make_session_factory(session),
        }

        result = await run_session_maintenance(ctx)

        assert result == {"status": "disabled"}
        session.commit.assert_not_awaited()

    async def test_missing_session_factory_raises(self):
        with pytest.raises(RuntimeError, match="session_maintenance_missing_session_factory"):
            await run_session_maintenance({"settings": _make_settings()})

    async def test_runs_all_maintenance_steps_and_commits(self):
        settings = _make_settings()
        session = AsyncMock()
        ctx = {
            "settings": settings,
            "session_factory": _make_session_factory(session),
        }

        with (
            patch(
                "src.app.workers.session_maintenance.compact_stale_interaction_transcripts",
                new=AsyncMock(return_value=4),
            ) as mock_transcripts,
            patch(
                "src.app.workers.session_maintenance.compact_stale_artifact_payloads",
                new=AsyncMock(return_value=2),
            ) as mock_artifacts,
            patch(
                "src.app.workers.session_maintenance.delete_resolved_workflow_checkpoints",
                new=AsyncMock(return_value=7),
            ) as mock_checkpoints,
        ):
            result = await run_session_maintenance(ctx)

        assert result == {
            "status": "completed",
            "transcripts_compacted": 4,
            "artifacts_compacted": 2,
            "checkpoints_deleted": 7,
        }
        session.commit.assert_awaited_once()
        mock_transcripts.assert_awaited_once()
        mock_artifacts.assert_awaited_once()
        mock_checkpoints.assert_awaited_once()

    async def test_rolls_back_on_failure(self):
        settings = _make_settings()
        session = AsyncMock()
        ctx = {
            "settings": settings,
            "session_factory": _make_session_factory(session),
        }

        with (
            patch(
                "src.app.workers.session_maintenance.compact_stale_interaction_transcripts",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await run_session_maintenance(ctx)

        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()
