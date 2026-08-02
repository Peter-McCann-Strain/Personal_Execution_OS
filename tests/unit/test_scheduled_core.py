"""Safety-boundary tests for scheduled notifications and reviews."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.app.agents.tools.calendar import CalendarEvent
from src.app.core.exceptions import ConfigError, LLMError
from src.app.workers import scheduled
from src.app.workers.scheduled import (
    _get_calendar_section,
    _get_curated_content_section,
    _goal_progress_percentage,
    _human_deadline,
    _nonnegative_int,
    _send_to_users,
    _split_message,
    _truncate_preview,
)

_STRINGIFY = object()


class _Secret:
    def __init__(self, value: str) -> None:
        self.value = value

    def get_secret_value(self) -> str:
        return self.value


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "allowed_user_ids": [123],
        "anthropic_api_key": _Secret("test-anthropic-key"),
        "google_client_id": "test-google-client",
        "google_client_secret": _Secret("test-google-secret"),
        "google_configured": False,
        "google_refresh_token": _Secret("test-google-refresh"),
        "redis_url": _Secret("redis://test"),
        "user_timezone": "UTC",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _session_factory(
    *,
    execute_side_effect: object | None = None,
) -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    if execute_side_effect is not None:
        session.execute.side_effect = execute_side_effect
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=session)
    context_manager.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=context_manager)
    return factory, session


@pytest.mark.parametrize(
    ("message", "limit", "expected"),
    [
        ("hello", 100, ["hello"]),
        ("", 100, [""]),
        ("a" * 20, 10, ["a" * 10, "a" * 10]),
        ("line one\nline two\nline three", 18, ["line one\nline two", "line three"]),
    ],
)
def test_split_message(message: str, limit: int, expected: list[str]) -> None:
    assert _split_message(message, limit) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("not-a-date", "not-a-date"),
        (object(), _STRINGIFY),
    ],
)
def test_human_deadline_preserves_unparseable_values(value: object, expected: object) -> None:
    now = datetime(2026, 8, 2, 9, tzinfo=UTC)

    result = _human_deadline(value, now, ZoneInfo("UTC"))

    assert result == (str(value) if expected is _STRINGIFY else expected)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 8, 1, 8), "overdue since yesterday ⚠️"),
        (datetime(2026, 7, 30, 8, tzinfo=UTC), "overdue — 3 days ago ⚠️"),
        (datetime(2026, 8, 2, 13, 30, tzinfo=UTC), "due today at 1:30pm"),
        (datetime(2026, 8, 3, 9, tzinfo=UTC), "due tomorrow at 9:00am"),
        (date(2026, 8, 5), "due Wednesday at 12:00am (3 days)"),
        (datetime(2026, 8, 12, 9, tzinfo=UTC), "due 12 Aug at 9:00am"),
    ],
)
def test_human_deadline_formats_each_relative_window(value: object, expected: str) -> None:
    now = datetime(2026, 8, 2, 9, tzinfo=UTC)

    assert _human_deadline(value, now, ZoneInfo("UTC")) == expected


def test_truncate_preview_collapses_whitespace_and_caps_length() -> None:
    assert _truncate_preview("  a\n b\tc  ") == "a b c"
    assert _truncate_preview("abcdefghij", limit=7) == "abcd..."
    assert _truncate_preview("abc", limit=2) == "a..."


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 0), (0, 0), (0.425, 42), (1, 100)],
)
def test_goal_progress_percentage_accepts_valid_ratios(
    value: object,
    expected: int,
) -> None:
    assert _goal_progress_percentage(value) == expected


@pytest.mark.parametrize("value", ["0.5", True, object()])
def test_goal_progress_percentage_rejects_non_numeric_values(value: object) -> None:
    with pytest.raises(TypeError, match=r"goal\.progress must be numeric"):
        _goal_progress_percentage(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_goal_progress_percentage_rejects_invalid_numeric_values(value: float) -> None:
    with pytest.raises(ValueError, match=r"goal\.progress must"):
        _goal_progress_percentage(value)


@pytest.mark.parametrize(("value", "expected"), [(0, 0), (7, 7)])
def test_nonnegative_int_accepts_valid_counters(value: object, expected: int) -> None:
    assert _nonnegative_int(value, "habit.streak") == expected


@pytest.mark.parametrize("value", ["7", True, 1.5])
def test_nonnegative_int_rejects_non_integer_counters(value: object) -> None:
    with pytest.raises(TypeError, match=r"habit\.streak must be an integer"):
        _nonnegative_int(value, "habit.streak")


def test_nonnegative_int_rejects_negative_counters() -> None:
    with pytest.raises(ValueError, match=r"habit\.streak must be non-negative"):
        _nonnegative_int(-1, "habit.streak")


@pytest.mark.asyncio
async def test_send_to_users_reports_missing_optional_telegram() -> None:
    with pytest.raises(ConfigError, match="Telegram bot is not available"):
        await _send_to_users({"bot": None}, "private scheduled content")


@pytest.mark.asyncio
async def test_send_to_users_requires_settings_before_external_delivery() -> None:
    bot = AsyncMock()

    with pytest.raises(ConfigError, match="Worker settings are not available"):
        await _send_to_users({"bot": bot}, "private scheduled content")

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_to_users_delivers_each_chunk_to_each_allowed_user() -> None:
    bot = AsyncMock()
    settings = _settings(allowed_user_ids=[123, 456])

    await _send_to_users(
        {"bot": bot, "settings": settings},
        "a" * 5000,
    )

    assert bot.send_message.await_count == 4
    assert [call.args[0] for call in bot.send_message.await_args_list] == [123, 123, 456, 456]


@pytest.mark.asyncio
async def test_send_to_users_isolates_one_telegram_failure() -> None:
    bot = AsyncMock()
    bot.send_message.side_effect = [RuntimeError("first user unavailable"), None]
    settings = _settings(allowed_user_ids=[123, 456])

    with patch.object(scheduled, "TelegramAPIError", RuntimeError):
        await _send_to_users({"bot": bot, "settings": settings}, "briefing")

    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_calendar_section_is_disabled_without_google_credentials() -> None:
    with patch("src.app.agents.tools.calendar.CalendarService") as service_class:
        result = await _get_calendar_section(_settings(google_configured=False))

    assert result == ""
    service_class.assert_not_called()


@pytest.mark.asyncio
async def test_calendar_section_formats_only_todays_events_and_closes_client() -> None:
    now = datetime.now(UTC)
    events = [
        CalendarEvent(
            id="timed",
            summary="Planning",
            start=now.replace(hour=10, minute=0, second=0, microsecond=0),
            end=now.replace(hour=11, minute=0, second=0, microsecond=0),
            location="Office",
        ),
        CalendarEvent(
            id="all-day",
            summary="Release day",
            start=date.today(),
            end=date.today(),
        ),
        CalendarEvent(
            id="tomorrow",
            summary="Not today",
            start=now + timedelta(days=1),
            end=now + timedelta(days=1, hours=1),
        ),
    ]
    calendar = MagicMock()
    calendar.get_upcoming_events = AsyncMock(return_value=events)
    calendar.close = AsyncMock()

    with patch(
        "src.app.agents.tools.calendar.CalendarService",
        return_value=calendar,
    ) as service_class:
        result = await _get_calendar_section(_settings(google_configured=True))

    assert "TODAY'S SCHEDULE (2 events):" in result
    assert "[10:00-11:00] Planning @ Office" in result
    assert "[All day] Release day" in result
    assert "Not today" not in result
    service_class.assert_called_once_with(
        client_id="test-google-client",
        client_secret="test-google-secret",
        refresh_token="test-google-refresh",
    )
    calendar.get_upcoming_events.assert_awaited_once_with(days=1, max_results=20)
    calendar.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_calendar_section_returns_empty_when_provider_has_no_events() -> None:
    calendar = MagicMock()
    calendar.get_upcoming_events = AsyncMock(return_value=[])
    calendar.close = AsyncMock()

    with patch(
        "src.app.agents.tools.calendar.CalendarService",
        return_value=calendar,
    ):
        result = await _get_calendar_section(_settings(google_configured=True))

    assert result == ""
    calendar.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_calendar_section_returns_empty_when_events_are_not_today() -> None:
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    calendar = MagicMock()
    calendar.get_upcoming_events = AsyncMock(
        return_value=[
            CalendarEvent(
                id="tomorrow",
                summary="Future event",
                start=tomorrow,
                end=tomorrow + timedelta(hours=1),
            )
        ]
    )
    calendar.close = AsyncMock()

    with patch(
        "src.app.agents.tools.calendar.CalendarService",
        return_value=calendar,
    ):
        result = await _get_calendar_section(_settings(google_configured=True))

    assert result == ""


@pytest.mark.asyncio
async def test_calendar_section_wraps_provider_error_and_still_closes_client() -> None:
    calendar = MagicMock()
    calendar.get_upcoming_events = AsyncMock(side_effect=ValueError("provider unavailable"))
    calendar.close = AsyncMock()

    with (
        patch(
            "src.app.agents.tools.calendar.CalendarService",
            return_value=calendar,
        ),
        pytest.raises(RuntimeError, match="calendar briefing failed: provider unavailable"),
    ):
        await _get_calendar_section(_settings(google_configured=True))

    calendar.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_curated_content_section_delegates_to_digest_store() -> None:
    get_latest_digest = AsyncMock(return_value="CURATED")
    ctx = {"session_factory": object()}

    with patch(
        "src.app.workers.curation.get_latest_digest",
        get_latest_digest,
    ):
        result = await _get_curated_content_section(ctx)

    assert result == "CURATED"
    get_latest_digest.assert_awaited_once_with(ctx)


@pytest.mark.asyncio
async def test_morning_briefing_disabled_without_database() -> None:
    send = AsyncMock()

    with patch.object(scheduled, "_send_to_users", send):
        await scheduled.morning_briefing({})

    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_morning_briefing_formats_all_sources_before_one_delivery() -> None:
    factory, _session = _session_factory()
    mapping_rows = AsyncMock(
        side_effect=[
            [
                {
                    "normalized_action": "Submit report",
                    "temporal_normalized": datetime.now(UTC) - timedelta(days=1),
                }
            ],
            [
                {
                    "normalized_action": "Call supplier",
                    "temporal_normalized": datetime.now(UTC) + timedelta(hours=2),
                }
            ],
            [{"title": "Launch", "progress": 0.42}],
            [
                {
                    "title": "Platform",
                    "status": "active",
                    "deadline": datetime.now(UTC) + timedelta(days=2),
                },
                {"title": "Documentation", "status": "active", "deadline": None},
            ],
            [
                {
                    "name": "Walk",
                    "current_streak": 1,
                    "longest_streak": 0,
                    "frequency": "daily",
                },
                {
                    "name": "Read",
                    "current_streak": 4,
                    "longest_streak": 8,
                    "frequency": "daily",
                },
            ],
        ]
    )
    fatigue = MagicMock()
    fatigue.flush_morning_digest = AsyncMock(return_value=["queued"])
    fatigue.format_digest.return_value = "QUEUED NOTIFICATIONS"
    conversation = MagicMock()
    conversation.set_pending_planning_session = AsyncMock(
        side_effect=RuntimeError("redis unavailable")
    )
    send = AsyncMock()
    invalid_timezone_settings = _settings(user_timezone="Mars/Olympus")

    with (
        patch.object(scheduled, "mapping_rows", mapping_rows),
        patch.object(scheduled, "load_latest_day_plan", AsyncMock(return_value=None)),
        patch.object(
            scheduled,
            "load_carry_over_tasks",
            AsyncMock(return_value=["Finish yesterday's draft"]),
        ),
        patch.object(
            scheduled,
            "_get_calendar_section",
            AsyncMock(return_value="TODAY'S SCHEDULE (1 event):\n  - [09:00] Stand-up"),
        ),
        patch.object(scheduled, "get_fatigue_manager", return_value=fatigue),
        patch.object(
            scheduled,
            "_get_curated_content_section",
            AsyncMock(return_value="CURATED READING"),
        ),
        patch.object(scheduled, "ConversationContext", return_value=conversation),
        patch.object(scheduled, "_send_to_users", send),
    ):
        await scheduled.morning_briefing(
            {
                "session_factory": factory,
                "settings": invalid_timezone_settings,
            }
        )

    send.assert_awaited_once()
    briefing = send.await_args.args[1]
    assert briefing.index("TODAY'S SCHEDULE") < briefing.index("OVERDUE")
    for expected in (
        "Submit report",
        "Call supplier",
        "Launch (42% complete)",
        "Documentation [active]",
        "Walk: 1 day streak",
        "Read: 4 days streak [daily] (best: 8)",
        "Finish yesterday's draft",
        "QUEUED NOTIFICATIONS",
        "CURATED READING",
    ):
        assert expected in briefing
    conversation.set_pending_planning_session.assert_awaited_once()
    planning_session = conversation.set_pending_planning_session.await_args.args[1]
    assert planning_session.source_date == datetime.now(UTC).date().isoformat()
    assert invalid_timezone_settings.user_timezone == "Mars/Olympus"


@pytest.mark.asyncio
async def test_morning_briefing_handles_empty_optional_sources_without_settings() -> None:
    factory, _session = _session_factory()
    fatigue = MagicMock()
    fatigue.flush_morning_digest = AsyncMock(return_value=[])
    send = AsyncMock()

    with (
        patch.object(
            scheduled,
            "mapping_rows",
            AsyncMock(side_effect=[[], [], [], [], []]),
        ),
        patch.object(scheduled, "get_fatigue_manager", return_value=fatigue),
        patch.object(
            scheduled,
            "_get_curated_content_section",
            AsyncMock(return_value=""),
        ),
        patch.object(scheduled, "_send_to_users", send),
    ):
        await scheduled.morning_briefing({"session_factory": factory})

    send.assert_awaited_once()
    assert "Nothing urgent today. Have a great day!" in send.await_args.args[1]
    assert "You do not have a plan locked in for today yet." in send.await_args.args[1]


@pytest.mark.asyncio
async def test_morning_briefing_uses_existing_day_plan_without_seeding_session() -> None:
    factory, _session = _session_factory()
    stored_plan = SimpleNamespace(plan=object())
    fatigue = MagicMock()
    fatigue.flush_morning_digest = AsyncMock(return_value=[])
    send = AsyncMock()
    conversation_class = MagicMock()

    with (
        patch.object(
            scheduled,
            "mapping_rows",
            AsyncMock(side_effect=[[], [], [], [], []]),
        ),
        patch.object(scheduled, "load_latest_day_plan", AsyncMock(return_value=stored_plan)),
        patch.object(scheduled, "build_day_plan_section", return_value="TODAY'S PLAN:\n  - Ship"),
        patch.object(scheduled, "_get_calendar_section", AsyncMock(return_value="")),
        patch.object(scheduled, "get_fatigue_manager", return_value=fatigue),
        patch.object(
            scheduled,
            "_get_curated_content_section",
            AsyncMock(return_value=""),
        ),
        patch.object(scheduled, "ConversationContext", conversation_class),
        patch.object(scheduled, "_send_to_users", send),
    ):
        await scheduled.morning_briefing({"session_factory": factory, "settings": _settings()})

    assert "TODAY'S PLAN:\n  - Ship" in send.await_args.args[1]
    conversation_class.assert_not_called()


@pytest.mark.asyncio
async def test_morning_briefing_propagates_database_error_without_delivery() -> None:
    factory, _session = _session_factory(
        execute_side_effect=RuntimeError("database unavailable"),
    )
    send = AsyncMock()

    with (
        patch.object(scheduled, "_send_to_users", send),
        pytest.raises(RuntimeError, match="database unavailable"),
    ):
        await scheduled.morning_briefing({"session_factory": factory, "settings": _settings()})

    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_morning_briefing_propagates_calendar_error_without_delivery() -> None:
    factory, _session = _session_factory()
    send = AsyncMock()

    with (
        patch.object(
            scheduled,
            "mapping_rows",
            AsyncMock(side_effect=[[], [], [], [], []]),
        ),
        patch.object(scheduled, "load_latest_day_plan", AsyncMock(return_value=None)),
        patch.object(scheduled, "load_carry_over_tasks", AsyncMock(return_value=[])),
        patch.object(
            scheduled,
            "_get_calendar_section",
            AsyncMock(side_effect=RuntimeError("calendar unavailable")),
        ),
        patch.object(scheduled, "_send_to_users", send),
        pytest.raises(RuntimeError, match="calendar unavailable"),
    ):
        await scheduled.morning_briefing({"session_factory": factory, "settings": _settings()})

    send.assert_not_awaited()


def _review_context(
    review_name: str,
    *,
    sparse: bool = False,
) -> tuple[dict[str, object], AsyncMock]:
    if review_name == "weekly_review":
        rows = [
            [{"mood_score": 7.0}],
            [{"title": "Launch", "progress": 0.5, "status": "active"}],
            [{"normalized_action": "Send update", "status": "confirmed"}],
            [{"title": "Platform", "status": "active"}],
            [
                {
                    "title": "Choose vendor",
                    "decision_made": "Vendor A",
                    "expected_outcome": None,
                    "review_date": date.today(),
                }
            ],
        ]
        factory, _session = _session_factory()
    elif review_name == "monthly_review":
        rows = [
            [{"mood_score": None if sparse else 8.0}],
            [{"title": "Launch", "progress": None, "status": "active"}],
            [
                {
                    "name": "Walk",
                    "current_streak": 5,
                    "longest_streak": 9,
                    "total_completions": 20,
                }
            ],
        ]
        factory, _session = _session_factory()
    elif review_name == "quarterly_review":
        rows = [
            [{"mood_score": 7.5}],
            [{"title": "Launch", "progress": 1, "status": "completed"}],
            [{"title": "Vendor", "actual_outcome": None}],
            [{"first_name": "Ada", "last_name": None, "relationship_score": 9}],
        ]
        factory, _session = _session_factory()
    else:
        rows = [
            [{"title": "Launch", "progress": 1, "status": "completed"}],
            [{"title": "Vendor", "actual_outcome": None, "outcome_rating": None}],
            [{"review_type": "quarterly"}],
        ]
        stats_result = MagicMock()
        stats_result.mappings.return_value.one.return_value = {
            "cnt": 42,
            "avg_mood": 8.25,
            "avg_energy": 7.0,
        }
        factory, _session = _session_factory(
            execute_side_effect=[stats_result, MagicMock(), MagicMock(), MagicMock()]
        )

    mapping_rows = AsyncMock(side_effect=rows)
    return {
        "session_factory": factory,
        "settings": _settings(),
    }, mapping_rows


def _review_result(review_name: str) -> SimpleNamespace:
    if review_name in {"weekly_review", "monthly_review"}:
        return SimpleNamespace(
            key_insight="Protect the highest-leverage work.",
            accomplishments=["Shipped"],
            recommendations=["Focus"],
        )
    if review_name == "quarterly_review":
        return SimpleNamespace(
            key_insight="Fewer priorities produced better results.",
            lessons_learned=["Constrain work in progress"],
            next_quarter_priorities=["Finish the platform"],
        )
    return SimpleNamespace(
        year_theme="Deliberate focus",
        key_insight="Consistency compounded.",
        lessons_learned=["Protect attention"],
        next_year_vision=["Build sustainably"],
    )


@pytest.mark.parametrize(
    ("review_name", "generator_name", "expected_fragments"),
    [
        (
            "weekly_review",
            "generate_weekly_review",
            ("Weekly Review:", "Accomplishments:", "Recommendations:"),
        ),
        (
            "monthly_review",
            "generate_monthly_review",
            ("Monthly Review:", "Accomplishments:", "Recommendations:"),
        ),
        (
            "quarterly_review",
            "generate_quarterly_review",
            ("Quarterly Review:", "Lessons Learned:", "Next Quarter Priorities:"),
        ),
        (
            "annual_review",
            "generate_annual_review",
            ("Annual Review:", "Theme: Deliberate focus", "Next Year Vision:"),
        ),
    ],
)
@pytest.mark.asyncio
async def test_review_success_delivers_generated_synthesis(
    review_name: str,
    generator_name: str,
    expected_fragments: tuple[str, ...],
) -> None:
    ctx, mapping_rows = _review_context(
        review_name,
        sparse=review_name == "monthly_review",
    )
    generator = AsyncMock(return_value=_review_result(review_name))
    send = AsyncMock()

    with (
        patch.object(scheduled, "mapping_rows", mapping_rows),
        patch("anthropic.AsyncAnthropic") as client_class,
        patch(
            f"src.app.agents.specialists.review.{generator_name}",
            generator,
        ),
        patch.object(scheduled, "_send_to_users", send),
    ):
        await getattr(scheduled, review_name)(ctx)

    generator.assert_awaited_once()
    client_class.assert_called_once_with(api_key="test-anthropic-key")
    send.assert_awaited_once()
    delivered = send.await_args.args[1]
    for fragment in expected_fragments:
        assert fragment in delivered


@pytest.mark.parametrize(
    ("review_name", "generator_name", "failure_prefix"),
    [
        ("weekly_review", "generate_weekly_review", "Weekly review generation failed"),
        ("monthly_review", "generate_monthly_review", "Monthly review generation failed"),
        (
            "quarterly_review",
            "generate_quarterly_review",
            "Quarterly review generation failed",
        ),
        ("annual_review", "generate_annual_review", "Annual review generation failed"),
    ],
)
@pytest.mark.asyncio
async def test_expected_llm_failure_delivers_labelled_raw_data_fallback(
    review_name: str,
    generator_name: str,
    failure_prefix: str,
) -> None:
    ctx, mapping_rows = _review_context(review_name)
    generator = AsyncMock(side_effect=LLMError("model unavailable"))
    send = AsyncMock()

    with (
        patch.object(scheduled, "mapping_rows", mapping_rows),
        patch("anthropic.AsyncAnthropic"),
        patch(
            f"src.app.agents.specialists.review.{generator_name}",
            generator,
        ),
        patch.object(scheduled, "_send_to_users", send),
    ):
        await getattr(scheduled, review_name)(ctx)

    send.assert_awaited_once()
    delivered = send.await_args.args[1]
    assert delivered.startswith(f"{failure_prefix}. Raw data:")
    assert "Total captures:" in delivered


@pytest.mark.parametrize(
    "review_name",
    ["weekly_review", "monthly_review", "quarterly_review", "annual_review"],
)
@pytest.mark.asyncio
async def test_reviews_are_disabled_without_database(
    review_name: str,
) -> None:
    send = AsyncMock()

    with patch.object(scheduled, "_send_to_users", send):
        await getattr(scheduled, review_name)({"settings": _settings()})

    send.assert_not_awaited()


@pytest.mark.parametrize(
    "review_name",
    ["weekly_review", "monthly_review", "quarterly_review", "annual_review"],
)
@pytest.mark.asyncio
async def test_reviews_are_disabled_without_settings(
    review_name: str,
) -> None:
    factory, _session = _session_factory()
    send = AsyncMock()

    with patch.object(scheduled, "_send_to_users", send):
        await getattr(scheduled, review_name)({"session_factory": factory})

    send.assert_not_awaited()
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_unexpected_review_error_propagates_without_external_delivery() -> None:
    ctx, mapping_rows = _review_context("weekly_review")
    send = AsyncMock()

    with (
        patch.object(scheduled, "mapping_rows", mapping_rows),
        patch("anthropic.AsyncAnthropic"),
        patch(
            "src.app.agents.specialists.review.generate_weekly_review",
            AsyncMock(side_effect=RuntimeError("unexpected model bug")),
        ),
        patch.object(scheduled, "_send_to_users", send),
        pytest.raises(RuntimeError, match="unexpected model bug"),
    ):
        await scheduled.weekly_review(ctx)

    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_weekly_review_handles_sparse_data_and_empty_optional_sections() -> None:
    factory, _session = _session_factory()
    generator = AsyncMock(
        return_value=SimpleNamespace(
            key_insight="Keep collecting evidence.",
            accomplishments=[],
            recommendations=[],
        )
    )
    send = AsyncMock()

    with (
        patch.object(
            scheduled,
            "mapping_rows",
            AsyncMock(side_effect=[[], [], [], [], []]),
        ),
        patch("anthropic.AsyncAnthropic"),
        patch(
            "src.app.agents.specialists.review.generate_weekly_review",
            generator,
        ),
        patch.object(scheduled, "_send_to_users", send),
    ):
        await scheduled.weekly_review({"session_factory": factory, "settings": _settings()})

    delivered = send.await_args.args[1]
    assert "Key Insight: Keep collecting evidence." in delivered
    assert "Accomplishments:" not in delivered
    assert "Recommendations:" not in delivered


@pytest.mark.asyncio
async def test_weekly_review_handles_omitted_optional_key_insight() -> None:
    """An otherwise valid sparse model response must still produce a review."""
    ctx, mapping_rows = _review_context("weekly_review")
    generator = AsyncMock(
        return_value=SimpleNamespace(
            key_insight=None,
            accomplishments=[],
            recommendations=[],
        )
    )
    send = AsyncMock()

    with (
        patch.object(scheduled, "mapping_rows", mapping_rows),
        patch("anthropic.AsyncAnthropic"),
        patch(
            "src.app.agents.specialists.review.generate_weekly_review",
            generator,
        ),
        patch.object(scheduled, "_send_to_users", send),
    ):
        await scheduled.weekly_review(ctx)

    send.assert_awaited_once()
    assert "Key Insight: No key insight provided." in send.await_args.args[1]
