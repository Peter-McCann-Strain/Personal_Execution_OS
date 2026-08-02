"""LangGraph review subgraph — weekly, monthly, quarterly, and annual review workflows.

1. Gather data from repositories (episodes, goals)
2. Generate review via Opus
3. Extract action items
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.specialists.review import generate_quarterly_review, generate_weekly_review
from src.app.domain.constants import GoalStatus
from src.app.persistence.repositories.episodes import get_episodes_by_date_range
from src.app.persistence.repositories.goals import list_goals

logger = structlog.get_logger()

# Mapping from review type to lookback days
_REVIEW_DAYS: dict[str, int] = {
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
    "annual": 365,
}


class ReviewState(BaseModel):
    """Validated review state whose explicitly set fields form node updates.

    Fields default to ``None`` so LangGraph's Pydantic update extractor does not
    overwrite prior node output with an unset model default.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    review_type: str | None = None
    data: str | None = None
    client: Any = None
    db_session: AsyncSession | None = None
    result: dict[str, Any] | None = None
    actions: list[Any] | None = None

    def __getitem__(self, key: str) -> Any:
        """Expose fields through the mapping interface used by existing nodes."""
        if key not in type(self).model_fields:
            raise KeyError(key)
        value = getattr(self, key)
        if value is None:
            raise KeyError(key)
        return value

    def get(self, key: str, default: Any = None) -> Any:
        """Return a state field or a caller-provided default."""
        if key not in type(self).model_fields:
            return default
        value = getattr(self, key)
        return default if value is None else value

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self.model_fields_set


async def gather_data_node(state: ReviewState) -> ReviewState:
    """Gather review data from the database for the relevant time period.

    Queries episodes and goals, then formats the data as a readable string
    that the LLM can use to generate its review.
    """
    db_session: AsyncSession | None = state.get("db_session")

    # If no db_session is available, fall back to any pre-supplied data string
    if db_session is None:
        logger.warning("review_gather_data_no_session", hint="using pre-supplied data")
        return ReviewState(
            data=state.get("data", ""),
            review_type=state.get("review_type", "weekly"),
        )

    review_type = state.get("review_type", "weekly")
    lookback_days = _REVIEW_DAYS.get(review_type, 7)

    now = datetime.now(tz=UTC)
    period_start = now - timedelta(days=lookback_days)

    # --- Query episodes for the period ---
    episodes = await get_episodes_by_date_range(
        db_session,
        start=period_start,
        end=now,
        limit=200,
    )

    # --- Query active goals ---
    active_goals = await list_goals(
        db_session,
        status=GoalStatus.ACTIVE,
        limit=50,
    )

    # --- Format data as a readable text block ---
    data = _format_review_data(
        review_type=review_type,
        period_start=period_start,
        period_end=now,
        episodes=episodes,
        goals=active_goals,
    )

    logger.info(
        "review_data_gathered",
        review_type=review_type,
        lookback_days=lookback_days,
        episode_count=len(episodes),
        goal_count=len(active_goals),
    )

    return ReviewState(data=data)


def _format_review_data(
    *,
    review_type: str,
    period_start: datetime,
    period_end: datetime,
    episodes: list,
    goals: list,
) -> str:
    """Format gathered data into the text block that the review prompts expect."""
    lines: list[str] = [
        f"{review_type.capitalize()} review period: "
        f"{period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')}\n",
        f"Total entries: {len(episodes)}",
    ]

    # --- Mood / energy statistics ---
    mood_values = [e.mood_score for e in episodes if e.mood_score is not None]
    energy_values = [e.energy_rating for e in episodes if e.energy_rating is not None]

    if mood_values:
        avg_mood = sum(mood_values) / len(mood_values)
        lines.append(f"Average mood: {avg_mood:.1f}")
    if energy_values:
        avg_energy = sum(energy_values) / len(energy_values)
        lines.append(f"Average energy: {avg_energy:.1f}")
    lines.append("")

    # --- Episode entries ---
    if episodes:
        lines.append("Diary entries:")
        for ep in episodes:
            date_str = ep.created_at.strftime("%a %H:%M") if ep.created_at else "?"
            summary = ep.summary or "(no summary)"
            mood_str = f" [mood: {ep.mood_score:.1f}]" if ep.mood_score is not None else ""
            energy_str = (
                f" [energy: {ep.energy_rating:.1f}]" if ep.energy_rating is not None else ""
            )
            lines.append(f"  - [{date_str}] {summary}{mood_str}{energy_str}")
        lines.append("")

    # --- Active goals ---
    if goals:
        lines.append("Active goals:")
        for g in goals:
            pct = int((g.progress or 0) * 100)
            lines.append(f"  - {g.title}: {pct}% ({g.status})")
        lines.append("")

    return "\n".join(lines)


async def generate_review_node(state: ReviewState) -> ReviewState:
    """Generate the review using Opus.

    Dispatches to weekly or quarterly based on state['review_type'].
    """
    client: AsyncAnthropic = state["client"]
    review_type = state.get("review_type", "weekly")

    if review_type == "quarterly":
        review = await generate_quarterly_review(state.get("data", ""), client)
    else:
        review = await generate_weekly_review(state.get("data", ""), client)

    return ReviewState(result=review.model_dump())


async def extract_actions_node(state: ReviewState) -> ReviewState:
    """Extract action items from the review for follow-up."""
    result = state.get("result", {})
    # Weekly reviews use 'recommendations', quarterly uses 'next_quarter_priorities'
    actions = result.get("recommendations") or result.get("next_quarter_priorities", [])
    return ReviewState(actions=actions)


def build_review_graph() -> StateGraph[ReviewState]:
    """Build the review subgraph."""
    graph = StateGraph(ReviewState)

    graph.add_node("gather_data", gather_data_node)
    graph.add_node("generate_review", generate_review_node)
    graph.add_node("extract_actions", extract_actions_node)

    graph.add_edge(START, "gather_data")
    graph.add_edge("gather_data", "generate_review")
    graph.add_edge("generate_review", "extract_actions")
    graph.add_edge("extract_actions", END)

    return graph
