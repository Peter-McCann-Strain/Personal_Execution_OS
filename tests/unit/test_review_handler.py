"""Tests for review handler — handle_review and _aggregate_week_data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.specialists.review import (
    PatternNoticed,
    Recommendation,
    WeeklyReview,
)
from src.app.domain.models import (
    ChatResponse,
    Intent,
    IntentType,
    MessageInput,
    Specialist,
)
from src.app.domain.services.handlers.review import (
    _aggregate_week_data,
    handle_review,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(content: str = "weekly review") -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _make_intent() -> Intent:
    return Intent(
        intent_type=IntentType.REVIEW,
        confidence=0.95,
        specialist=Specialist.REVIEW,
        reasoning="Review request",
    )


def _make_mapping_row(data: dict) -> dict:
    """Return a plain dict to simulate a SQLAlchemy RowMapping."""
    return data


def _make_mock_result(rows: list[dict]) -> MagicMock:
    """Create a mock SQLAlchemy result with mappings().all()."""
    mappings_mock = MagicMock()
    mappings_mock.all.return_value = rows

    result = MagicMock()
    result.mappings.return_value = mappings_mock
    return result


def _make_empty_result() -> MagicMock:
    return _make_mock_result([])


def _sample_episodes() -> list[dict]:
    now = datetime.now(tz=UTC)
    return [
        {
            "id": "ep-1",
            "summary": "Had a great workout",
            "episode_type": "diary",
            "mood_score": 8.0,
            "energy_rating": 7.0,
            "created_at": now - timedelta(days=2),
        },
        {
            "id": "ep-2",
            "summary": "Stressful meeting",
            "episode_type": "diary",
            "mood_score": 4.0,
            "energy_rating": 3.0,
            "created_at": now - timedelta(days=1),
        },
    ]


def _sample_goals() -> list[dict]:
    return [
        {
            "title": "Ship MVP",
            "progress": 0.65,
            "status": "active",
            "goal_type": "quarterly",
        },
    ]


def _sample_commitments() -> list[dict]:
    return [
        {
            "normalized_action": "Send report to boss",
            "status": "detected",
            "temporal_normalized": datetime(2026, 3, 20, tzinfo=UTC),
            "created_at": datetime.now(tz=UTC),
        },
    ]


def _sample_projects() -> list[dict]:
    return [
        {
            "title": "Personal Assistant",
            "status": "in_progress",
            "deadline": datetime(2026, 6, 30, tzinfo=UTC),
        },
    ]


def _make_weekly_review(**overrides) -> WeeklyReview:
    """Build a WeeklyReview with sensible defaults, overridable."""
    defaults = {
        "period": "week of 2026-03-09 to 2026-03-16",
        "accomplishments": ["Completed integration tests"],
        "mood_summary": "Generally positive",
        "average_mood": 6.0,
        "goal_progress": [],
        "open_commitments": [
            {"action": "Send report to boss"},
        ],
        "relationship_alerts": [],
        "patterns_noticed": [PatternNoticed(pattern="Energy drops after lunch")],
        "recommendations": [Recommendation(action="Schedule deep work before noon")],
        "key_insight": "Good progress overall",
    }
    defaults.update(overrides)
    return WeeklyReview(**defaults)


# ---------------------------------------------------------------------------
# _aggregate_week_data tests
# ---------------------------------------------------------------------------


class TestAggregateWeekData:
    async def test_with_full_data(self):
        """All four queries return data — episodes, goals, commitments, projects."""
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _make_mock_result(_sample_episodes()),
                _make_mock_result(_sample_goals()),
                _make_mock_result(_sample_commitments()),
                _make_mock_result(_sample_projects()),
            ]
        )

        result = await _aggregate_week_data(session)

        assert "Total captures: 2" in result
        assert "Average mood:" in result
        assert "Average energy:" in result
        assert "Diary entries:" in result
        assert "Had a great workout" in result
        assert "Stressful meeting" in result
        assert "Goals:" in result
        assert "Ship MVP: 65%" in result
        assert "Open commitments:" in result
        assert "Send report to boss" in result
        assert "Active projects:" in result
        assert "Personal Assistant" in result
        assert "(deadline:" in result

    async def test_empty_data(self):
        """All queries return empty — should still produce header lines."""
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        result = await _aggregate_week_data(session)

        assert "Total captures: 0" in result
        assert "Diary entries:" not in result
        assert "Goals:" not in result
        assert "Open commitments:" not in result
        assert "Active projects:" not in result

    async def test_average_mood_none_when_all_null(self):
        """When all mood_score values are None, average mood is omitted."""
        episodes = [
            {
                "id": "ep-1",
                "summary": "test",
                "episode_type": "diary",
                "mood_score": None,
                "energy_rating": None,
                "created_at": datetime.now(tz=UTC),
            },
        ]
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _make_mock_result(episodes),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        result = await _aggregate_week_data(session)

        assert "Average mood:" not in result
        assert "Average energy:" not in result

    async def test_episodes_with_none_summary(self):
        """Episodes with None summary show '(no summary)'."""
        episodes = [
            {
                "id": "ep-1",
                "summary": None,
                "episode_type": "diary",
                "mood_score": None,
                "energy_rating": None,
                "created_at": datetime.now(tz=UTC),
            },
        ]
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _make_mock_result(episodes),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        result = await _aggregate_week_data(session)

        assert "(no summary)" in result

    async def test_episodes_with_none_created_at(self):
        """Episodes with None created_at show '?' as date."""
        episodes = [
            {
                "id": "ep-1",
                "summary": "Something happened",
                "episode_type": "diary",
                "mood_score": 5.0,
                "energy_rating": None,
                "created_at": None,
            },
        ]
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _make_mock_result(episodes),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        result = await _aggregate_week_data(session)

        assert "[?]" in result
        assert "[mood: 5.0]" in result

    async def test_goals_with_none_progress(self):
        """Goals with None progress should show 0%."""
        goals = [
            {
                "title": "Undefined Goal",
                "progress": None,
                "status": "active",
                "goal_type": "quarterly",
            },
        ]
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_mock_result(goals),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        result = await _aggregate_week_data(session)

        assert "Undefined Goal: 0% (active)" in result

    async def test_projects_without_deadline(self):
        """Projects with no deadline should not show '(deadline: ...)'."""
        projects = [
            {
                "title": "Side Project",
                "status": "planning",
                "deadline": None,
            },
        ]
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_mock_result(projects),
            ]
        )

        result = await _aggregate_week_data(session)

        assert "Side Project [planning]" in result
        assert "(deadline:" not in result

    async def test_week_date_range_in_header(self):
        """The result should contain date range in the header."""
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        result = await _aggregate_week_data(session)

        assert "Week of" in result
        assert " to " in result


# ---------------------------------------------------------------------------
# handle_review tests
# ---------------------------------------------------------------------------


class TestHandleReview:
    @pytest.fixture(autouse=True)
    def _mock_due_items(self):
        with patch(
            "src.app.domain.services.handlers.review._get_spaced_repetition_items",
            new_callable=AsyncMock,
            return_value=[],
        ):
            yield

    async def test_full_review_all_sections(self):
        """Review with all sections populated generates complete output."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        # Set up _aggregate_week_data queries
        mock_session.execute = AsyncMock(
            side_effect=[
                _make_mock_result(_sample_episodes()),
                _make_mock_result(_sample_goals()),
                _make_mock_result(_sample_commitments()),
                _make_mock_result(_sample_projects()),
            ]
        )

        review = _make_weekly_review()

        with patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        assert isinstance(result, ChatResponse)
        assert result.agent == "review"
        assert "# Weekly Review:" in result.content
        assert "**Key Insight:** Good progress overall" in result.content
        assert "**Mood:** Generally positive" in result.content
        assert "Average: 6.0/10" in result.content
        assert "**Accomplishments:**" in result.content
        assert "- Completed integration tests" in result.content
        assert "**Patterns Noticed:**" in result.content
        assert "- Energy drops after lunch" in result.content
        assert "**Open Commitments (1):**" in result.content
        assert "- Send report to boss" in result.content
        assert "**Recommendations:**" in result.content
        assert "- Schedule deep work before noon" in result.content
        assert result.metadata["period"] == review.period
        assert result.metadata["average_mood"] == 6.0
        assert result.metadata["accomplishment_count"] == 1
        assert result.metadata["recommendation_count"] == 1

    async def test_review_no_key_insight(self):
        """Review without key_insight should not include that line."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        review = _make_weekly_review(key_insight=None)

        with patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        assert "**Key Insight:**" not in result.content

    async def test_review_no_mood_summary(self):
        """Review without mood_summary omits the mood section entirely."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        review = _make_weekly_review(mood_summary=None, average_mood=None)

        with patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        assert "**Mood:**" not in result.content
        assert "Average:" not in result.content

    async def test_review_mood_without_average(self):
        """Mood summary present but average_mood is None."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        review = _make_weekly_review(mood_summary="Mixed feelings", average_mood=None)

        with patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        assert "**Mood:** Mixed feelings" in result.content
        assert "Average:" not in result.content

    async def test_review_empty_accomplishments(self):
        """Review with no accomplishments omits that section."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        review = _make_weekly_review(accomplishments=[])

        with patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        assert "**Accomplishments:**" not in result.content

    async def test_review_empty_patterns(self):
        """Review with no patterns omits that section."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        review = _make_weekly_review(patterns_noticed=[])

        with patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        assert "**Patterns Noticed:**" not in result.content

    async def test_review_empty_commitments(self):
        """Review with no open commitments omits that section."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        review = _make_weekly_review(open_commitments=[])

        with patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        assert "**Open Commitments" not in result.content

    async def test_review_empty_recommendations(self):
        """Review with no recommendations omits that section."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        review = _make_weekly_review(recommendations=[])

        with patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        assert "**Recommendations:**" not in result.content

    async def test_review_commitment_with_normalized_action_key(self):
        """Commitments using 'normalized_action' key instead of 'action'."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        review = _make_weekly_review(
            open_commitments=[
                {"normalized_action": "Follow up with client"},
            ]
        )

        with patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        assert "- Follow up with client" in result.content

    async def test_review_commitment_fallback_to_str(self):
        """Commitments without 'action' or 'normalized_action' fall back to str."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        review = _make_weekly_review(
            open_commitments=[
                {"status": "pending", "some_field": "data"},
            ]
        )

        with patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        # Falls back to str(c) for the commitment
        assert "**Open Commitments (1):**" in result.content

    async def test_review_metadata_counts(self):
        """Metadata includes correct counts even with empty sections."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        review = _make_weekly_review(
            accomplishments=["A", "B", "C"],
            recommendations=[Recommendation(action="R1"), Recommendation(action="R2")],
        )

        with patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        assert result.metadata["accomplishment_count"] == 3
        assert result.metadata["recommendation_count"] == 2

    async def test_review_due_items_are_rendered(self):
        """Review includes due spaced-repetition items when present."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        review = _make_weekly_review(
            accomplishments=[],
            patterns_noticed=[],
            open_commitments=[],
            recommendations=[],
        )

        due_items = [
            {
                "id": "ep-due-1",
                "summary": None,
                "content": "Long form note that should appear in the due-items section.",
            },
            {
                "id": "ep-due-2",
                "summary": "Concise note",
                "content": "ignored because summary is present",
            },
        ]

        with (
            patch(
                "src.app.domain.services.handlers.review.generate_weekly_review",
                new_callable=AsyncMock,
                return_value=review,
            ),
            patch(
                "src.app.domain.services.handlers.review._get_spaced_repetition_items",
                new_callable=AsyncMock,
                return_value=due_items,
            ),
            patch(
                "src.app.domain.services.handlers.review.enqueue_entity_extraction",
                new_callable=AsyncMock,
            ),
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        assert "**Due for Review (2):**" in result.content
        assert "- Long form note that should appear in the due-items section." in result.content
        assert "- Concise note" in result.content
        assert result.metadata["spaced_repetition_due"] == 2

    async def test_review_entity_extraction_failure_is_swallowed(self):
        """Entity extraction failures should not block the review reply."""
        message = _make_message()
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
                _make_empty_result(),
            ]
        )

        review = _make_weekly_review(
            accomplishments=[],
            patterns_noticed=[],
            open_commitments=[],
            recommendations=[],
        )

        with (
            patch(
                "src.app.domain.services.handlers.review.generate_weekly_review",
                new_callable=AsyncMock,
                return_value=review,
            ),
            patch(
                "src.app.domain.services.handlers.review._get_spaced_repetition_items",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.domain.services.handlers.review.enqueue_entity_extraction",
                new_callable=AsyncMock,
                side_effect=RuntimeError("graph offline"),
            ),
        ):
            result = await handle_review(message, mock_client, mock_session, _make_intent())

        assert result.agent == "review"
        assert "Weekly Review" in result.content


class TestSpacedRepetitionItems:
    async def test_existing_spaced_repetition_state_is_reused(self):
        """Rows with spaced_repetition metadata should use existing SM-2 state."""
        session = AsyncMock()
        row = {
            "id": "ep-1",
            "summary": "Review this later",
            "content": "A long note worth revisiting.",
            "metadata": {
                "spaced_repetition": {
                    "repetitions": 3,
                    "easiness": 2.9,
                    "interval": 6,
                }
            },
        }

        result_mock = MagicMock()
        mappings_mock = MagicMock()
        mappings_mock.all.return_value = [row]
        result_mock.mappings.return_value = mappings_mock
        session.execute = AsyncMock(return_value=result_mock)

        with patch(
            "src.app.domain.services.handlers.review.calculate_next_review",
            return_value={
                "next_review_date": "2026-04-08T00:00:00+00:00",
                "interval": 12,
            },
        ) as mock_calculate:
            from src.app.domain.services.handlers.review import (
                _get_spaced_repetition_items,
            )

            items = await _get_spaced_repetition_items(session)

        assert len(items) == 1
        assert items[0]["id"] == "ep-1"
        assert items[0]["spaced_repetition"]["interval"] == 12
        mock_calculate.assert_called_once_with(
            quality=4,
            repetitions=3,
            easiness=2.9,
            interval=6,
        )

    async def test_first_review_initializes_sm2_state(self):
        """Rows without spaced_repetition metadata should initialize SM-2 state."""
        session = AsyncMock()
        row = {
            "id": "ep-2",
            "summary": "First review candidate",
            "content": "Progressive summary content",
            "metadata": {
                "progressive_summary": "true",
            },
        }

        result_mock = MagicMock()
        mappings_mock = MagicMock()
        mappings_mock.all.return_value = [row]
        result_mock.mappings.return_value = mappings_mock
        session.execute = AsyncMock(return_value=result_mock)

        with patch(
            "src.app.domain.services.handlers.review.calculate_next_review",
            return_value={
                "next_review_date": "2026-04-08T00:00:00+00:00",
                "interval": 1,
            },
        ) as mock_calculate:
            from src.app.domain.services.handlers.review import (
                _get_spaced_repetition_items,
            )

            items = await _get_spaced_repetition_items(session)

        assert len(items) == 1
        assert items[0]["id"] == "ep-2"
        assert items[0]["spaced_repetition"]["interval"] == 1
        mock_calculate.assert_called_once_with(
            quality=4,
            repetitions=0,
            easiness=2.5,
            interval=1,
        )

    async def test_query_failure_propagates(self):
        """Database errors in spaced repetition lookup should propagate."""
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=RuntimeError("db down"))

        from src.app.core.exceptions import DatabaseError

        with patch("src.app.domain.services.handlers.review.logger.error") as mock_error:
            from src.app.domain.services.handlers.review import (
                _get_spaced_repetition_items,
            )

            with pytest.raises(
                DatabaseError,
                match="Spaced repetition lookup failed with RuntimeError: db down",
            ):
                await _get_spaced_repetition_items(session)

        mock_error.assert_called_once()
