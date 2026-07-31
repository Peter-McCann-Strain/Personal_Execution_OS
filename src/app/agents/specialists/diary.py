"""Diary agent — processes captures into structured diary entries.

Uses raw Anthropic SDK. No fallbacks. Fails loudly on API errors.
"""

import structlog
from anthropic import AsyncAnthropic

from src.app.agents.prompts.diary import DIARY_SYSTEM_PROMPT
from src.app.config import get_settings
from src.app.core.llm_helpers import call_and_parse_with_retry
from src.app.domain.models import DiaryEntry

logger = structlog.get_logger()


async def process_diary_entry(
    message: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
    context: str | None = None,
) -> DiaryEntry:
    """Process a user message into a structured diary entry.

    No fallback. If Claude fails, the error propagates.
    """
    settings = get_settings()
    model = model or settings.diary_model
    max_tokens = max_tokens or settings.diary_max_tokens

    system_prompt = DIARY_SYSTEM_PROMPT
    if context:
        system_prompt += f"\n\n## Additional Context\n{context}"

    return await call_and_parse_with_retry(
        client,
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": message}],
        response_model=DiaryEntry,
        error_context="diary agent",
    )
