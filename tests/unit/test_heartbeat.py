"""Tests for heartbeat daemon — including relationship decay, deadlines, overdue, healthcheck."""

import uuid
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.specialists.notification import FatigueManager
from src.app.workers.heartbeat import (
    _generate_nudge,
    _get_interaction_context,
    check_decisions_due_review,
    check_habit_streaks,
    check_overdue_commitments,
    check_relationship_decay,
    check_stale_goals,
    check_upcoming_deadlines,
    ping_healthcheck,
    run_heartbeat,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session(query_results: list[dict] | None = None):
    """Create a mock AsyncSession returning fake query data."""
    rows = query_results or []

    mock_result = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = rows
    mock_result.mappings.return_value = mock_mappings

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _mock_session_factory(session=None):
    """Wrap a mock session in a factory that supports async with."""
    if session is None:
        session = _mock_session()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = cm
    return factory


# ---------------------------------------------------------------------------
# run_heartbeat
# ---------------------------------------------------------------------------


class TestRunHeartbeat:
    async def test_no_session_factory_returns_early(self):
        with patch("src.app.workers.heartbeat.logger") as mock_logger:
            await run_heartbeat({})
            mock_logger.error.assert_called_once_with("heartbeat_no_session_factory")

    async def test_runs_all_checks(self):
        session = _mock_session()
        factory = _mock_session_factory(session)
        ctx = {
            "session_factory": factory,
            "settings": SimpleNamespace(llm_configured=True),
        }

        with (
            patch(
                "src.app.workers.heartbeat.check_stale_goals", new_callable=AsyncMock
            ) as mock_stale,
            patch(
                "src.app.workers.heartbeat.check_upcoming_deadlines", new_callable=AsyncMock
            ) as mock_upcoming,
            patch(
                "src.app.workers.heartbeat.check_overdue_commitments", new_callable=AsyncMock
            ) as mock_overdue,
            patch(
                "src.app.workers.heartbeat.check_relationship_decay", new_callable=AsyncMock
            ) as mock_decay,
            patch("src.app.workers.heartbeat.ping_healthcheck", new_callable=AsyncMock),
        ):
            await run_heartbeat(ctx)

        mock_stale.assert_called_once_with(session)
        mock_upcoming.assert_called_once_with(session)
        mock_overdue.assert_called_once_with(session)
        mock_decay.assert_called_once_with(session)

    async def test_check_failure_does_not_block_others(self):
        """If one check raises, the others should still run."""
        session = _mock_session()
        factory = _mock_session_factory(session)
        ctx = {
            "session_factory": factory,
            "settings": SimpleNamespace(llm_configured=True),
        }

        with (
            patch(
                "src.app.workers.heartbeat.check_stale_goals",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch(
                "src.app.workers.heartbeat.check_upcoming_deadlines", new_callable=AsyncMock
            ) as mock_upcoming,
            patch(
                "src.app.workers.heartbeat.check_overdue_commitments", new_callable=AsyncMock
            ) as mock_overdue,
            patch(
                "src.app.workers.heartbeat.check_relationship_decay", new_callable=AsyncMock
            ) as mock_decay,
            patch("src.app.workers.heartbeat.ping_healthcheck", new_callable=AsyncMock),
        ):
            await run_heartbeat(ctx)

        # Despite stale_goals failing, others ran
        mock_upcoming.assert_called_once()
        mock_overdue.assert_called_once()
        mock_decay.assert_called_once()


# ---------------------------------------------------------------------------
# check_relationship_decay
# ---------------------------------------------------------------------------


class TestCheckRelationshipDecay:
    async def test_no_decayed_contacts(self):
        session = _mock_session(query_results=[])
        await check_relationship_decay(session)
        # No errors, just logs

    async def test_generates_notifications_for_decayed_contacts(self):
        now = datetime.now(tz=UTC)
        decayed = [
            {
                "id": uuid.uuid4(),
                "first_name": "Alice",
                "last_name": "Smith",
                "interaction_frequency_days": 14,
                "last_interaction_at": now - timedelta(days=21),
                "relationship_score": 45.0,
                "how_we_met": None,
                "tags": None,
            },
            {
                "id": uuid.uuid4(),
                "first_name": "Bob",
                "last_name": None,
                "interaction_frequency_days": 7,
                "last_interaction_at": now - timedelta(days=10),
                "relationship_score": 60.0,
                "how_we_met": None,
                "tags": None,
            },
        ]

        # First call: decayed contacts; second + third: empty interaction context
        session = _mock_session_multi([decayed, [], []])
        mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))

        with (
            patch("src.app.workers.heartbeat.get_fatigue_manager", return_value=mgr),
            patch(
                "src.app.workers.heartbeat._generate_nudge",
                new_callable=AsyncMock,
                side_effect=[
                    "Alice Smith has been out of touch for 21 days.",
                    "Bob has been out of touch for 10 days.",
                ],
            ),
        ):
            await check_relationship_decay(session)

        # Both contacts should have been queued as P2 notifications
        assert mgr.pending_count == 2

    async def test_notification_message_format(self):
        now = datetime.now(tz=UTC)
        decayed = [
            {
                "id": str(uuid.uuid4()),
                "first_name": "Charlie",
                "last_name": "Brown",
                "interaction_frequency_days": 30,
                "last_interaction_at": now - timedelta(days=45),
                "relationship_score": 30.0,
                "how_we_met": None,
                "tags": None,
            },
        ]

        # First call: decayed contacts; second: empty interaction context
        session = _mock_session_multi([decayed, []])
        mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))

        with (
            patch("src.app.workers.heartbeat.get_fatigue_manager", return_value=mgr),
            patch(
                "src.app.workers.heartbeat._generate_nudge",
                new_callable=AsyncMock,
                return_value="Charlie Brown has been out of touch for 45 days (expected every 30 days).",
            ),
        ):
            await check_relationship_decay(session)

        # Verify the queued notification message content
        assert mgr.pending_count == 1
        pending = mgr._pending_p2
        assert len(pending) == 1
        assert "Charlie Brown" in pending[0].message
        assert "45 days" in pending[0].message
        assert "every 30 days" in pending[0].message
        assert pending[0].category == "relationship"

    async def test_handles_contact_with_no_last_name(self):
        now = datetime.now(tz=UTC)
        decayed = [
            {
                "id": uuid.uuid4(),
                "first_name": "Cher",
                "last_name": None,
                "interaction_frequency_days": 7,
                "last_interaction_at": now - timedelta(days=14),
                "relationship_score": 55.0,
                "how_we_met": None,
                "tags": None,
            },
        ]

        # First call: decayed contacts; second: empty interaction context
        session = _mock_session_multi([decayed, []])
        mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))

        with (
            patch("src.app.workers.heartbeat.get_fatigue_manager", return_value=mgr),
            patch(
                "src.app.workers.heartbeat._generate_nudge",
                new_callable=AsyncMock,
                return_value="Cher has been out of touch for 14 days (expected every 7 days).",
            ),
        ):
            await check_relationship_decay(session)

        pending = mgr._pending_p2
        assert "Cher" in pending[0].message
        assert "  " not in pending[0].message

    async def test_rejects_malformed_contact_data_before_calling_model(self):
        now = datetime.now(tz=UTC)
        decayed = [
            {
                "id": uuid.uuid4(),
                "first_name": "Alice",
                "last_name": None,
                "interaction_frequency_days": 7,
                "last_interaction_at": now - timedelta(days=14),
                "how_we_met": None,
                "tags": ["friend", 42],
            }
        ]
        session = _mock_session_multi([decayed])
        generate_nudge = AsyncMock()

        with (
            patch("src.app.workers.heartbeat._generate_nudge", generate_nudge),
            pytest.raises(TypeError, match=r"contact\.tags\[1\] must be a string"),
        ):
            await check_relationship_decay(session)

        generate_nudge.assert_not_awaited()


# ---------------------------------------------------------------------------
# check_stale_goals (sanity check existing behaviour)
# ---------------------------------------------------------------------------


class TestCheckStaleGoals:
    async def test_logs_stale_goals(self):
        stale = [
            {
                "id": uuid.uuid4(),
                "title": "Learn Rust",
                "status": "active",
                "progress": 0.3,
                "updated_at": "2026-02-15",
            },
        ]
        session = _mock_session(query_results=stale)

        with patch("src.app.workers.heartbeat.logger") as mock_logger:
            await check_stale_goals(session)
            mock_logger.warning.assert_called_once()
            mock_logger.info.assert_any_call("stale_goals_check_complete", stale_count=1)


# ---------------------------------------------------------------------------
# check_upcoming_deadlines
# ---------------------------------------------------------------------------


def _mock_session_multi(results_list: list[list[dict]]):
    """Create a mock AsyncSession returning different results for sequential execute() calls."""
    execute_results = []
    for rows in results_list:
        mock_result = MagicMock()
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = rows
        mock_result.mappings.return_value = mock_mappings
        execute_results.append(mock_result)

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_results)
    return session


class TestCheckUpcomingDeadlines:
    async def test_no_upcoming_deadlines(self):
        """When no commitments or projects are due, logs zero counts."""
        session = _mock_session_multi([[], []])

        with patch("src.app.workers.heartbeat.logger") as mock_logger:
            await check_upcoming_deadlines(session)
            mock_logger.info.assert_any_call(
                "upcoming_deadlines_check_complete",
                commitment_count=0,
                project_count=0,
            )

    async def test_upcoming_commitments_logged(self):
        """Upcoming commitments within 48h should be logged."""
        now = datetime.now(tz=UTC)
        commitments = [
            {
                "id": "uuid-c1",
                "verbatim_text": "Submit report",
                "normalized_action": "submit report",
                "temporal_normalized": now + timedelta(hours=24),
                "status": "confirmed",
            },
        ]
        session = _mock_session_multi([commitments, []])

        with patch("src.app.workers.heartbeat.logger") as mock_logger:
            await check_upcoming_deadlines(session)
            mock_logger.warning.assert_called_once()
            mock_logger.info.assert_any_call(
                "upcoming_deadlines_check_complete",
                commitment_count=1,
                project_count=0,
            )

    async def test_upcoming_projects_logged(self):
        """Upcoming project deadlines within 48h should be logged."""
        now = datetime.now(tz=UTC)
        projects = [
            {
                "id": "uuid-p1",
                "title": "Launch MVP",
                "deadline": now + timedelta(hours=12),
                "status": "active",
            },
        ]
        session = _mock_session_multi([[], projects])

        with patch("src.app.workers.heartbeat.logger") as mock_logger:
            await check_upcoming_deadlines(session)
            mock_logger.warning.assert_called_once()
            mock_logger.info.assert_any_call(
                "upcoming_deadlines_check_complete",
                commitment_count=0,
                project_count=1,
            )

    async def test_both_commitments_and_projects(self):
        """Both commitments and projects within 48h should be logged."""
        now = datetime.now(tz=UTC)
        commitments = [
            {
                "id": "uuid-c1",
                "verbatim_text": "Call client",
                "normalized_action": "call client",
                "temporal_normalized": now + timedelta(hours=6),
                "status": "in_progress",
            },
        ]
        projects = [
            {
                "id": "uuid-p1",
                "title": "Deploy v2",
                "deadline": now + timedelta(hours=36),
                "status": "active",
            },
        ]
        session = _mock_session_multi([commitments, projects])

        with patch("src.app.workers.heartbeat.logger") as mock_logger:
            await check_upcoming_deadlines(session)
            assert mock_logger.warning.call_count == 2
            mock_logger.info.assert_any_call(
                "upcoming_deadlines_check_complete",
                commitment_count=1,
                project_count=1,
            )


# ---------------------------------------------------------------------------
# check_overdue_commitments
# ---------------------------------------------------------------------------


class TestCheckOverdueCommitments:
    async def test_no_overdue_commitments(self):
        """When nothing is overdue, logs zero count."""
        session = _mock_session(query_results=[])

        with patch("src.app.workers.heartbeat.logger") as mock_logger:
            await check_overdue_commitments(session)
            mock_logger.info.assert_any_call("overdue_commitments_check_complete", overdue_count=0)

    async def test_overdue_commitments_logged(self):
        """Overdue commitments should be logged as warnings."""
        now = datetime.now(tz=UTC)
        overdue = [
            {
                "id": "uuid-o1",
                "verbatim_text": "Submit taxes",
                "normalized_action": "submit taxes",
                "temporal_normalized": now - timedelta(days=3),
                "status": "confirmed",
                "created_at": now - timedelta(days=10),
            },
            {
                "id": "uuid-o2",
                "verbatim_text": "Reply to email",
                "normalized_action": "reply to email",
                "temporal_normalized": now - timedelta(hours=6),
                "status": "detected",
                "created_at": now - timedelta(days=1),
            },
        ]
        session = _mock_session(query_results=overdue)

        with patch("src.app.workers.heartbeat.logger") as mock_logger:
            await check_overdue_commitments(session)
            assert mock_logger.warning.call_count == 2
            mock_logger.info.assert_any_call("overdue_commitments_check_complete", overdue_count=2)

    async def test_overdue_commitment_log_excludes_user_content(self):
        """Operational warning identifies the row without logging its action text."""
        now = datetime.now(tz=UTC)
        due_date = now - timedelta(days=2)
        overdue = [
            {
                "id": "uuid-o1",
                "verbatim_text": "Pay rent",
                "normalized_action": "pay rent",
                "temporal_normalized": due_date,
                "status": "in_progress",
                "created_at": now - timedelta(days=5),
            },
        ]
        session = _mock_session(query_results=overdue)

        with patch("src.app.workers.heartbeat.logger") as mock_logger:
            await check_overdue_commitments(session)
            mock_logger.warning.assert_called_once_with(
                "overdue_commitment",
                commitment_id="uuid-o1",
                was_due=str(due_date),
                status="in_progress",
            )


# ---------------------------------------------------------------------------
# ping_healthcheck
# ---------------------------------------------------------------------------


class TestPingHealthcheck:
    async def test_no_url_configured(self):
        """When no healthcheck URL is set, should return silently."""
        settings = MagicMock(spec=[])
        await ping_healthcheck(settings)
        # No error — just returns

    async def test_empty_url_returns_silently(self):
        """When healthcheck URL is empty, should return silently."""
        settings = MagicMock()
        settings.healthchecks_heartbeat_url = ""
        await ping_healthcheck(settings)

    async def test_successful_ping(self):
        """Should ping the healthcheck URL and log success."""
        settings = MagicMock()
        settings.healthchecks_heartbeat_url = "https://hc-ping.com/test-uuid"

        mock_response = AsyncMock()

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("src.app.workers.heartbeat.logger") as mock_logger,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await ping_healthcheck(settings)

        mock_client.get.assert_awaited_once_with("https://hc-ping.com/test-uuid", timeout=5.0)
        mock_logger.info.assert_called_with("healthcheck_pinged")

    async def test_ping_failure_logs_warning(self):
        """HTTP errors should be caught and logged as warnings."""
        import httpx

        settings = MagicMock()
        settings.healthchecks_heartbeat_url = "https://hc-ping.com/test-uuid"

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("src.app.workers.heartbeat.logger") as mock_logger,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.HTTPError("connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await ping_healthcheck(settings)

        mock_logger.warning.assert_called_with("healthcheck_ping_failed")


# ---------------------------------------------------------------------------
# run_heartbeat — ping_healthcheck integration
# ---------------------------------------------------------------------------


class TestRunHeartbeatHealthcheck:
    async def test_pings_healthcheck_when_settings_present(self):
        """run_heartbeat should call ping_healthcheck when settings are in ctx."""
        session = _mock_session()
        factory = _mock_session_factory(session)
        settings = MagicMock()
        ctx = {"session_factory": factory, "settings": settings}

        with (
            patch("src.app.workers.heartbeat.check_stale_goals", new_callable=AsyncMock),
            patch("src.app.workers.heartbeat.check_upcoming_deadlines", new_callable=AsyncMock),
            patch("src.app.workers.heartbeat.check_overdue_commitments", new_callable=AsyncMock),
            patch("src.app.workers.heartbeat.check_relationship_decay", new_callable=AsyncMock),
            patch("src.app.workers.heartbeat.check_decisions_due_review", new_callable=AsyncMock),
            patch("src.app.workers.heartbeat.check_habit_streaks", new_callable=AsyncMock),
            patch(
                "src.app.workers.heartbeat.ping_healthcheck", new_callable=AsyncMock
            ) as mock_ping,
        ):
            await run_heartbeat(ctx)

        mock_ping.assert_awaited_once_with(settings)


# ---------------------------------------------------------------------------
# _get_interaction_context
# ---------------------------------------------------------------------------


class TestGetInteractionContext:
    async def test_returns_empty_string_when_no_interactions(self):
        """No interaction rows should return empty string."""
        session = _mock_session(query_results=[])
        result = await _get_interaction_context(session, uuid.uuid4())
        assert result == ""

    async def test_formats_interaction_rows(self):
        """Should format interaction rows with date, summary and topics."""
        interactions = [
            {
                "summary": "Discussed AI project",
                "topics": ["AI", "LLMs"],
                "interaction_at": datetime(2026, 3, 10, 14, 0, tzinfo=UTC),
            },
            {
                "summary": "Coffee catch-up",
                "topics": None,
                "interaction_at": datetime(2026, 3, 5, 10, 0, tzinfo=UTC),
            },
        ]
        session = _mock_session(query_results=interactions)
        result = await _get_interaction_context(session, uuid.uuid4())

        assert "Discussed AI project" in result
        assert "AI, LLMs" in result
        assert "Coffee catch-up" in result
        assert "2026-03-10" in result
        assert "2026-03-05" in result

    async def test_handles_no_summary(self):
        """Interaction with no summary should show 'no summary'."""
        interactions = [
            {
                "summary": None,
                "topics": None,
                "interaction_at": datetime(2026, 3, 1, tzinfo=UTC),
            },
        ]
        session = _mock_session(query_results=interactions)
        result = await _get_interaction_context(session, uuid.uuid4())

        assert "no summary" in result

    async def test_handles_no_interaction_at(self):
        """Interaction with no date should show '?'."""
        interactions = [
            {
                "summary": "Quick chat",
                "topics": None,
                "interaction_at": None,
            },
        ]
        session = _mock_session(query_results=interactions)
        result = await _get_interaction_context(session, uuid.uuid4())

        assert "?" in result
        assert "Quick chat" in result

    async def test_topics_as_empty_list(self):
        """Empty topics list should not add bracket suffix."""
        interactions = [
            {
                "summary": "Chat",
                "topics": [],
                "interaction_at": datetime(2026, 3, 8, tzinfo=UTC),
            },
        ]
        session = _mock_session(query_results=interactions)
        result = await _get_interaction_context(session, uuid.uuid4())

        assert "Chat" in result
        # No brackets because topics is empty
        assert "[" not in result

    async def test_rejects_non_string_interaction_topics(self):
        session = _mock_session(
            query_results=[
                {
                    "summary": "Chat",
                    "topics": ["planning", 7],
                    "interaction_at": datetime(2026, 3, 8, tzinfo=UTC),
                }
            ]
        )

        with pytest.raises(TypeError, match=r"interaction\.topics\[1\] must be a string"):
            await _get_interaction_context(session, uuid.uuid4())


# ---------------------------------------------------------------------------
# _generate_nudge
# ---------------------------------------------------------------------------


class TestGenerateNudge:
    async def test_llm_error_propagates(self):
        """When LLM call fails, the error should propagate."""
        with (
            patch("src.app.config.get_settings") as mock_settings,
            patch(
                "src.app.core.llm_helpers.call_and_extract_text",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM down"),
            ),
        ):
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.anthropic_api_key.get_secret_value.return_value = "sk-test"
            mock_settings.return_value.classifier_model = "claude-3-haiku"

            with pytest.raises(RuntimeError, match="LLM down"):
                await _generate_nudge(
                    full_name="Bob Jones",
                    days_since=15,
                    days_overdue=8,
                    frequency=7,
                    how_we_met="Conference",
                    tags=["friend", "tech"],
                    interaction_context="  2026-03-01: Discussed project",
                )

    async def test_successful_llm_nudge(self):
        """When LLM succeeds, should return the generated message."""
        with (
            patch("src.app.config.get_settings") as mock_settings,
            patch(
                "src.app.core.llm_helpers.call_and_extract_text",
                new_callable=AsyncMock,
                return_value="  Time to reach out to Alice! Maybe grab coffee.  ",
            ),
            patch("anthropic.AsyncAnthropic"),
        ):
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.anthropic_api_key.get_secret_value.return_value = "sk-test"
            mock_settings.return_value.classifier_model = "claude-3-haiku"

            result = await _generate_nudge(
                full_name="Alice",
                days_since=20,
                days_overdue=6,
                frequency=14,
                how_we_met="Work",
                tags=["colleague"],
                interaction_context="  2026-03-01: Had lunch",
            )

        assert result == "Time to reach out to Alice! Maybe grab coffee."

    async def test_nudge_includes_how_we_met_and_tags(self):
        """When how_we_met and tags are provided, they should be in the prompt context."""
        captured_messages = []

        async def _capture_call(
            client, *, model, max_tokens, system, messages, error_context, inject_personality
        ):
            captured_messages.append(messages)
            return "Nudge with context"

        with (
            patch("src.app.config.get_settings") as mock_settings,
            patch(
                "src.app.core.llm_helpers.call_and_extract_text",
                new_callable=AsyncMock,
                side_effect=_capture_call,
            ),
            patch("anthropic.AsyncAnthropic"),
        ):
            mock_settings.return_value = MagicMock()
            mock_settings.return_value.anthropic_api_key.get_secret_value.return_value = "sk-test"
            mock_settings.return_value.classifier_model = "claude-3-haiku"

            result = await _generate_nudge(
                full_name="Carol",
                days_since=30,
                days_overdue=16,
                frequency=14,
                how_we_met="University",
                tags=["friend", "study-buddy"],
                interaction_context="  2026-02-14: Valentine hangout",
            )

        assert result == "Nudge with context"
        # Verify the context included how_we_met and tags
        msg_content = captured_messages[0][0]["content"]
        assert "University" in msg_content
        assert "friend, study-buddy" in msg_content
        assert "Valentine hangout" in msg_content


# ---------------------------------------------------------------------------
# check_decisions_due_review
# ---------------------------------------------------------------------------


class TestCheckDecisionsDueReview:
    async def test_no_decisions_due(self):
        """When no decisions are due for review, logs zero count."""
        session = _mock_session(query_results=[])

        with patch("src.app.workers.heartbeat.logger") as mock_logger:
            await check_decisions_due_review(session)
            mock_logger.info.assert_any_call("decisions_due_review_check_complete", due_count=0)

    async def test_generates_notifications_for_due_decisions(self):
        """Decisions past review_date should produce P2 notifications."""
        now = datetime.now(tz=UTC)
        decisions = [
            {
                "id": "uuid-d1",
                "title": "Switch to Kubernetes",
                "decision_made": "Adopt K8s for deployment",
                "expected_outcome": "Better scalability",
                "review_date": now - timedelta(days=5),
            },
            {
                "id": "uuid-d2",
                "title": "Hire contractor",
                "decision_made": "Engage freelance dev",
                "expected_outcome": "Ship faster",
                "review_date": now - timedelta(days=1),
            },
        ]
        session = _mock_session(query_results=decisions)
        mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))

        with patch("src.app.workers.heartbeat.get_fatigue_manager", return_value=mgr):
            await check_decisions_due_review(session)

        assert mgr.pending_count == 2
        messages = [n.message for n in mgr._pending_p2]
        assert any("Switch to Kubernetes" in m for m in messages)
        assert any("Hire contractor" in m for m in messages)
        assert all(n.category == "decision_review" for n in mgr._pending_p2)

    async def test_decision_notification_message_format(self):
        """Decision notification should include title, decision_made, and review_date."""
        now = datetime.now(tz=UTC)
        review_date = now - timedelta(days=3)
        decisions = [
            {
                "id": "uuid-d1",
                "title": "Use Postgres",
                "decision_made": "PostgreSQL over MongoDB",
                "expected_outcome": "Simpler ops",
                "review_date": review_date,
            },
        ]
        session = _mock_session(query_results=decisions)
        mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))

        with patch("src.app.workers.heartbeat.get_fatigue_manager", return_value=mgr):
            await check_decisions_due_review(session)

        msg = mgr._pending_p2[0].message
        assert "Use Postgres" in msg
        assert "PostgreSQL over MongoDB" in msg
        assert str(review_date) in msg
        assert "How did it turn out?" in msg


# ---------------------------------------------------------------------------
# check_habit_streaks
# ---------------------------------------------------------------------------


class TestCheckHabitStreaks:
    async def test_no_broken_habits(self):
        """When no habits have broken streaks, logs zero count."""
        session = _mock_session()

        with (
            patch(
                "src.app.persistence.repositories.habits.check_broken_streaks",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("src.app.workers.heartbeat.logger") as mock_logger,
        ):
            await check_habit_streaks(session)
            mock_logger.info.assert_any_call("habit_streaks_check_complete", broken_count=0)

    async def test_generates_notifications_for_broken_habits(self):
        """Broken habits should produce P2 notifications and reset streaks."""
        import uuid

        habit1 = MagicMock()
        habit1.id = uuid.uuid4()
        habit1.name = "Meditation"
        habit1.current_streak = 15
        habit1.longest_streak = 30

        habit2 = MagicMock()
        habit2.id = uuid.uuid4()
        habit2.name = "Exercise"
        habit2.current_streak = 7
        habit2.longest_streak = 45

        session = AsyncMock()
        session.commit = AsyncMock()
        mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))

        with (
            patch(
                "src.app.persistence.repositories.habits.check_broken_streaks",
                new_callable=AsyncMock,
                return_value=[habit1, habit2],
            ),
            patch(
                "src.app.persistence.repositories.habits.reset_streak",
                new_callable=AsyncMock,
            ) as mock_reset,
            patch("src.app.workers.heartbeat.get_fatigue_manager", return_value=mgr),
        ):
            await check_habit_streaks(session)

        # Both habits should have been reset
        assert mock_reset.call_count == 2
        mock_reset.assert_any_call(session, habit1.id)
        mock_reset.assert_any_call(session, habit2.id)

        # Both habits should have P2 notifications
        assert mgr.pending_count == 2
        messages = [n.message for n in mgr._pending_p2]
        assert any("Meditation" in m for m in messages)
        assert any("Exercise" in m for m in messages)
        assert all(n.category == "habit" for n in mgr._pending_p2)

    async def test_habit_notification_message_format(self):
        """Habit notification should include name, streak count, and longest streak."""
        import uuid

        habit = MagicMock()
        habit.id = uuid.uuid4()
        habit.name = "Reading"
        habit.current_streak = 10
        habit.longest_streak = 25

        session = AsyncMock()
        session.commit = AsyncMock()
        mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))

        with (
            patch(
                "src.app.persistence.repositories.habits.check_broken_streaks",
                new_callable=AsyncMock,
                return_value=[habit],
            ),
            patch(
                "src.app.persistence.repositories.habits.reset_streak",
                new_callable=AsyncMock,
            ),
            patch("src.app.workers.heartbeat.get_fatigue_manager", return_value=mgr),
        ):
            await check_habit_streaks(session)

        msg = mgr._pending_p2[0].message
        assert "Reading" in msg
        assert "10 completions" in msg
        assert "Longest streak: 25" in msg
        assert "Time to restart!" in msg

    async def test_commits_after_each_reset(self):
        """session.commit() should be called after each streak reset."""
        import uuid

        habit = MagicMock()
        habit.id = uuid.uuid4()
        habit.name = "Journaling"
        habit.current_streak = 5
        habit.longest_streak = 20

        session = AsyncMock()
        session.commit = AsyncMock()
        mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))

        with (
            patch(
                "src.app.persistence.repositories.habits.check_broken_streaks",
                new_callable=AsyncMock,
                return_value=[habit],
            ),
            patch(
                "src.app.persistence.repositories.habits.reset_streak",
                new_callable=AsyncMock,
            ),
            patch("src.app.workers.heartbeat.get_fatigue_manager", return_value=mgr),
        ):
            await check_habit_streaks(session)

        session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# check_relationship_decay — with interaction context and LLM nudges
# ---------------------------------------------------------------------------


class TestCheckRelationshipDecayWithContext:
    async def test_passes_interaction_context_to_generate_nudge(self):
        """When interactions exist, context should be passed to _generate_nudge."""
        now = datetime.now(tz=UTC)
        decayed = [
            {
                "id": uuid.uuid4(),
                "first_name": "Dave",
                "last_name": "Wilson",
                "interaction_frequency_days": 14,
                "last_interaction_at": now - timedelta(days=21),
                "relationship_score": 50.0,
                "how_we_met": "Hackathon",
                "tags": ["dev", "friend"],
            },
        ]
        interactions = [
            {
                "summary": "Discussed Rust project",
                "topics": ["Rust", "WebAssembly"],
                "interaction_at": datetime(2026, 3, 1, tzinfo=UTC),
            },
        ]

        session = _mock_session_multi([decayed, interactions])
        mgr = FatigueManager(dnd_start=time(22, 0), dnd_end=time(7, 0))

        with (
            patch("src.app.workers.heartbeat.get_fatigue_manager", return_value=mgr),
            patch(
                "src.app.workers.heartbeat._generate_nudge",
                new_callable=AsyncMock,
                return_value="Hey Dave, time to reconnect!",
            ) as mock_nudge,
        ):
            await check_relationship_decay(session)

        mock_nudge.assert_awaited_once()
        call_kwargs = mock_nudge.call_args.kwargs
        assert call_kwargs["full_name"] == "Dave Wilson"
        assert call_kwargs["how_we_met"] == "Hackathon"
        assert call_kwargs["tags"] == ["dev", "friend"]
        assert "Discussed Rust project" in call_kwargs["interaction_context"]
