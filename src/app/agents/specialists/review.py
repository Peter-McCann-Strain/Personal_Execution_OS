"""Review agent — weekly, monthly, quarterly, annual reviews with pattern detection.

Uses Opus for deep analysis. No fallback.
"""

from typing import TypeVar

import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from src.app.agents.prompts.review import (
    ANNUAL_REVIEW_PROMPT,
    MONTHLY_REVIEW_PROMPT,
    QUARTERLY_REVIEW_PROMPT,
    WEEKLY_REVIEW_PROMPT,
)
from src.app.config import get_settings
from src.app.core.llm_helpers import call_and_parse

logger = structlog.get_logger()

_T = TypeVar("_T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PatternNoticed(BaseModel):
    pattern: str
    evidence: str = ""
    category: str = ""
    actionable: bool = False


class Recommendation(BaseModel):
    action: str
    why: str = ""
    priority: str = "medium"


class WeeklyReview(BaseModel):
    period: str
    accomplishments: list[str] = Field(default_factory=list)
    mood_summary: str | None = None
    average_mood: float | None = Field(default=None, ge=0.0, le=10.0)
    average_energy: float | None = Field(default=None, ge=0.0, le=10.0)
    goal_progress: list[dict] = Field(default_factory=list)
    open_commitments: list[dict] = Field(default_factory=list)
    relationship_alerts: list[str] = Field(default_factory=list)
    patterns_noticed: list[PatternNoticed] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    key_insight: str | None = None
    user_reply: str = ""


class MonthlyReview(BaseModel):
    period: str
    accomplishments: list[str] = Field(default_factory=list)
    mood_trend: str | None = None
    average_mood: float | None = Field(default=None, ge=0.0, le=10.0)
    goal_progress: list[dict] = Field(default_factory=list)
    habit_adherence: list[dict] = Field(default_factory=list)
    patterns_noticed: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    key_insight: str | None = None
    user_reply: str = ""


class QuarterlyReview(BaseModel):
    period: str
    goal_achievement: list[dict] = Field(default_factory=list)
    major_decisions: list[dict] = Field(default_factory=list)
    relationship_health: list[dict] = Field(default_factory=list)
    pattern_analysis: list[str] = Field(default_factory=list)
    lessons_learned: list[str] = Field(default_factory=list)
    next_quarter_priorities: list[str] = Field(default_factory=list)
    key_insight: str | None = None
    user_reply: str = ""


class AnnualReview(BaseModel):
    period: str
    year_theme: str | None = None
    major_accomplishments: list[str] = Field(default_factory=list)
    goal_achievement: list[dict] = Field(default_factory=list)
    major_decisions: list[dict] = Field(default_factory=list)
    relationship_summary: list[dict] = Field(default_factory=list)
    personal_growth: list[str] = Field(default_factory=list)
    lessons_learned: list[str] = Field(default_factory=list)
    next_year_vision: list[str] = Field(default_factory=list)
    user_reply: str = ""
    key_insight: str | None = None


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------


async def _generate_review(
    data: str,
    client: AsyncAnthropic,
    *,
    system: str,
    response_model: type[_T],
    error_context: str,
    model: str | None = None,
    max_tokens: int | None = None,
) -> _T:
    """Common logic for all review periods."""
    settings = get_settings()
    return await call_and_parse(
        client,
        model=model or settings.review_model,
        max_tokens=max_tokens or settings.review_max_tokens,
        system=system,
        messages=[{"role": "user", "content": data}],
        response_model=response_model,
        error_context=error_context,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_weekly_review(
    week_data: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> WeeklyReview:
    """Generate a weekly review from aggregated data."""
    return await _generate_review(
        week_data,
        client,
        system=WEEKLY_REVIEW_PROMPT,
        response_model=WeeklyReview,
        error_context="Weekly review generation",
        model=model,
        max_tokens=max_tokens,
    )


async def generate_monthly_review(
    month_data: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> MonthlyReview:
    """Generate a monthly review from aggregated data."""
    return await _generate_review(
        month_data,
        client,
        system=MONTHLY_REVIEW_PROMPT,
        response_model=MonthlyReview,
        error_context="Monthly review generation",
        model=model,
        max_tokens=max_tokens,
    )


async def generate_quarterly_review(
    quarter_data: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> QuarterlyReview:
    """Generate a quarterly review from aggregated data."""
    return await _generate_review(
        quarter_data,
        client,
        system=QUARTERLY_REVIEW_PROMPT,
        response_model=QuarterlyReview,
        error_context="Quarterly review generation",
        model=model,
        max_tokens=max_tokens,
    )


async def generate_annual_review(
    year_data: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> AnnualReview:
    """Generate an annual review from aggregated data."""
    return await _generate_review(
        year_data,
        client,
        system=ANNUAL_REVIEW_PROMPT,
        response_model=AnnualReview,
        error_context="Annual review generation",
        model=model,
        max_tokens=max_tokens,
    )
