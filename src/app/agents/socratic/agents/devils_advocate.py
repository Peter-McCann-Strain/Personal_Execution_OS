"""Devil's Advocate agent — steelman-then-attack challenger.

Uses Opus for genuine reasoning diversity (different model from Tutor).
DMAD research (ICLR 2025) shows model diversity is the dominant driver
of debate quality (73% improvement).

No fallbacks. If Claude fails, the error propagates.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from anthropic import AsyncAnthropic

from src.app.agents.socratic.prompts.devils_advocate import DEVILS_ADVOCATE_SYSTEM_PROMPT
from src.app.agents.socratic.state import AgentResponse
from src.app.config import get_settings
from src.app.core.llm_helpers import call_and_parse

logger = structlog.get_logger()


def _build_da_context(
    state: dict[str, Any],
    assessor_suggestion: str | None = None,
) -> str:
    """Build context for the Devil's Advocate from its filtered view.

    The DA sees: working memory, current proposition, its own prep
    (counter-arguments, steelman positions), and Assessor's suggestion.
    """
    working_memory = state.get("working_memory", [])
    recent = "\n".join(f"[{t.get('role', '?')}]: {t.get('content', '')}" for t in working_memory)

    propositions = state.get("propositions", [])
    prop_idx = state.get("current_proposition_index", 0)
    current_prop = ""
    if propositions and prop_idx < len(propositions):
        current_prop = json.dumps(propositions[prop_idx], indent=2)

    da_prep = state.get("devils_advocate_prep", {})
    counters = json.dumps(da_prep.get("counter_arguments", [])[:3], indent=2) if da_prep else "None"
    steelmans = (
        json.dumps(da_prep.get("steelman_positions", [])[:3], indent=2) if da_prep else "None"
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

<your_counter_arguments>
{counters}
</your_counter_arguments>

<your_steelman_positions>
{steelmans}
</your_steelman_positions>
{suggestion}
Challenge the student's position using Dennett's rules: steelman first, then attack."""


async def challenge(
    state: dict[str, Any],
    client: AsyncAnthropic,
    assessor_suggestion: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> AgentResponse:
    """Generate the Devil's Advocate's challenge.

    No fallback. If Claude fails, the error propagates.
    """
    settings = get_settings()
    model = model or settings.socratic_devils_advocate_model
    max_tokens = max_tokens or settings.socratic_devils_advocate_max_tokens

    context = _build_da_context(state, assessor_suggestion)

    return await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system=DEVILS_ADVOCATE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
        response_model=AgentResponse,
        error_context="socratic devils advocate",
        inject_personality=False,
    )
