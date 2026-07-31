"""Scheduled tasks — morning briefing, evening review, weekly review."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from anthropic import APIError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.app.core.analytics import average_metric
from src.app.core.async_utils import mapping_rows
from src.app.core.conversation import ConversationContext
from src.app.core.exceptions import ConfigError, LLMError
from src.app.domain.services.day_plans import (
    build_day_plan_section,
    build_morning_plan_prompt,
    build_morning_planning_session,
    load_carry_over_tasks,
    load_latest_day_plan,
    planning_owner_user_id,
    planning_source_date,
)
from src.app.workers.agent_tasks import get_fatigue_manager

logger = structlog.get_logger()

_TELEGRAM_MAX_LENGTH = 4096


def _split_message(msg: str, max_length: int) -> list[str]:
    """Split a long message into chunks, preferring line breaks."""
    if len(msg) <= max_length:
        return [msg]

    chunks: list[str] = []
    remaining = msg
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break
        # Find the last newline within the limit
        split_at = remaining.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    return chunks


def _human_deadline(dt_value, now: datetime, tz: ZoneInfo) -> str:
    """Convert a raw deadline value to a human-readable relative string.

    Accepts a datetime object or an ISO-format string. Falls back to the
    raw string representation if parsing fails so nothing is silently lost.
    """
    if dt_value is None:
        return ""

    # Normalise to datetime
    if isinstance(dt_value, str):
        try:
            dt = datetime.fromisoformat(dt_value)
        except (ValueError, TypeError):
            return str(dt_value)
    elif isinstance(dt_value, datetime):
        dt = dt_value
    elif isinstance(dt_value, date):
        # date-only value — treat as midnight UTC
        dt = datetime(dt_value.year, dt_value.month, dt_value.day, tzinfo=UTC)
    else:
        return str(dt_value)

    # Ensure timezone-aware comparison
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt_local = dt.astimezone(tz)
    now_local = now.astimezone(tz)

    delta_days = (dt_local.date() - now_local.date()).days
    time_str = dt_local.strftime("%-I:%M%p").lower()  # e.g. "8:00am"

    if delta_days < 0:
        abs_days = abs(delta_days)
        if abs_days == 1:
            return "overdue since yesterday ⚠️"
        return f"overdue — {abs_days} days ago ⚠️"
    if delta_days == 0:
        return f"due today at {time_str}"
    if delta_days == 1:
        return f"due tomorrow at {time_str}"
    if delta_days <= 6:
        day_name = dt_local.strftime("%A")
        return f"due {day_name} at {time_str} ({delta_days} days)"
    return f"due {dt_local.strftime('%-d %b')} at {time_str}"


def _truncate_preview(text: str, limit: int = 90) -> str:
    """Collapse whitespace and cap one-line previews for digest messages."""
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: max(limit - 3, 1)].rstrip() + "..."


async def _send_to_users(ctx: dict, message: str) -> None:
    """Send a message to all allowed Telegram users via the bot in ctx."""
    bot: Bot | None = ctx.get("bot")
    if not bot:
        raise ConfigError("Telegram bot is not available for scheduled delivery.")
    settings = ctx.get("settings")
    if not settings:
        raise ConfigError("Worker settings are not available for scheduled delivery.")

    chunks = _split_message(message, _TELEGRAM_MAX_LENGTH)
    for uid in settings.allowed_user_ids:
        for chunk in chunks:
            try:
                await bot.send_message(uid, chunk)
            except TelegramAPIError:
                logger.exception("telegram_send_failed", user_id=uid)


async def _get_calendar_section(settings) -> str:
    """Fetch today's calendar events and format as a briefing section."""
    if not settings.google_configured:
        logger.debug("calendar_not_configured_for_briefing")
        return ""

    try:
        from src.app.agents.tools.calendar import CalendarEvent, CalendarService

        calendar = CalendarService(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret.get_secret_value(),
            refresh_token=settings.google_refresh_token.get_secret_value(),
        )

        try:
            events = await calendar.get_upcoming_events(days=1, max_results=20)
        finally:
            await calendar.close()

        if not events:
            return ""

        # Filter to today's events only. Timed events should use their own timezone,
        # while all-day date events are already expressed as calendar-local dates.
        todays_events: list[CalendarEvent] = []
        for ev in events:
            if isinstance(ev.start, datetime):
                event_timezone = ev.start.tzinfo or UTC
                target_date = datetime.now(event_timezone).date()
                ev_date = ev.start.astimezone(event_timezone).date()
            else:
                target_date = date.today()
                ev_date = ev.start
            if ev_date == target_date:
                todays_events.append(ev)

        if not todays_events:
            return ""

        lines = [f"TODAY'S SCHEDULE ({len(todays_events)} events):"]
        for ev in todays_events:
            if isinstance(ev.start, datetime):
                time_str = ev.start.strftime("%H:%M")
                end_str = ev.end.strftime("%H:%M") if isinstance(ev.end, datetime) else ""
                time_range = f"{time_str}-{end_str}" if end_str else time_str
            else:
                time_range = "All day"

            location_str = f" @ {ev.location}" if ev.location else ""
            lines.append(f"  - [{time_range}] {ev.summary}{location_str}")

        lines.append("")
        return "\n".join(lines)

    except Exception as exc:
        logger.exception("calendar_briefing_failed")
        raise RuntimeError(f"calendar briefing failed: {exc}") from exc


async def _get_curated_content_section(ctx: dict) -> str:
    """Retrieve the latest curated content digest for the morning briefing.

    Returns empty string only when no digest is stored.
    """
    from src.app.workers.curation import get_latest_digest

    return await get_latest_digest(ctx)


async def morning_briefing(ctx: dict) -> None:
    """Generate and send morning briefing (8am daily).

    Contents: calendar events, deadlines, commitments, mood continuity, project status,
    curated content digest.
    """
    logger.info("morning_briefing_started")

    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    if not session_factory:
        logger.error("morning_briefing_no_session_factory")
        return

    settings = ctx.get("settings")

    now = datetime.now(tz=UTC)

    # Resolve user timezone for human-readable deadline formatting.
    # str() guards against test MagicMock objects which would fail ZoneInfo validation.
    try:
        tz_raw = getattr(settings, "user_timezone", None)
        tz_str = str(tz_raw) if tz_raw and isinstance(tz_raw, str) else "Europe/London"
        user_tz = ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, ValueError):
        user_tz = ZoneInfo("UTC")

    async with session_factory() as session:
        # Overdue commitments
        overdue_result = await session.execute(
            text("""
                SELECT id, normalized_action, temporal_normalized
                FROM commitments
                WHERE status IN ('detected', 'confirmed', 'in_progress')
                  AND temporal_normalized IS NOT NULL
                  AND temporal_normalized < :now
                ORDER BY temporal_normalized ASC
                LIMIT 10
            """),
            {"now": now},
        )
        overdue = await mapping_rows(overdue_result)

        # Upcoming deadlines (next 48 hours)
        upcoming_result = await session.execute(
            text("""
                SELECT id, normalized_action, temporal_normalized
                FROM commitments
                WHERE status IN ('detected', 'confirmed', 'in_progress')
                  AND temporal_normalized IS NOT NULL
                  AND temporal_normalized > :now
                  AND temporal_normalized < :deadline
                ORDER BY temporal_normalized ASC
                LIMIT 10
            """),
            {"now": now, "deadline": now + timedelta(hours=48)},
        )
        upcoming = await mapping_rows(upcoming_result)

        # Active goals (top priorities)
        goals_result = await session.execute(
            text("""
                SELECT title, progress, status, goal_type
                FROM goals
                WHERE status = 'active'
                ORDER BY priority ASC
                LIMIT 5
            """)
        )
        top_goals = await mapping_rows(goals_result)

        # Active projects
        projects_result = await session.execute(
            text("""
                SELECT title, status, deadline
                FROM projects
                WHERE status NOT IN ('completed', 'cancelled', 'archived')
                ORDER BY deadline ASC NULLS LAST
                LIMIT 5
            """)
        )
        active_projects = await mapping_rows(projects_result)

        # Habit streaks
        habits_result = await session.execute(
            text("""
                SELECT name, current_streak, longest_streak, frequency,
                       frequency_days, last_completed_at
                FROM habits
                WHERE active = TRUE
                ORDER BY name ASC
            """)
        )
        active_habits = await mapping_rows(habits_result)

        day_plan = None
        carry_over_tasks: list[str] = []
        if settings:
            planning_owner_id = planning_owner_user_id(settings)
            source_date = planning_source_date(settings)
            day_plan = await load_latest_day_plan(
                session,
                user_id=planning_owner_id,
                source_date=source_date,
            )
            if day_plan is None:
                carry_over_tasks = await load_carry_over_tasks(
                    session,
                    user_id=planning_owner_id,
                    source_date=source_date,
                )
        else:
            carry_over_tasks = []

    # Format briefing
    lines = ["Good morning! Here is your daily briefing.\n"]

    # Calendar section — goes at the TOP before overdue items
    if settings:
        calendar_section = await _get_calendar_section(settings)
        if calendar_section:
            lines.append(calendar_section)

    if overdue:
        lines.append(f"OVERDUE ({len(overdue)}):")
        for c in overdue:
            dl = _human_deadline(c["temporal_normalized"], now, user_tz)
            lines.append(f"  - {c['normalized_action']} — {dl}")
        lines.append("")

    if upcoming:
        lines.append(f"UPCOMING DEADLINES ({len(upcoming)}):")
        for c in upcoming:
            dl = _human_deadline(c["temporal_normalized"], now, user_tz)
            lines.append(f"  - {c['normalized_action']} — {dl}")
        lines.append("")

    if top_goals:
        lines.append("TOP GOALS:")
        for g in top_goals:
            pct = int((g["progress"] or 0) * 100)
            lines.append(f"  - {g['title']} ({pct}% complete)")
        lines.append("")

    if active_projects:
        lines.append("ACTIVE PROJECTS:")
        for p in active_projects:
            if p["deadline"]:
                dl = _human_deadline(p["deadline"], now, user_tz)
                deadline_str = f" — {dl}"
            else:
                deadline_str = ""
            lines.append(f"  - {p['title']} [{p['status']}]{deadline_str}")
        lines.append("")

    if active_habits:
        lines.append("HABIT STREAKS:")
        for h in active_habits:
            streak = h["current_streak"]
            best = h["longest_streak"]
            freq = h["frequency"]
            streak_str = f"{streak} day{'s' if streak != 1 else ''}"
            best_str = f"best: {best}" if best > 0 else ""
            suffix = f" ({best_str})" if best_str else ""
            lines.append(f"  - {h['name']}: {streak_str} streak [{freq}]{suffix}")
        lines.append("")

    if day_plan is not None:
        lines.append(build_day_plan_section(day_plan.plan))
        lines.append("")
    else:
        lines.append(build_morning_plan_prompt(carry_over_tasks=carry_over_tasks))
        lines.append("")

    if not any([overdue, upcoming, top_goals, active_projects, active_habits]):
        lines.append("Nothing urgent today. Have a great day!")

    # Flush pending P2 + P3 notifications into morning digest
    fatigue = get_fatigue_manager()
    morning_notifications = await fatigue.flush_morning_digest()
    if morning_notifications:
        digest_text = fatigue.format_digest(morning_notifications)
        lines.append("")
        lines.append(digest_text)
        logger.info(
            "morning_digest_appended",
            notification_count=len(morning_notifications),
        )

    # Curated content digest — added after notifications
    curated_section = await _get_curated_content_section(ctx)
    if curated_section:
        lines.append("")
        lines.append(curated_section)
        logger.info("curated_content_appended")

    briefing = "\n".join(lines)
    logger.info("morning_briefing_generated", length=len(briefing))

    await _send_to_users(ctx, briefing)

    if settings and day_plan is None:
        try:
            conv_ctx = ConversationContext(redis_url=settings.redis_url.get_secret_value())
            await conv_ctx.set_pending_planning_session(
                planning_owner_user_id(settings),
                build_morning_planning_session(settings=settings),
            )
        except Exception:
            logger.warning("morning_planning_session_seed_failed", exc_info=True)
    logger.info("morning_briefing_completed")


async def weekly_review(ctx: dict) -> None:
    """Generate weekly review (Sunday 7pm).

    Contents: episode synthesis, goal progress, mood trends, habit streaks,
    open commitments, project health.
    """
    logger.info("weekly_review_started")

    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    settings = ctx.get("settings")

    if not session_factory:
        logger.error("weekly_review_no_session_factory")
        return

    if not settings:
        logger.error("weekly_review_no_settings")
        return

    now = datetime.now(tz=UTC)
    week_start = now - timedelta(days=7)

    async with session_factory() as session:
        # Week's episodes
        episodes_result = await session.execute(
            text("""
                SELECT id, summary, episode_type, mood_score, energy_rating, created_at
                FROM episodes
                WHERE created_at >= :start AND created_at < :end
                ORDER BY created_at ASC
            """),
            {"start": week_start, "end": now},
        )
        week_episodes = await mapping_rows(episodes_result)

        # Goal progress
        goals_result = await session.execute(
            text("""
                SELECT title, progress, status, goal_type, updated_at
                FROM goals
                WHERE status NOT IN ('cancelled')
                ORDER BY priority ASC
            """)
        )
        all_goals = await mapping_rows(goals_result)

        # Open commitments
        commitments_result = await session.execute(
            text("""
                SELECT normalized_action, status, temporal_normalized, created_at
                FROM commitments
                WHERE status NOT IN ('completed', 'cancelled')
                ORDER BY created_at DESC
                LIMIT 20
            """)
        )
        open_commitments = await mapping_rows(commitments_result)

        # Project health
        projects_result = await session.execute(
            text("""
                SELECT title, status, deadline
                FROM projects
                WHERE status NOT IN ('completed', 'cancelled', 'archived')
            """)
        )
        active_projects = await mapping_rows(projects_result)

        # Decisions due for review
        decisions_result = await session.execute(
            text("""
                SELECT id, title, decision_made, expected_outcome, review_date, created_at
                FROM decisions
                WHERE status = 'pending_review'
                  AND review_date IS NOT NULL
                  AND review_date <= :now
                ORDER BY review_date ASC
                LIMIT 20
            """),
            {"now": now},
        )
        decisions_due = await mapping_rows(decisions_result)

    # Aggregate week data as text for the review agent
    week_data_lines = [f"Week of {week_start.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}\n"]
    week_data_lines.append(f"Total captures: {len(week_episodes)}")

    avg_mood = average_metric(week_episodes, "mood_score")
    if avg_mood is not None:
        week_data_lines.append(f"Average mood: {avg_mood:.1f}")
    week_data_lines.append("")

    week_data_lines.append("Goals:")
    for g in all_goals:
        pct = int((g["progress"] or 0) * 100)
        week_data_lines.append(f"  - {g['title']}: {pct}% ({g['status']})")
    week_data_lines.append("")

    week_data_lines.append("Open commitments:")
    for c in open_commitments:
        week_data_lines.append(f"  - {c['normalized_action']} [{c['status']}]")
    week_data_lines.append("")

    week_data_lines.append("Active projects:")
    for p in active_projects:
        week_data_lines.append(f"  - {p['title']} [{p['status']}]")

    if decisions_due:
        week_data_lines.append("")
        week_data_lines.append(f"Decisions due for review ({len(decisions_due)}):")
        for d in decisions_due:
            week_data_lines.append(
                f'  - {d["title"]}: "{d["decision_made"]}" '
                f"(expected: {d['expected_outcome'] or 'N/A'}, review due: {d['review_date']})"
            )

    week_data = "\n".join(week_data_lines)

    # Call the review agent to generate the weekly review
    review_text: str | None = None
    try:
        from anthropic import AsyncAnthropic

        from src.app.agents.specialists.review import generate_weekly_review

        client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
        review = await generate_weekly_review(week_data, client)
        logger.info(
            "weekly_review_generated",
            key_insight_length=len(review.key_insight),
            accomplishments=len(review.accomplishments),
            recommendations=len(review.recommendations),
        )

        # Format review for Telegram
        week_str = week_start.strftime("%Y-%m-%d")
        now_str = now.strftime("%Y-%m-%d")
        review_lines = [f"Weekly Review: {week_str} — {now_str}\n"]
        review_lines.append(f"Key Insight: {review.key_insight}\n")
        if review.accomplishments:
            review_lines.append("Accomplishments:")
            for a in review.accomplishments:
                review_lines.append(f"  - {a}")
            review_lines.append("")
        if review.recommendations:
            review_lines.append("Recommendations:")
            for r in review.recommendations:
                review_lines.append(f"  - {r}")
        review_text = "\n".join(review_lines)
    except (APIError, LLMError):
        logger.exception("weekly_review_generation_failed")
        review_text = f"Weekly review generation failed. Raw data:\n\n{week_data}"

    if review_text:
        await _send_to_users(ctx, review_text)
    logger.info("weekly_review_completed")


async def monthly_review(ctx: dict) -> None:
    """Generate monthly review (1st of each month).

    Aggregates the past month's data: episodes, mood/energy, goals, habits,
    commitments. Calls the review agent (Opus) for synthesis.
    """
    logger.info("monthly_review_started")

    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    settings = ctx.get("settings")

    if not session_factory or not settings:
        logger.error("monthly_review_missing_context")
        return

    now = datetime.now(tz=UTC)
    month_start = now - timedelta(days=30)

    async with session_factory() as session:
        episodes_result = await session.execute(
            text("""
                SELECT summary, mood_score, energy_rating, tags, created_at
                FROM episodes
                WHERE created_at >= :start AND created_at < :end
                ORDER BY created_at ASC
            """),
            {"start": month_start, "end": now},
        )
        month_episodes = await mapping_rows(episodes_result)

        goals_result = await session.execute(
            text("""
                SELECT title, progress, status, goal_type
                FROM goals WHERE status NOT IN ('cancelled')
                ORDER BY priority ASC
            """)
        )
        all_goals = await mapping_rows(goals_result)

        habits_result = await session.execute(
            text("""
                SELECT name, current_streak, longest_streak,
                       total_completions, frequency
                FROM habits WHERE active = TRUE
                ORDER BY name ASC
            """)
        )
        active_habits = await mapping_rows(habits_result)

    # Build month data text
    month_str = month_start.strftime("%B %Y")
    lines = [f"Monthly Review: {month_str}\n"]
    lines.append(f"Total captures: {len(month_episodes)}")

    avg_mood = average_metric(month_episodes, "mood_score")
    if avg_mood is not None:
        lines.append(f"Average mood: {avg_mood:.1f}")
    lines.append("")

    lines.append("Goals:")
    for g in all_goals:
        pct = int((g["progress"] or 0) * 100)
        lines.append(f"  - {g['title']}: {pct}% ({g['status']})")
    lines.append("")

    lines.append("Habits:")
    for h in active_habits:
        lines.append(
            f"  - {h['name']}: streak={h['current_streak']}, "
            f"best={h['longest_streak']}, total={h['total_completions']}"
        )

    month_data = "\n".join(lines)

    review_text: str | None = None
    try:
        from anthropic import AsyncAnthropic

        from src.app.agents.specialists.review import generate_monthly_review

        client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
        )
        review = await generate_monthly_review(month_data, client)
        logger.info(
            "monthly_review_generated",
            key_insight_length=len(review.key_insight),
        )

        review_lines = [f"Monthly Review: {month_str}\n"]
        review_lines.append(f"Key Insight: {review.key_insight}\n")
        if review.accomplishments:
            review_lines.append("Accomplishments:")
            for a in review.accomplishments:
                review_lines.append(f"  - {a}")
            review_lines.append("")
        if review.recommendations:
            review_lines.append("Recommendations:")
            for r in review.recommendations:
                review_lines.append(f"  - {r}")
        review_text = "\n".join(review_lines)
    except (APIError, LLMError):
        logger.exception("monthly_review_generation_failed")
        review_text = f"Monthly review generation failed. Raw data:\n\n{month_data}"

    if review_text:
        await _send_to_users(ctx, review_text)
    logger.info("monthly_review_completed")


async def quarterly_review(ctx: dict) -> None:
    """Generate quarterly review (1st of Jan, Apr, Jul, Oct).

    Aggregates 3 months of data for strategic review.
    """
    logger.info("quarterly_review_started")

    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    settings = ctx.get("settings")

    if not session_factory or not settings:
        logger.error("quarterly_review_missing_context")
        return

    now = datetime.now(tz=UTC)
    quarter_start = now - timedelta(days=90)

    async with session_factory() as session:
        episodes_result = await session.execute(
            text("""
                SELECT summary, mood_score, energy_rating, created_at
                FROM episodes
                WHERE created_at >= :start AND created_at < :end
                ORDER BY created_at ASC
            """),
            {"start": quarter_start, "end": now},
        )
        quarter_episodes = await mapping_rows(episodes_result)

        goals_result = await session.execute(
            text("""
                SELECT title, progress, status, goal_type
                FROM goals ORDER BY priority ASC
            """)
        )
        all_goals = await mapping_rows(goals_result)

        decisions_result = await session.execute(
            text("""
                SELECT title, decision_made, actual_outcome, outcome_rating,
                       created_at
                FROM decisions
                WHERE created_at >= :start
                ORDER BY created_at ASC
            """),
            {"start": quarter_start},
        )
        quarter_decisions = await mapping_rows(decisions_result)

        contacts_result = await session.execute(
            text("""
                SELECT first_name, last_name, relationship_score,
                       last_interaction_at
                FROM contacts
                ORDER BY relationship_score DESC
                LIMIT 20
            """)
        )
        top_contacts = await mapping_rows(contacts_result)

    q_str = quarter_start.strftime("%B") + " — " + now.strftime("%B %Y")
    lines = [f"Quarterly Review: {q_str}\n"]
    lines.append(f"Total captures: {len(quarter_episodes)}")
    avg_mood = average_metric(quarter_episodes, "mood_score")
    if avg_mood is not None:
        lines.append(f"Average mood: {avg_mood:.1f}")
    lines.append("")

    lines.append("Goals:")
    for g in all_goals:
        pct = int((g["progress"] or 0) * 100)
        lines.append(f"  - {g['title']}: {pct}% ({g['status']})")
    lines.append("")

    if quarter_decisions:
        lines.append("Decisions this quarter:")
        for d in quarter_decisions:
            outcome = d.get("actual_outcome") or "pending"
            lines.append(f"  - {d['title']}: {outcome}")
        lines.append("")

    lines.append("Key relationships:")
    for c in top_contacts:
        name = f"{c['first_name']} {c['last_name'] or ''}".strip()
        lines.append(f"  - {name} (score: {c['relationship_score']})")

    quarter_data = "\n".join(lines)

    review_text: str | None = None
    try:
        from anthropic import AsyncAnthropic

        from src.app.agents.specialists.review import generate_quarterly_review

        client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
        )
        review = await generate_quarterly_review(quarter_data, client)
        logger.info(
            "quarterly_review_generated",
            key_insight_length=len(review.key_insight),
        )

        review_lines = [f"Quarterly Review: {q_str}\n"]
        review_lines.append(f"Key Insight: {review.key_insight}\n")
        if review.lessons_learned:
            review_lines.append("Lessons Learned:")
            for lesson in review.lessons_learned:
                review_lines.append(f"  - {lesson}")
            review_lines.append("")
        if review.next_quarter_priorities:
            review_lines.append("Next Quarter Priorities:")
            for p in review.next_quarter_priorities:
                review_lines.append(f"  - {p}")
        review_text = "\n".join(review_lines)
    except (APIError, LLMError):
        logger.exception("quarterly_review_generation_failed")
        review_text = f"Quarterly review generation failed. Raw data:\n\n{quarter_data}"

    if review_text:
        await _send_to_users(ctx, review_text)
    logger.info("quarterly_review_completed")


async def annual_review(ctx: dict) -> None:
    """Generate annual review (January 1st).

    Aggregates a full year of data for life-level reflection.
    """
    logger.info("annual_review_started")

    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    settings = ctx.get("settings")

    if not session_factory or not settings:
        logger.error("annual_review_missing_context")
        return

    now = datetime.now(tz=UTC)
    year_start = now - timedelta(days=365)

    async with session_factory() as session:
        episodes_result = await session.execute(
            text("""
                SELECT COUNT(*) as cnt,
                       AVG(mood_score) as avg_mood,
                       AVG(energy_rating) as avg_energy
                FROM episodes
                WHERE created_at >= :start
            """),
            {"start": year_start},
        )
        year_stats = episodes_result.mappings().one()

        goals_result = await session.execute(
            text("""
                SELECT title, progress, status, goal_type
                FROM goals ORDER BY priority ASC
            """)
        )
        all_goals = await mapping_rows(goals_result)

        decisions_result = await session.execute(
            text("""
                SELECT title, decision_made, actual_outcome,
                       outcome_rating, created_at
                FROM decisions
                WHERE created_at >= :start
                ORDER BY created_at ASC
            """),
            {"start": year_start},
        )
        year_decisions = await mapping_rows(decisions_result)

        reviews_result = await session.execute(
            text("""
                SELECT review_type, period, content, created_at
                FROM reviews
                WHERE created_at >= :start
                ORDER BY created_at ASC
            """),
            {"start": year_start},
        )
        year_reviews = await mapping_rows(reviews_result)

    year_str = str(now.year)
    lines = [f"Annual Review: {year_str}\n"]
    lines.append(f"Total captures: {year_stats['cnt']}")
    if year_stats["avg_mood"]:
        lines.append(f"Average mood: {year_stats['avg_mood']:.1f}")
    lines.append("")

    lines.append("Goals:")
    for g in all_goals:
        pct = int((g["progress"] or 0) * 100)
        lines.append(f"  - {g['title']}: {pct}% ({g['status']})")
    lines.append("")

    if year_decisions:
        lines.append(f"Decisions this year ({len(year_decisions)}):")
        for d in year_decisions[:10]:
            outcome = d.get("actual_outcome") or "pending"
            rating = d.get("outcome_rating") or "N/A"
            lines.append(f"  - {d['title']}: {outcome} (rating: {rating})")
        lines.append("")

    if year_reviews:
        lines.append(f"Reviews generated: {len(year_reviews)}")

    year_data = "\n".join(lines)

    review_text: str | None = None
    try:
        from anthropic import AsyncAnthropic

        from src.app.agents.specialists.review import generate_annual_review

        client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
        )
        review = await generate_annual_review(year_data, client)
        logger.info(
            "annual_review_generated",
            key_insight_length=len(review.key_insight),
        )

        review_lines = [f"Annual Review: {year_str}\n"]
        if review.year_theme:
            review_lines.append(f"Theme: {review.year_theme}\n")
        review_lines.append(f"Key Insight: {review.key_insight}\n")
        if review.lessons_learned:
            review_lines.append("Lessons Learned:")
            for lesson in review.lessons_learned:
                review_lines.append(f"  - {lesson}")
            review_lines.append("")
        if review.next_year_vision:
            review_lines.append("Next Year Vision:")
            for v in review.next_year_vision:
                review_lines.append(f"  - {v}")
        review_text = "\n".join(review_lines)
    except (APIError, LLMError):
        logger.exception("annual_review_generation_failed")
        review_text = f"Annual review generation failed. Raw data:\n\n{year_data}"

    if review_text:
        await _send_to_users(ctx, review_text)
    logger.info("annual_review_completed")
