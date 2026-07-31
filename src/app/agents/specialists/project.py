"""Project agent — manages projects, tasks, sprints, WSJF prioritisation.

Uses Sonnet for AI-assisted project breakdown. No fallback.
"""

import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from src.app.agents.prompts.project import PROJECT_BREAKDOWN_PROMPT
from src.app.config import get_settings
from src.app.core.llm_helpers import call_and_parse

logger = structlog.get_logger()


class TaskBreakdown(BaseModel):
    title: str
    description: str
    estimate_hours: float = Field(ge=0.5, le=8.0)
    complexity: str
    context_tags: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class MilestoneBreakdown(BaseModel):
    title: str
    success_criteria: list[str]
    tasks: list[TaskBreakdown]


class ProjectBreakdownResult(BaseModel):
    milestones: list[MilestoneBreakdown]
    project_summary: str | None = None
    total_estimated_hours: float | None = None
    critical_path: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    user_reply: str = ""


async def ai_breakdown_project(
    description: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> ProjectBreakdownResult:
    """Use AI to break a project into milestones and tasks."""
    settings = get_settings()
    model = model or settings.project_model
    max_tokens = max_tokens or settings.project_max_tokens

    return await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system=PROJECT_BREAKDOWN_PROMPT,
        messages=[{"role": "user", "content": description}],
        response_model=ProjectBreakdownResult,
        error_context="Project breakdown",
    )


def calculate_wsjf(
    business_value: int,
    time_criticality: int,
    risk_reduction: int,
    job_size: int,
) -> float:
    """Calculate WSJF score for task prioritisation.

    WSJF = Cost of Delay / Job Size
    Cost of Delay = Business Value + Time Criticality + Risk Reduction

    All inputs on 1-10 scale. Raises ValueError if inputs are out of range.
    """
    for name, value in [
        ("business_value", business_value),
        ("time_criticality", time_criticality),
        ("risk_reduction", risk_reduction),
        ("job_size", job_size),
    ]:
        if not (1 <= value <= 10):
            raise ValueError(f"{name} must be between 1 and 10, got {value}")
    cost_of_delay = business_value + time_criticality + risk_reduction
    return round(cost_of_delay / job_size, 2)
