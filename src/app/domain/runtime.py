"""Agent runtime contracts and defaults."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from src.app.config import Settings, get_settings
from src.app.domain.models import Specialist


class ConfirmationPolicy(StrEnum):
    """When a specialist must obtain user confirmation before acting."""

    NEVER = "never"
    ON_MUTATION = "on_mutation"
    ALWAYS = "always"


class AgentRuntimeConfig(BaseModel):
    """Operational contract for a specialist runtime."""

    specialist: Specialist
    prompt_source: str
    allowed_tools: list[str] = Field(default_factory=list)
    confirmation_policy: ConfirmationPolicy = ConfirmationPolicy.NEVER
    memory_namespace: str
    model_policy: str
    eval_rubric_id: str
    max_token_budget: int
    output_schema: str


def get_agent_runtime_config(
    specialist: Specialist,
    settings: Settings | None = None,
) -> AgentRuntimeConfig:
    """Resolve the runtime contract for a specialist."""
    settings = settings or get_settings()

    configs: dict[Specialist, AgentRuntimeConfig] = {
        Specialist.DIARY: AgentRuntimeConfig(
            specialist=Specialist.DIARY,
            prompt_source="src/app/agents/prompts/diary.py",
            memory_namespace="session.diary",
            model_policy=settings.diary_model,
            eval_rubric_id="diary-response-v1",
            max_token_budget=settings.diary_max_tokens,
            output_schema="chat_response",
        ),
        Specialist.MEMORY: AgentRuntimeConfig(
            specialist=Specialist.MEMORY,
            prompt_source="src/app/agents/specialists/memory.py",
            memory_namespace="memory.unified_search",
            model_policy=settings.memory_model,
            eval_rubric_id="memory-answer-v1",
            max_token_budget=settings.memory_max_tokens,
            output_schema="memory_answer",
        ),
        Specialist.RESEARCH: AgentRuntimeConfig(
            specialist=Specialist.RESEARCH,
            prompt_source="src/app/agents/prompts/research.py",
            memory_namespace="session.research",
            model_policy=settings.research_synthesis_model,
            eval_rubric_id="research-report-v1",
            max_token_budget=settings.research_synthesis_max_tokens,
            output_schema="research_report",
        ),
        Specialist.REVIEW: AgentRuntimeConfig(
            specialist=Specialist.REVIEW,
            prompt_source="src/app/agents/prompts/review.py",
            memory_namespace="session.review",
            model_policy=settings.review_model,
            eval_rubric_id="review-analysis-v1",
            max_token_budget=settings.review_max_tokens,
            output_schema="review_summary",
        ),
        Specialist.PROJECT: AgentRuntimeConfig(
            specialist=Specialist.PROJECT,
            prompt_source="src/app/agents/prompts/project.py",
            memory_namespace="projects.active",
            model_policy=settings.project_model,
            eval_rubric_id="project-planning-v1",
            max_token_budget=settings.project_max_tokens,
            output_schema="project_plan",
        ),
        Specialist.COMMUNICATIONS: AgentRuntimeConfig(
            specialist=Specialist.COMMUNICATIONS,
            prompt_source="src/app/agents/prompts/communications.py",
            memory_namespace="communications.active",
            model_policy=settings.communications_model,
            eval_rubric_id="communications-draft-v1",
            max_token_budget=settings.communications_draft_max_tokens,
            output_schema="communications_response",
        ),
        Specialist.TOOLS: AgentRuntimeConfig(
            specialist=Specialist.TOOLS,
            prompt_source="src/app/agents/specialists/tools.py",
            allowed_tools=[
                "google-calendar__*",
                "google-gmail__*",
                "tavily-search__*",
                "filesystem__read*",
                "filesystem__list*",
                "filesystem__search*",
            ],
            confirmation_policy=ConfirmationPolicy.ON_MUTATION,
            memory_namespace="tools.session",
            model_policy=settings.tools_model,
            eval_rubric_id="tools-execution-v1",
            max_token_budget=settings.tools_summary_max_tokens,
            output_schema="tool_summary",
        ),
        Specialist.NOTIFICATION: AgentRuntimeConfig(
            specialist=Specialist.NOTIFICATION,
            prompt_source="src/app/agents/prompts/notification.py",
            memory_namespace="notifications.active",
            model_policy=settings.classifier_model,
            eval_rubric_id="notification-response-v1",
            max_token_budget=settings.classifier_max_tokens,
            output_schema="notification_response",
        ),
        Specialist.SAVE: AgentRuntimeConfig(
            specialist=Specialist.SAVE,
            prompt_source="src/app/agents/prompts/save.py",
            memory_namespace="memory.capture",
            model_policy=settings.classifier_model,
            eval_rubric_id="save-handler-v1",
            max_token_budget=settings.classifier_max_tokens,
            output_schema="save_result",
        ),
        Specialist.PLAN_DAY: AgentRuntimeConfig(
            specialist=Specialist.PLAN_DAY,
            prompt_source="src/app/agents/prompts/plan_day.py",
            memory_namespace="planning.day",
            model_policy=settings.project_model,
            eval_rubric_id="day-plan-v1",
            max_token_budget=settings.project_max_tokens,
            output_schema="day_plan",
        ),
        Specialist.SOCRATIC: AgentRuntimeConfig(
            specialist=Specialist.SOCRATIC,
            prompt_source="src/app/agents/socratic/prompts",
            memory_namespace="tutorial.socratic",
            model_policy=settings.socratic_tutor_model,
            eval_rubric_id="socratic-tutorial-v1",
            max_token_budget=settings.socratic_analysis_max_tokens,
            output_schema="tutorial_response",
        ),
        # CONVERSATIONAL is a virtual specialist — no LLM call, returns a
        # capabilities list when routing confidence is below threshold.
        Specialist.CONVERSATIONAL: AgentRuntimeConfig(
            specialist=Specialist.CONVERSATIONAL,
            prompt_source="src/app/domain/services/chat.py",
            memory_namespace="session.conversational",
            model_policy=settings.routing_model,
            eval_rubric_id="conversational-response-v1",
            max_token_budget=settings.routing_max_tokens,
            output_schema="capabilities_list",
        ),
    }

    return configs[specialist]
