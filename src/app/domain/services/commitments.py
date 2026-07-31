"""Commitment extraction and tracking — detects promises from conversations.

Uses LLM (Haiku) to extract commitments. No fallback.
"""

import anthropic
import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from src.app.config import get_settings
from src.app.core.exceptions import LLMError
from src.app.core.llm_helpers import call_llm, parse_json_response

logger = structlog.get_logger()

COMMITMENT_PROMPT = """Extract any commitments or promises from the text.

A commitment is when someone says they will do something, or asks someone to do something.

For each commitment found:
- verbatim_text: the exact quote
- normalized_action: what needs to be done
- who_committed: who made the promise (or "user" for the speaker)
- who_to: who it was promised to (or null if unclear)
- temporal_expression: any time reference ("by Friday", "next week", "tomorrow")
- confidence: 0.0-1.0 how confident you are this is a real commitment

Respond with JSON only:
{
    "commitments": [
        {
            "verbatim_text": "exact quote",
            "normalized_action": "clear action description",
            "who_committed": "name or user",
            "who_to": "name or null",
            "temporal_expression": "time reference or null",
            "confidence": 0.0-1.0
        }
    ]
}

If there are no commitments, return: {"commitments": []}"""


class ExtractedCommitment(BaseModel):
    verbatim_text: str
    normalized_action: str
    who_committed: str
    who_to: str | None = None
    temporal_expression: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


async def extract_commitments(
    text: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> list[ExtractedCommitment]:
    """Extract commitments from text. Returns list of ExtractedCommitment.

    Uses call_llm + parse_json_response directly because the response
    contains a nested list ('commitments' key) rather than a flat Pydantic model.
    """
    settings = get_settings()
    model = model or settings.commitment_model
    max_tokens = max_tokens or settings.commitment_max_tokens

    try:
        response = await call_llm(
            client,
            model=model,
            max_tokens=max_tokens,
            system=COMMITMENT_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
    except (LLMError, anthropic.APIError) as e:
        logger.error("commitment_extraction_failed", error=str(e))
        raise LLMError(f"Commitment extraction failed: {e}") from e

    try:
        data = parse_json_response(response, "commitment extraction")
        commitments = [ExtractedCommitment(**c) for c in data.get("commitments", [])]
        logger.info("commitments_extracted", count=len(commitments))
        return commitments
    except (KeyError, ValueError) as e:
        logger.error("commitment_parse_failed", error=str(e))
        raise LLMError(f"Failed to parse commitments: {e}") from e
