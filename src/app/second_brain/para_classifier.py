"""PARA classification — assigns captures to Projects, Areas, Resources, or Archives.

Uses LLM (Haiku) for classification. No fallback. Fails loudly.
"""

import structlog
from anthropic import APIError, AsyncAnthropic

from src.app.config import get_settings
from src.app.core.exceptions import LLMError
from src.app.core.llm_helpers import call_llm, parse_json_response
from src.app.domain.constants import ParaCategory

logger = structlog.get_logger()

PARA_PROMPT = """Classify the following text into one PARA category.

## Categories
- project: tied to an active project with a deadline or defined outcome
- area: an ongoing responsibility or standard to maintain (health, career, finances, relationships)
- resource: reference material, interesting info, something to potentially use later
- archive: completed, dormant, or no longer relevant

## Rules
- Default to "resource" if genuinely uncertain
- Short personal reflections/diary entries are usually "area" (self/wellbeing)
- Tasks or action items tied to specific outcomes are "project"
- Random interesting facts or links are "resource"

Respond with JSON only: {"category": "project|area|resource|archive", "reasoning": "brief why"}"""


async def classify_para(
    text: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Classify text into a PARA category. Returns one of: project, area, resource, archive."""
    settings = get_settings()
    model = model or settings.classifier_model
    max_tokens = max_tokens or settings.classifier_max_tokens

    try:
        response = await call_llm(
            client,
            model=model,
            max_tokens=max_tokens,
            system=PARA_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
    except (APIError, LLMError) as e:
        logger.error("para_classification_failed", error=str(e))
        raise LLMError(f"PARA classification failed: {e}") from e

    try:
        data = parse_json_response(response, "PARA classification")
        category = data["category"]
        if category not in set(ParaCategory):
            raise LLMError(f"Invalid PARA category: {category}")
        logger.info("para_classified", category=category, reasoning=data.get("reasoning"))
        return category
    except KeyError as e:
        logger.error("para_parse_failed", error=str(e))
        raise LLMError(f"Failed to parse PARA classification: {e}") from e
