"""Assessor agent — hidden pedagogical gatekeeper.

Uses Haiku for speed (~100ms). Reads the full blackboard state and decides
which agent speaks next. Never visible to the user.

No fallbacks. If Claude fails, the error propagates.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from anthropic import AsyncAnthropic

from src.app.agents.socratic.prompts.assessor import ASSESSOR_SYSTEM_PROMPT
from src.app.agents.socratic.state import (
    AssessorDecision,
)
from src.app.config import get_settings
from src.app.core.llm_helpers import call_and_parse

logger = structlog.get_logger()


def _build_assessor_context(state: dict[str, Any]) -> str:
    """Build the context message for the Assessor from blackboard state.

    The Assessor sees EVERYTHING — full dialogue, prep results, metrics.
    """
    # Working memory: last N turns
    working_memory = state.get("working_memory", [])
    recent_turns = "\n".join(
        f"[{t.get('role', '?')}]: {t.get('content', '')}" for t in working_memory
    )

    # Speaking ratio
    ratio = state.get("speaking_ratio", {"user_words": 0, "agent_words": 0})
    user_words = ratio.get("user_words", 0)
    agent_words = ratio.get("agent_words", 0)
    total_words = user_words + agent_words
    user_pct = round(user_words / total_words * 100) if total_words > 0 else 50

    # Current proposition being discussed
    propositions = state.get("propositions", [])
    prop_idx = state.get("current_proposition_index", 0)
    current_prop = ""
    if propositions and prop_idx < len(propositions):
        current_prop = json.dumps(propositions[prop_idx], indent=2)

    # Preparation highlights
    tutor_prep = state.get("tutor_prep", {})
    da_prep = state.get("devils_advocate_prep", {})

    return f"""\
<tutorial_state>
Phase: {state.get("phase", "dialogue")}
Turn: {state.get("current_turn", 0)}
Current Bloom's level: {state.get("bloom_level", "understand")}
Cognitive load: {state.get("cognitive_load", "moderate")}
Emotional state: {state.get("emotional_state", "engaged")}
Speaking ratio: student {user_pct}% / agents {100 - user_pct}%
No-intervention count (consecutive): {state.get("no_intervention_count", 0)}
Propositions explored: {len(state.get("propositions_explored", []))} / {len(propositions)}
</tutorial_state>

<current_proposition>
{current_prop}
</current_proposition>

<recent_dialogue>
{recent_turns}
</recent_dialogue>

<tutor_plan_hint>
{json.dumps(tutor_prep.get("question_sequence", [])[:3], indent=2) if tutor_prep else "No plan"}
</tutor_plan_hint>

<da_vulnerabilities>
{json.dumps(da_prep.get("vulnerabilities", []), indent=2) if da_prep else "None prepared"}
</da_vulnerabilities>

Now decide: which agent should speak next, or should we remain silent?"""


async def assess_turn(
    state: dict[str, Any],
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> AssessorDecision:
    """Evaluate the student's latest response and route to the right agent.

    Returns an AssessorDecision with the action, reasoning, and state updates.
    No fallback. If Claude fails, the error propagates.
    """
    settings = get_settings()
    model = model or settings.socratic_assessor_model
    max_tokens = max_tokens or settings.socratic_assessor_max_tokens

    context = _build_assessor_context(state)

    decision = await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system=ASSESSOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
        response_model=AssessorDecision,
        error_context="socratic assessor",
        inject_personality=False,  # Assessor is hidden — no personality injection
    )

    logger.info(
        "assessor_decision",
        action=decision.action,
        bloom_level=decision.bloom_level,
        cognitive_load=decision.cognitive_load,
        emotional_state=decision.emotional_state,
        speaking_ratio_ok=decision.speaking_ratio_ok,
    )

    return decision
