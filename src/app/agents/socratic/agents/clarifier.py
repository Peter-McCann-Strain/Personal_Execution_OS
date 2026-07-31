"""Clarifier agent — precision enforcer.

Uses Haiku for fast, neutral interventions. Safe to use when the student
is defensive because it targets language, not positions.

No fallbacks. If Claude fails, the error propagates.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from anthropic import AsyncAnthropic

from src.app.agents.socratic.prompts.clarifier import CLARIFIER_SYSTEM_PROMPT
from src.app.agents.socratic.state import AgentResponse
from src.app.config import get_settings
from src.app.core.llm_helpers import call_and_parse

logger = structlog.get_logger()


def _build_clarifier_context(
    state: dict[str, Any],
    assessor_suggestion: str | None = None,
) -> str:
    """Build context for the Clarifier from its filtered view.

    The Clarifier sees: working memory, its prep (ambiguous terms,
    vague claims), and Assessor's suggestion. Minimal context to keep
    responses focused.
    """
    working_memory = state.get("working_memory", [])
    recent = "\n".join(f"[{t.get('role', '?')}]: {t.get('content', '')}" for t in working_memory)

    clarifier_prep = state.get("clarifier_prep", {})
    ambiguous = (
        json.dumps(
            clarifier_prep.get("ambiguous_terms", [])[:5],
            indent=2,
        )
        if clarifier_prep
        else "None"
    )
    vague = (
        json.dumps(
            clarifier_prep.get("vague_claims", [])[:5],
            indent=2,
        )
        if clarifier_prep
        else "None"
    )

    suggestion = (
        f"\n<assessor_hint>{assessor_suggestion}</assessor_hint>" if assessor_suggestion else ""
    )

    return f"""\
<recent_dialogue>
{recent}
</recent_dialogue>

<ambiguities_detected>
{ambiguous}
</ambiguities_detected>

<vague_claims>
{vague}
</vague_claims>
{suggestion}
Demand precision on the most important ambiguity in the student's latest response."""


async def clarify(
    state: dict[str, Any],
    client: AsyncAnthropic,
    assessor_suggestion: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> AgentResponse:
    """Generate the Clarifier's precision request.

    No fallback. If Claude fails, the error propagates.
    """
    settings = get_settings()
    model = model or settings.socratic_clarifier_model
    max_tokens = max_tokens or settings.socratic_clarifier_max_tokens

    context = _build_clarifier_context(state, assessor_suggestion)

    return await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system=CLARIFIER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
        response_model=AgentResponse,
        error_context="socratic clarifier",
        inject_personality=False,
    )
