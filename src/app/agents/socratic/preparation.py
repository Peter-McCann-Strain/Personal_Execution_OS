"""Preparation phase — async processing before a tutorial begins.

1. Extract atomic propositions from submitted work
2. Fan out to 4 prep agents in parallel (via LangGraph Send)
3. Merge preparation results into the blackboard

This runs ASYNC via ARQ before the student starts the tutorial.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from anthropic import AsyncAnthropic

from src.app.agents.socratic.prompts.preparation import (
    CLARIFIER_PREP_PROMPT,
    CONNECTOR_PREP_PROMPT,
    DEVILS_ADVOCATE_PREP_PROMPT,
    PROPOSITION_EXTRACTION_PROMPT,
    TUTOR_PREP_PROMPT,
)
from src.app.agents.socratic.state import (
    ClarifierPrep,
    ConnectorPrep,
    DevilsAdvocatePrep,
    Proposition,
    TutorPrep,
)
from src.app.config import get_settings
from src.app.core.llm_helpers import call_and_parse, call_llm, parse_json_response

logger = structlog.get_logger()


async def extract_propositions(
    submitted_work: str,
    work_type: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> list[Proposition]:
    """Extract atomic propositions from submitted work.

    Returns a list of Proposition objects ordered by centrality.
    No fallback. If Claude fails, the error propagates.
    """
    settings = get_settings()
    model = model or settings.socratic_preparation_model
    max_tokens = max_tokens or settings.socratic_preparation_max_tokens
    max_props = settings.socratic_max_propositions

    prompt = PROPOSITION_EXTRACTION_PROMPT.format(
        max_propositions=max_props,
        work_type=work_type,
        submitted_work=submitted_work,
    )

    response = await call_llm(
        client,
        model=model,
        max_tokens=max_tokens,
        system="You extract atomic propositions from submitted work. Respond with valid JSON only.",
        messages=[{"role": "user", "content": prompt}],
        inject_personality=False,
    )

    data = parse_json_response(response, error_context="proposition extraction")
    raw_props = data.get("propositions", [])

    propositions = []
    for i, p in enumerate(raw_props[:max_props]):
        propositions.append(
            Proposition(
                index=i,
                text=p.get("text", ""),
                source_location=p.get("source_location", ""),
                claim_type=p.get("claim_type", "assertion"),
                centrality=float(p.get("centrality", 0.5)),
            )
        )

    logger.info("propositions_extracted", count=len(propositions))
    return propositions


async def prepare_tutor(
    propositions: list[dict[str, Any]],
    submitted_work: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> TutorPrep:
    """Prepare the Tutor's questioning plan."""
    settings = get_settings()
    model = model or settings.socratic_tutor_model
    max_tokens = max_tokens or settings.socratic_preparation_max_tokens

    prompt = TUTOR_PREP_PROMPT.format(
        propositions=json.dumps(propositions, indent=2),
        submitted_work=submitted_work[:2000],
    )

    return await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system="You are preparing a Socratic tutorial. Respond with valid JSON only.",
        messages=[{"role": "user", "content": prompt}],
        response_model=TutorPrep,
        error_context="tutor preparation",
        inject_personality=False,
    )


async def prepare_devils_advocate(
    propositions: list[dict[str, Any]],
    submitted_work: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> DevilsAdvocatePrep:
    """Prepare the Devil's Advocate's counter-arguments."""
    settings = get_settings()
    model = model or settings.socratic_devils_advocate_model
    max_tokens = max_tokens or settings.socratic_preparation_max_tokens

    prompt = DEVILS_ADVOCATE_PREP_PROMPT.format(
        propositions=json.dumps(propositions, indent=2),
        submitted_work=submitted_work[:2000],
    )

    return await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system=(
            "You prepare counter-arguments for a Socratic tutorial. Respond with valid JSON only."
        ),
        messages=[{"role": "user", "content": prompt}],
        response_model=DevilsAdvocatePrep,
        error_context="devils advocate preparation",
        inject_personality=False,
    )


async def prepare_clarifier(
    propositions: list[dict[str, Any]],
    submitted_work: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> ClarifierPrep:
    """Prepare the Clarifier's ambiguity detection."""
    settings = get_settings()
    model = model or settings.socratic_clarifier_model
    max_tokens = max_tokens or settings.socratic_preparation_max_tokens

    prompt = CLARIFIER_PREP_PROMPT.format(
        propositions=json.dumps(propositions, indent=2),
        submitted_work=submitted_work[:2000],
    )

    return await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system=(
            "You detect ambiguity in preparation for a Socratic tutorial."
            " Respond with valid JSON only."
        ),
        messages=[{"role": "user", "content": prompt}],
        response_model=ClarifierPrep,
        error_context="clarifier preparation",
        inject_personality=False,
    )


async def prepare_connector(
    propositions: list[dict[str, Any]],
    submitted_work: str,
    client: AsyncAnthropic,
    second_brain_context: str = "",
    model: str | None = None,
    max_tokens: int | None = None,
) -> ConnectorPrep:
    """Prepare the Connector's links to the second brain."""
    settings = get_settings()
    model = model or settings.socratic_connector_model
    max_tokens = max_tokens or settings.socratic_preparation_max_tokens

    prompt = CONNECTOR_PREP_PROMPT.format(
        propositions=json.dumps(propositions, indent=2),
        submitted_work=submitted_work[:2000],
        second_brain_context=second_brain_context or "No prior context available.",
    )

    return await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system=(
            "You find connections to prior knowledge for a Socratic tutorial."
            " Respond with valid JSON only."
        ),
        messages=[{"role": "user", "content": prompt}],
        response_model=ConnectorPrep,
        error_context="connector preparation",
        inject_personality=False,
    )
