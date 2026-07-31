"""Review handler — weekly and quarterly reviews.

Includes spaced repetition: surfaces notes/episodes due for review
using the SM-2 algorithm so the user is reminded of important insights.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.specialists.review import generate_weekly_review
from src.app.core.analytics import average_metric
from src.app.core.async_utils import maybe_await
from src.app.core.exceptions import DatabaseError
from src.app.domain.models import ChatResponse, Intent, MessageInput
from src.app.domain.services.handlers._common import enqueue_entity_extraction
from src.app.second_brain.spaced_repetition import calculate_next_review

logger = structlog.get_logger()


async def _mapping_rows(result: object) -> list[dict]:
    """Read SQLAlchemy mapping rows while tolerating AsyncMock-based test doubles."""
    mappings = await maybe_await(result.mappings())
    rows = await maybe_await(mappings.all())
    return list(rows)


async def handle_review(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    _intent: Intent,
) -> ChatResponse:
    """Handle review requests by aggregating data and generating a review."""
    # Aggregate the last 7 days of data for the review
    week_data = await _aggregate_week_data(session)

    review = await generate_weekly_review(week_data, client)

    # --- Spaced repetition: surface items due for review ---
    due_items = await _get_spaced_repetition_items(session)

    # Format the review
    lines = [f"# Weekly Review: {review.period}\n"]

    if review.key_insight:
        lines.append(f"**Key Insight:** {review.key_insight}\n")

    if review.mood_summary:
        lines.append(f"**Mood:** {review.mood_summary}")
        if review.average_mood is not None:
            lines.append(f"Average: {review.average_mood:.1f}/10")
        lines.append("")

    if review.accomplishments:
        lines.append("**Accomplishments:**")
        for a in review.accomplishments:
            lines.append(f"- {a}")
        lines.append("")

    if review.patterns_noticed:
        lines.append("**Patterns Noticed:**")
        for p in review.patterns_noticed:
            lines.append(f"- {p.pattern}")
        lines.append("")

    if review.open_commitments:
        lines.append(f"**Open Commitments ({len(review.open_commitments)}):**")
        for c in review.open_commitments:
            action = c.get("action", c.get("normalized_action", str(c)))
            lines.append(f"- {action}")
        lines.append("")

    if due_items:
        lines.append(f"**Due for Review ({len(due_items)}):**")
        for item in due_items:
            summary = item.get("summary") or item.get("content", "")[:80]
            lines.append(f"- {summary}")
        lines.append("")

    if review.recommendations:
        lines.append("**Recommendations:**")
        for r in review.recommendations:
            lines.append(f"- {r.action}")

    try:
        await enqueue_entity_extraction(
            episode_id=str(uuid.uuid4()),
            text_content="\n".join(lines),
        )
    except Exception as exc:
        logger.warning(
            "review_entity_extraction_degraded",
            error=str(exc),
            exc_info=True,
        )

    # Use LLM-generated reply as the chat message; full review stored in metadata
    user_reply = review.user_reply if isinstance(review.user_reply, str) else ""
    reply = user_reply.strip() or (
        review.key_insight or f"Weekly review for {review.period} complete. Full review below."
    )
    full_review_text = "\n".join(lines)

    return ChatResponse(
        content=reply + "\n\n" + full_review_text,
        agent="review",
        metadata={
            "period": review.period,
            "average_mood": review.average_mood,
            "accomplishment_count": len(review.accomplishments),
            "recommendation_count": len(review.recommendations),
            "spaced_repetition_due": len(due_items),
        },
    )


async def _get_spaced_repetition_items(
    session: AsyncSession,
    limit: int = 10,
) -> list[dict]:
    """Query episodes whose spaced-repetition next_review_date has passed.

    Episodes store SM-2 state in metadata->>'spaced_repetition'. Those whose
    ``next_review_date`` is in the past (or not yet set) are returned.

    For episodes without SM-2 state, we treat any episode older than 7 days
    that has a progressive summary as eligible for a first review.

    Raises when the query fails so review data loss is visible.
    """
    now = datetime.now(tz=UTC)
    first_review_cutoff = now - timedelta(days=7)

    try:
        # Episodes with SM-2 state whose review date has passed
        result = await session.execute(
            text("""
                SELECT id, summary, content, metadata
                FROM episodes
                WHERE (
                    -- Has SM-2 state and next review date has passed
                    metadata->>'spaced_repetition' IS NOT NULL
                    AND (metadata->'spaced_repetition'->>'next_review_date')::timestamptz <= :now
                )
                OR (
                    -- Has a progressive summary but no SM-2 state yet (first review)
                    metadata->>'progressive_summary' IS NOT NULL
                    AND metadata->>'spaced_repetition' IS NULL
                    AND created_at <= :first_review_cutoff
                )
                ORDER BY created_at ASC
                LIMIT :limit
            """),
            {"now": now, "first_review_cutoff": first_review_cutoff, "limit": limit},
        )
        rows = await _mapping_rows(result)

        items = []
        for row in rows:
            item = {
                "id": str(row["id"]),
                "summary": row["summary"],
                "content": row["content"],
            }
            # For items with existing SM-2 state, calculate next review interval
            # using a default quality=4 (good recall) — the user can adjust later
            meta = row.get("metadata") or {}
            sr_state = meta.get("spaced_repetition")
            if sr_state:
                item["spaced_repetition"] = calculate_next_review(
                    quality=4,
                    repetitions=sr_state.get("repetitions", 0),
                    easiness=sr_state.get("easiness", 2.5),
                    interval=sr_state.get("interval", 1),
                )
            else:
                # First review: initialise SM-2 state
                item["spaced_repetition"] = calculate_next_review(
                    quality=4,
                    repetitions=0,
                    easiness=2.5,
                    interval=1,
                )
            items.append(item)

        logger.info("spaced_repetition_items_found", count=len(items))
        return items
    except Exception as exc:
        logger.error("spaced_repetition_query_failed", exc_info=True)
        raise DatabaseError(
            f"Spaced repetition lookup failed with {type(exc).__name__}: {exc}",
        ) from exc


async def _aggregate_week_data(session: AsyncSession) -> str:
    """Aggregate the last 7 days of episodes, goals, commitments, and projects."""
    now = datetime.now(tz=UTC)
    week_start = now - timedelta(days=7)

    # Episodes from the past week
    episodes_result = await session.execute(
        text("""
            SELECT id, summary, episode_type, mood_score, energy_rating, created_at
            FROM episodes
            WHERE created_at >= :start AND created_at < :end
            ORDER BY created_at ASC
        """),
        {"start": week_start, "end": now},
    )
    week_episodes = await _mapping_rows(episodes_result)

    # Goal progress
    goals_result = await session.execute(
        text("""
            SELECT title, progress, status, goal_type
            FROM goals
            WHERE status NOT IN ('cancelled')
            ORDER BY priority ASC
        """),
    )
    all_goals = await _mapping_rows(goals_result)

    # Open commitments
    commitments_result = await session.execute(
        text("""
            SELECT normalized_action, status, temporal_normalized, created_at
            FROM commitments
            WHERE status NOT IN ('completed', 'cancelled')
            ORDER BY created_at DESC
            LIMIT 20
        """),
    )
    open_commitments = await _mapping_rows(commitments_result)

    # Active projects
    projects_result = await session.execute(
        text("""
            SELECT title, status, deadline
            FROM projects
            WHERE status NOT IN ('completed', 'cancelled', 'archived')
        """),
    )
    active_projects = await _mapping_rows(projects_result)

    # Build text representation
    lines = [
        f"Week of {week_start.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}\n",
        f"Total captures: {len(week_episodes)}",
    ]

    avg_mood = average_metric(week_episodes, "mood_score")
    if avg_mood is not None:
        lines.append(f"Average mood: {avg_mood:.1f}")

    avg_energy = average_metric(week_episodes, "energy_rating")
    if avg_energy is not None:
        lines.append(f"Average energy: {avg_energy:.1f}")
    lines.append("")

    if week_episodes:
        lines.append("Diary entries:")
        for ep in week_episodes:
            date_str = ep["created_at"].strftime("%a %H:%M") if ep["created_at"] else "?"
            summary = ep["summary"] or "(no summary)"
            mood_str = f" [mood: {ep['mood_score']:.1f}]" if ep["mood_score"] else ""
            lines.append(f"  - [{date_str}] {summary}{mood_str}")
        lines.append("")

    if all_goals:
        lines.append("Goals:")
        for g in all_goals:
            pct = int((g["progress"] or 0) * 100)
            lines.append(f"  - {g['title']}: {pct}% ({g['status']})")
        lines.append("")

    if open_commitments:
        lines.append("Open commitments:")
        for c in open_commitments:
            lines.append(f"  - {c['normalized_action']} [{c['status']}]")
        lines.append("")

    if active_projects:
        lines.append("Active projects:")
        for p in active_projects:
            deadline_str = f" (deadline: {p['deadline']})" if p["deadline"] else ""
            lines.append(f"  - {p['title']} [{p['status']}]{deadline_str}")

    return "\n".join(lines)
