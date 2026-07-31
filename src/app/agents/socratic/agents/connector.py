"""Connector agent — second brain linker.

Uses Sonnet for synthesising connections between disparate knowledge.
Links the current discussion to the user's diary, notes, past tutorials.

No fallbacks. If Claude fails, the error propagates.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from anthropic import AsyncAnthropic

from src.app.agents.socratic.prompts.connector import CONNECTOR_SYSTEM_PROMPT
from src.app.agents.socratic.state import AgentResponse
from src.app.config import get_settings
from src.app.core.llm_helpers import call_and_parse

logger = structlog.get_logger()


def _build_connector_context(
    state: dict[str, Any],
    assessor_suggestion: str | None = None,
) -> str:
    """Build context for the Connector from its filtered view.

    The Connector sees: working memory, its prep (relevant notes,
    prior work links, knowledge gaps), and Assessor's suggestion.
    """
    working_memory = state.get("working_memory", [])
    recent = "\n".join(f"[{t.get('role', '?')}]: {t.get('content', '')}" for t in working_memory)

    connector_prep = state.get("connector_prep", {})
    notes = (
        json.dumps(
            connector_prep.get("relevant_notes", [])[:5],
            indent=2,
        )
        if connector_prep
        else "None"
    )
    links = (
        json.dumps(
            connector_prep.get("prior_work_links", [])[:5],
            indent=2,
        )
        if connector_prep
        else "None"
    )
    gaps = (
        json.dumps(
            connector_prep.get("knowledge_gaps", [])[:5],
            indent=2,
        )
        if connector_prep
        else "None"
    )

    suggestion = (
        f"\n<assessor_hint>{assessor_suggestion}</assessor_hint>" if assessor_suggestion else ""
    )

    return f"""\
<recent_dialogue>
{recent}
</recent_dialogue>

<relevant_notes_from_second_brain>
{notes}
</relevant_notes_from_second_brain>

<prior_work_connections>
{links}
</prior_work_connections>

<knowledge_gaps>
{gaps}
</knowledge_gaps>
{suggestion}
Surface a relevant connection from the student's prior work or knowledge."""


async def connect(
    state: dict[str, Any],
    client: AsyncAnthropic,
    assessor_suggestion: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> AgentResponse:
    """Generate the Connector's response linking to prior knowledge.

    No fallback. If Claude fails, the error propagates.
    """
    settings = get_settings()
    model = model or settings.socratic_connector_model
    max_tokens = max_tokens or settings.socratic_connector_max_tokens

    context = _build_connector_context(state, assessor_suggestion)

    return await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system=CONNECTOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
        response_model=AgentResponse,
        error_context="socratic connector",
        inject_personality=False,
    )
