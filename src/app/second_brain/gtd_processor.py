"""GTD (Getting Things Done) processor — clarify and organise incoming captures.

Uses LLM (Haiku) to determine actionability and next steps. No fallback.
"""

from __future__ import annotations

from typing import Literal

import structlog
from anthropic import APIError, AsyncAnthropic
from pydantic import BaseModel

from src.app.config import get_settings
from src.app.core.exceptions import LLMError
from src.app.core.llm_helpers import call_llm, parse_json_response

logger = structlog.get_logger()

GtdType = Literal[
    "do_now",
    "next_action",
    "create_project",
    "waiting_for",
    "reference",
    "someday_maybe",
    "incubate",
]


class GtdResult(BaseModel):
    """Validated result of GTD processing."""

    is_actionable: bool
    gtd_type: GtdType
    next_action: str | None = None
    reasoning: str = ""


GTD_PROMPT = """You are a GTD (Getting Things Done) processor.
Analyse the user's input and determine:

1. Is it actionable? (does it require doing something?)
2. If actionable:
   - Can it be done in under 2 minutes? → flag as "do_now"
   - Is it a multi-step outcome? → flag as "create_project"
   - Is it a single deferred action? → flag as "next_action"
   - Should someone else do it? → flag as "waiting_for"
3. If not actionable:
   - Is it reference material? → flag as "reference"
   - Is it a someday/maybe idea? → flag as "someday_maybe"
   - Is it just a thought/reflection? → flag as "incubate"

Respond with JSON only:
{
    "is_actionable": true/false,
    "gtd_type": "do_now|next_action|create_project|waiting_for|reference|someday_maybe|incubate",
    "next_action": "specific next physical action if actionable, null otherwise",
    "reasoning": "brief explanation"
}"""


async def process_gtd(
    text: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> GtdResult:
    """Process text through GTD clarify/organise flow.

    Returns a validated ``GtdResult`` with typed fields.
    """
    settings = get_settings()
    model = model or settings.classifier_model
    max_tokens = max_tokens or settings.classifier_max_tokens

    try:
        response = await call_llm(
            client,
            model=model,
            max_tokens=max_tokens,
            system=GTD_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
    except (APIError, LLMError) as e:
        logger.error("gtd_processing_failed", error=str(e), model=model)
        raise LLMError(f"GTD processing failed: {e}") from e

    data = parse_json_response(response, "GTD processing")

    try:
        result = GtdResult(**data)
    except ValueError as e:
        logger.error("gtd_parse_failed", error=str(e))
        raise LLMError(f"Failed to parse GTD response: {e}") from e

    logger.info(
        "gtd_processed",
        is_actionable=result.is_actionable,
        gtd_type=result.gtd_type,
    )
    return result
