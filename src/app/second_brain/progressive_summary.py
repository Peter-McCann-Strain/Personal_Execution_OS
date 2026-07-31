"""Progressive Summarization — generates Layer 2-4 summaries for notes.

Based on Tiago Forte's Building a Second Brain methodology.
Layer 1: Original text
Layer 2: Bold key passages
Layer 3: Highlighted most important
Layer 4: Executive summary (1-2 sentences)
"""

import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from src.app.config import get_settings
from src.app.core.llm_helpers import call_and_parse

logger = structlog.get_logger()


class ProgressiveSummaryResult(BaseModel):
    """Validated structure for progressive summary LLM output."""

    layer_2_passages: list[str]
    layer_3_highlights: list[str]
    layer_4_summary: str


SUMMARY_PROMPT = """Generate progressive summaries for the following note.

## Layers
- Layer 2: Extract the 3-5 most important sentences/phrases from the text
- Layer 3: From Layer 2, identify the 1-2 key insights
- Layer 4: Write a 1-2 sentence executive summary

Respond with JSON:
{
    "layer_2_passages": ["key passage 1", "key passage 2"],
    "layer_3_highlights": ["key insight 1"],
    "layer_4_summary": "Executive summary in 1-2 sentences"
}"""


async def generate_progressive_summary(
    content: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> ProgressiveSummaryResult:
    """Generate Layer 2-4 summaries for a note."""
    settings = get_settings()
    model = model or settings.summary_model
    max_tokens = max_tokens or settings.summary_max_tokens

    return await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system=SUMMARY_PROMPT,
        messages=[{"role": "user", "content": content}],
        response_model=ProgressiveSummaryResult,
        error_context="Progressive summary",
    )
