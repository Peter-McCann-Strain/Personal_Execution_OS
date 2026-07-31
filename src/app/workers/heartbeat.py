"""Heartbeat daemon — runs every 30 minutes.

Checks stale goals, upcoming deadlines, overdue commitments, relationship decay.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.app.agents.specialists.notification import Notification, Priority
from src.app.core.async_utils import mapping_rows
from src.app.workers.agent_tasks import get_fatigue_manager

logger = structlog.get_logger()


async def run_heartbeat(ctx: dict) -> None:
    """Main heartbeat — runs all periodic checks."""
    logger.info("heartbeat_started")

    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    if session_factory is None:
        logger.error("heartbeat_no_session_factory")
        return

    settings = ctx.get("settings")
    async with session_factory() as session:
        checks: list[tuple[str, object]] = [
            ("stale_goals", check_stale_goals),
            ("upcoming_deadlines", check_upcoming_deadlines),
            ("overdue_commitments", check_overdue_commitments),
            ("decisions_due_review", check_decisions_due_review),
            ("habit_streaks", check_habit_streaks),
        ]
        if settings is not None and bool(getattr(settings, "llm_configured", False)):
            checks.append(("relationship_decay", check_relationship_decay))
        else:
            logger.info("heartbeat_relationship_nudges_skipped_model_provider_disabled")

        for name, check_fn in checks:
            try:
                await check_fn(session)
            except Exception:
                logger.exception("heartbeat_check_failed", check=name)

    # Ping healthchecks.io if configured
    if settings:
        await ping_healthcheck(settings)

    logger.info("heartbeat_completed")


async def check_stale_goals(session: AsyncSession) -> None:
    """Flag goals with no progress in 7+ days."""
    logger.info("checking_stale_goals")

    result = await session.execute(
        text("""
            SELECT id, title, status, progress, updated_at
            FROM goals
            WHERE status NOT IN ('completed', 'cancelled')
              AND updated_at < NOW() - INTERVAL '7 days'
            ORDER BY updated_at ASC
        """)
    )
    stale_goals = await mapping_rows(result)

    for goal in stale_goals:
        logger.warning(
            "stale_goal_detected",
            goal_id=str(goal["id"]),
            status=goal["status"],
            progress=goal["progress"],
            last_updated=str(goal["updated_at"]),
        )

    logger.info("stale_goals_check_complete", stale_count=len(stale_goals))


async def check_upcoming_deadlines(session: AsyncSession) -> None:
    """Alert on deadlines within 48 hours."""
    logger.info("checking_upcoming_deadlines")

    # Check commitments with temporal_normalized within 48 hours
    commitment_result = await session.execute(
        text("""
            SELECT id, verbatim_text, normalized_action,
                   temporal_normalized, status
            FROM commitments
            WHERE status IN ('detected', 'confirmed', 'in_progress')
              AND temporal_normalized IS NOT NULL
              AND temporal_normalized > NOW()
              AND temporal_normalized < NOW() + INTERVAL '48 hours'
            ORDER BY temporal_normalized ASC
        """)
    )
    upcoming_commitments = await mapping_rows(commitment_result)

    for c in upcoming_commitments:
        logger.warning(
            "upcoming_commitment_deadline",
            commitment_id=str(c["id"]),
            deadline=str(c["temporal_normalized"]),
        )

    # Check projects with deadlines within 48 hours
    project_result = await session.execute(
        text("""
            SELECT id, title, deadline, status
            FROM projects
            WHERE status NOT IN ('completed', 'cancelled', 'archived')
              AND deadline IS NOT NULL
              AND deadline > NOW()
              AND deadline < NOW() + INTERVAL '48 hours'
            ORDER BY deadline ASC
        """)
    )
    upcoming_projects = await mapping_rows(project_result)

    for p in upcoming_projects:
        logger.warning(
            "upcoming_project_deadline",
            project_id=str(p["id"]),
            deadline=str(p["deadline"]),
        )

    logger.info(
        "upcoming_deadlines_check_complete",
        commitment_count=len(upcoming_commitments),
        project_count=len(upcoming_projects),
    )


async def check_overdue_commitments(session: AsyncSession) -> None:
    """Remind about overdue commitments."""
    logger.info("checking_overdue_commitments")

    result = await session.execute(
        text("""
            SELECT id, verbatim_text, normalized_action,
                   temporal_normalized, status, created_at
            FROM commitments
            WHERE status IN ('detected', 'confirmed', 'in_progress')
              AND temporal_normalized IS NOT NULL
              AND temporal_normalized < NOW()
            ORDER BY temporal_normalized ASC
        """)
    )
    overdue = await mapping_rows(result)

    for c in overdue:
        logger.warning(
            "overdue_commitment",
            commitment_id=str(c["id"]),
            was_due=str(c["temporal_normalized"]),
            status=c["status"],
        )

    logger.info("overdue_commitments_check_complete", overdue_count=len(overdue))


async def check_relationship_decay(session: AsyncSession) -> None:
    """Check for contacts whose last interaction is overdue by their expected frequency.

    Queries contacts with recent interaction context and uses Haiku to generate
    personalised reconnection nudges.
    """
    logger.info("checking_relationship_decay")

    result = await session.execute(
        text("""
            SELECT c.id, c.first_name, c.last_name,
                   c.interaction_frequency_days,
                   c.last_interaction_at, c.relationship_score,
                   c.how_we_met, c.tags
            FROM contacts c
            WHERE c.interaction_frequency_days IS NOT NULL
              AND c.last_interaction_at IS NOT NULL
              AND c.last_interaction_at < NOW()
                  - (c.interaction_frequency_days || ' days')::interval
            ORDER BY c.last_interaction_at ASC
            LIMIT 20
        """)
    )
    decayed_contacts = await mapping_rows(result)

    if not decayed_contacts:
        logger.info("relationship_decay_check_complete", decayed_count=0)
        return

    fatigue = get_fatigue_manager()

    for contact in decayed_contacts:
        first = contact["first_name"]
        last = contact["last_name"] or ""
        full_name = f"{first} {last}".strip()
        freq = contact["interaction_frequency_days"]
        last_at = contact["last_interaction_at"]

        now = datetime.now(tz=UTC)
        days_since = (now - last_at).days if last_at else 0
        days_overdue = days_since - freq if freq else 0

        # Fetch recent interaction context for richer nudges
        interaction_ctx = await _get_interaction_context(
            session,
            contact["id"],
        )

        message = await _generate_nudge(
            full_name=full_name,
            days_since=days_since,
            days_overdue=days_overdue,
            frequency=freq,
            how_we_met=contact.get("how_we_met"),
            tags=contact.get("tags"),
            interaction_context=interaction_ctx,
        )

        notification = Notification(
            message=message,
            priority=Priority.P2_NORMAL,
            category="relationship",
        )

        await fatigue.evaluate(notification)

        logger.info(
            "relationship_decay_detected",
            contact_id=str(contact["id"]),
            days_since=days_since,
            days_overdue=days_overdue,
            frequency=freq,
        )

    logger.info(
        "relationship_decay_check_complete",
        decayed_count=len(decayed_contacts),
    )


async def _get_interaction_context(
    session: AsyncSession,
    contact_id: uuid.UUID,
) -> str:
    """Fetch the last 3 interactions for context."""
    result = await session.execute(
        text("""
            SELECT summary, topics, interaction_at
            FROM interactions
            WHERE contact_id = :cid
            ORDER BY interaction_at DESC NULLS LAST
            LIMIT 3
        """),
        {"cid": contact_id},
    )
    rows = await mapping_rows(result)
    if not rows:
        return ""
    lines = []
    for r in rows:
        date_str = str(r["interaction_at"])[:10] if r["interaction_at"] else "?"
        summary = r["summary"] or "no summary"
        topics = ", ".join(r["topics"]) if r.get("topics") else ""
        suffix = f" [{topics}]" if topics else ""
        lines.append(f"  {date_str}: {summary}{suffix}")
    return "\n".join(lines)


async def _generate_nudge(
    *,
    full_name: str,
    days_since: int,
    days_overdue: int,
    frequency: int,
    how_we_met: str | None,
    tags: list[str] | None,
    interaction_context: str,
) -> str:
    """Generate a personalised reconnection nudge via Haiku."""
    from anthropic import AsyncAnthropic

    from src.app.config import get_settings
    from src.app.core.llm_helpers import call_and_extract_text

    settings = get_settings()
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
    )

    context_parts = [
        f"Contact: {full_name}",
        f"Days since last contact: {days_since}",
        f"Expected frequency: every {frequency} days",
    ]
    if how_we_met:
        context_parts.append(f"How you met: {how_we_met}")
    if tags:
        context_parts.append(f"Tags: {', '.join(tags)}")
    if interaction_context:
        context_parts.append(f"Recent interactions:\n{interaction_context}")

    message = await call_and_extract_text(
        client,
        model=settings.classifier_model,
        max_tokens=settings.nudge_max_tokens,
        system=(
            "Generate a brief, warm reconnection nudge (1-2 sentences). "
            "Suggest a specific action based on the relationship context. "
            "Be concise and personal, not generic."
        ),
        messages=[
            {
                "role": "user",
                "content": "\n".join(context_parts),
            }
        ],
        error_context="relationship_nudge",
        inject_personality=False,
    )
    return message.strip()


async def check_decisions_due_review(session: AsyncSession) -> None:
    """Check for decisions past their review_date that are still pending review.

    Generates P2 notifications for each decision due, queued via FatigueManager
    for batch delivery in morning/evening digests.
    """
    logger.info("checking_decisions_due_review")

    result = await session.execute(
        text("""
            SELECT id, title, decision_made, expected_outcome, review_date
            FROM decisions
            WHERE status = 'pending_review'
              AND review_date IS NOT NULL
              AND review_date <= NOW()
            ORDER BY review_date ASC
            LIMIT 20
        """)
    )
    decisions_due = await mapping_rows(result)

    if not decisions_due:
        logger.info("decisions_due_review_check_complete", due_count=0)
        return

    fatigue = get_fatigue_manager()

    for decision in decisions_due:
        title = decision["title"]
        review_date = decision["review_date"]

        message = (
            f'Decision due for review: "{title}". '
            f'You decided: "{decision["decision_made"]}". '
            f"Review was due {review_date}. "
            f"How did it turn out?"
        )

        notification = Notification(
            message=message,
            priority=Priority.P2_NORMAL,
            category="decision_review",
        )

        await fatigue.evaluate(notification)

        logger.info(
            "decision_due_review_detected",
            decision_id=str(decision["id"]),
            review_date=str(review_date),
        )

    logger.info(
        "decisions_due_review_check_complete",
        due_count=len(decisions_due),
    )


async def check_habit_streaks(session: AsyncSession) -> None:
    """Check for habits whose streaks have been broken and create notifications.

    Queries active habits with a non-zero streak that have not been completed
    within their frequency window. Resets the streak and generates P2
    notifications via FatigueManager for batch delivery.
    """
    logger.info("checking_habit_streaks")

    from src.app.persistence.repositories.habits import check_broken_streaks, reset_streak

    broken_habits = await check_broken_streaks(session)

    if not broken_habits:
        logger.info("habit_streaks_check_complete", broken_count=0)
        return

    fatigue = get_fatigue_manager()

    for habit in broken_habits:
        old_streak = habit.current_streak

        # Reset the streak
        await reset_streak(session, habit.id)
        await session.commit()

        message = (
            f"Your streak for '{habit.name}' has been broken after {old_streak} completions. "
            f"Longest streak: {habit.longest_streak}. Time to restart!"
        )

        notification = Notification(
            message=message,
            priority=Priority.P2_NORMAL,
            category="habit",
        )

        await fatigue.evaluate(notification)

        logger.info(
            "habit_streak_broken",
            habit_id=str(habit.id),
            old_streak=old_streak,
            longest_streak=habit.longest_streak,
        )

    logger.info("habit_streaks_check_complete", broken_count=len(broken_habits))


async def ping_healthcheck(settings) -> None:
    """Ping Healthchecks.io dead-man's switch."""
    import httpx

    healthcheck_url = getattr(settings, "healthchecks_heartbeat_url", None)
    if not healthcheck_url:
        return

    try:
        async with httpx.AsyncClient() as client:
            await client.get(healthcheck_url, timeout=5.0)
        logger.info("healthcheck_pinged")
    except httpx.HTTPError:
        logger.warning("healthcheck_ping_failed")
