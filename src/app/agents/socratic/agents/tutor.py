"""Tutor agent — the primary Socratic questioner.

Uses Sonnet for nuanced, adaptive questioning. The main voice the student hears.

No fallbacks. If Claude fails, the error propagates.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from anthropic import AsyncAnthropic

from src.app.agents.socratic.prompts.tutor import (
    TUTOR_OPENING_PROMPT,
    TUTOR_SYSTEM_PROMPT,
)
from src.app.agents.socratic.state import AgentResponse
from src.app.config import get_settings
from src.app.core.llm_helpers import call_and_parse

logger = structlog.get_logger()


def _build_tutor_context(
    state: dict[str, Any],
    assessor_suggestion: str | None = None,
) -> str:
    """Build context for the Tutor from its filtered view of the blackboard.

    The Tutor sees: working memory, current proposition, its prep, and
    the Assessor's suggestion. It does NOT see other agents' prep or the
    full Assessor reasoning.
    """
    working_memory = state.get("working_memory", [])
    recent = "\n".join(f"[{t.get('role', '?')}]: {t.get('content', '')}" for t in working_memory)

    propositions = state.get("propositions", [])
    prop_idx = state.get("current_proposition_index", 0)
    current_prop = ""
    if propositions and prop_idx < len(propositions):
        current_prop = json.dumps(propositions[prop_idx], indent=2)

    tutor_prep = state.get("tutor_prep", {})
    plan = (
        json.dumps(tutor_prep.get("question_sequence", [])[:3], indent=2) if tutor_prep else "None"
    )

    suggestion = (
        f"\n<assessor_hint>{assessor_suggestion}</assessor_hint>" if assessor_suggestion else ""
    )

    return f"""\
<recent_dialogue>
{recent}
</recent_dialogue>

<current_proposition>
{current_prop}
</current_proposition>

<your_questioning_plan>
{plan}
</your_questioning_plan>
{suggestion}
Respond to the student's latest message with a Socratic question."""


async def tutor_respond(
    state: dict[str, Any],
    client: AsyncAnthropic,
    assessor_suggestion: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> AgentResponse:
    """Generate the Tutor's response to the student.

    No fallback. If Claude fails, the error propagates.
    """
    settings = get_settings()
    model = model or settings.socratic_tutor_model
    max_tokens = max_tokens or settings.socratic_tutor_max_tokens

    context = _build_tutor_context(state, assessor_suggestion)

    return await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system=TUTOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
        response_model=AgentResponse,
        error_context="socratic tutor",
        inject_personality=False,  # Uses its own persona, not the assistant personality
    )


async def tutor_opening(
    state: dict[str, Any],
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> AgentResponse:
    """Generate the Tutor's opening question for a new tutorial.

    Uses the Feynman technique: "Explain this to me as if..."
    """
    settings = get_settings()
    model = model or settings.socratic_tutor_model
    max_tokens = max_tokens or settings.socratic_tutor_max_tokens

    tutor_prep = state.get("tutor_prep", {})
    propositions = state.get("propositions", [])

    opening_context = TUTOR_OPENING_PROMPT.format(
        work_summary=tutor_prep.get("work_summary", state.get("submitted_work", "")[:500]),
        propositions=json.dumps(propositions[:5], indent=2),
        question_plan=json.dumps(tutor_prep.get("question_sequence", [])[:3], indent=2),
    )

    return await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system=TUTOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": opening_context}],
        response_model=AgentResponse,
        error_context="socratic tutor opening",
        inject_personality=False,
    )
