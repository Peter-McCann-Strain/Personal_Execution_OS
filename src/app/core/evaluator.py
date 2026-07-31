"""Response evaluator — lightweight quality check on specialist responses.

Implements Anthropic's evaluator-optimizer pattern. Uses Haiku to check
whether the specialist's response actually addresses the user's intent.
Failures propagate so evaluator issues are visible instead of being masked.
"""

from __future__ import annotations

import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field, field_validator

from src.app.config import get_settings
from src.app.core.exceptions import EvaluationError
from src.app.core.llm_helpers import call_and_parse
from src.app.domain.models import ResponseQuality

logger = structlog.get_logger()

_INTERNAL_ERROR_PATTERNS = (
    "traceback (most recent call last)",
    "failed to parse ",
    "response evaluation failed",
    "specialist handler failed",
    "memory retrieval failed",
    "routing failed",
)

_SCHEMA_STYLE_PREFIXES = (
    "classification:",
    "intent:",
    "route:",
    "{",
    "[",
)


class EvaluationResult(BaseModel):
    """Result of evaluating a specialist response."""

    passes: bool = Field(description="Whether the response adequately addresses the intent")
    issue: str = Field(default="", description="Brief description of the issue if it doesn't pass")
    suggestion: str = Field(default="", description="Suggestion for improvement")
    context_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    tool_use_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    final_response_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    grounding: float | None = Field(default=None, ge=0.0, le=1.0)
    channel_style: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("issue", "suggestion", mode="before")
    @classmethod
    def _coerce_nullable_text(cls, value: object) -> str:
        """Treat null rubric fields as empty strings."""
        if value is None:
            return ""
        return str(value)

    def to_quality_record(
        self,
        *,
        route_quality: float | None,
    ) -> ResponseQuality:
        """Convert the evaluator output into the canonical runtime quality record."""
        return ResponseQuality(
            route_quality=route_quality,
            context_quality=self.context_quality,
            tool_use_quality=self.tool_use_quality,
            final_response_quality=self.final_response_quality,
            grounding=self.grounding,
            channel_style=self.channel_style,
            passes=self.passes,
            issue=self.issue,
            suggestion=self.suggestion,
        )


_EVAL_SYSTEM = """\
You are a response quality evaluator for a personal assistant system. Given a user's \
current message and the specialist agent's response, determine whether the response \
adequately addresses the user's intent.

Evaluate:
1. Does the response address what the user actually asked/said in the CURRENT message?
2. Is the response coherent and useful?
3. If context or retrieval appears to be used, is it grounded rather than fabricated?
4. If tools appear to be used, does the response reflect sensible tool usage?
5. Does the response fit the delivery channel?

Do NOT nitpick. Score generously when the response is useful and on-target.

Specialist context (to avoid false failures):
- memory: Returns stored diary entries / notes. A response grounding answer in past \
captures is CORRECT even if the message looks like a standalone topic. Pass it.
- diary: Confirms a capture was logged. Very short responses are CORRECT — this is a \
journaling agent. Pass unless content is completely irrelevant.
- notification: Returns focus mode status or DND info. Terse responses are CORRECT. Pass.
- plan_day: Returns a time-blocked plan. Long structured responses are CORRECT. Pass.

Return JSON with:
- passes: true/false
- issue: brief issue
- suggestion: hint
- context_quality: 0.0-1.0 or null when not applicable
- tool_use_quality: 0.0-1.0 or null when not applicable
- final_response_quality: 0.0-1.0
- grounding: 0.0-1.0 or null when not applicable
- channel_style: 0.0-1.0

Be generous — most responses should pass. Only flag CLEAR mismatches where the response \
is completely off-topic or obviously incorrect."""


async def evaluate_response(
    user_message: str,
    response_content: str,
    specialist: str,
    client: AsyncAnthropic,
    *,
    source: str = "api",
    context_inspection: dict | None = None,
    response_metadata: dict | None = None,
) -> EvaluationResult:
    """Evaluate whether a specialist response addresses the user's intent.

    Returns EvaluationResult on success.
    Evaluator failures propagate so masked quality regressions are visible.
    """
    settings = get_settings()
    response_metadata = response_metadata or {}

    # Extract just the current message — don't feed conversation history to evaluator
    eval_message = user_message
    if "Current message:" in eval_message:
        eval_message = eval_message.split("Current message:")[-1].strip()
    if "[System note:" in eval_message:
        eval_message = eval_message.split("[System note:")[0].strip()

    try:
        result = await call_and_parse(
            client,
            model=settings.classifier_model,  # Haiku — fast and cheap
            max_tokens=settings.evaluator_max_tokens,
            system=_EVAL_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"User message: {eval_message[:300]}\n\n"
                        f"Channel: {source}\n\n"
                        f"Context inspection: {context_inspection or {}}\n\n"
                        f"Response metadata: {response_metadata}\n\n"
                        f"Specialist ({specialist}) response: {response_content[:800]}\n\n"
                        "Does this response adequately address the user's intent?"
                    ),
                }
            ],
            response_model=EvaluationResult,
            error_context="response_evaluation",
            inject_personality=False,  # Evaluator should be objective
        )
    except Exception as exc:
        logger.error("response_evaluation_failed", exc_info=True)
        raise EvaluationError(
            f"Response evaluation failed with {type(exc).__name__}: {exc}",
        ) from exc

    logger.info(
        "response_evaluated",
        passes=result.passes,
        specialist=specialist,
        issue=result.issue[:100] if result.issue else "",
    )
    return result


def evaluate_response_deterministic(
    *,
    user_message: str,
    response_content: str,
    specialist: str,
    source: str = "api",
    context_inspection: dict | None = None,
    response_metadata: dict | None = None,
) -> EvaluationResult:
    """Run cheap, deterministic quality checks on the live request path."""
    del specialist
    response_metadata = response_metadata or {}
    context_inspection = context_inspection or {}

    eval_message = _extract_current_message(user_message)
    cleaned = response_content.strip()
    lowered = cleaned.lower()

    issue = ""
    suggestion = ""
    passes = True
    final_response_quality = 0.9
    channel_style = 1.0
    grounding: float | None = None
    tool_use_quality: float | None = None

    if not cleaned:
        passes = False
        issue = "Assistant returned an empty response."
        suggestion = "Return a direct answer or next action."
        final_response_quality = 0.0
        channel_style = 0.0
    elif any(pattern in lowered for pattern in _INTERNAL_ERROR_PATTERNS):
        passes = False
        issue = "User-visible response leaked an internal failure."
        suggestion = "Replace internal error text with a safe recovery message."
        final_response_quality = 0.0
        channel_style = 0.0
    else:
        if any(lowered.startswith(prefix) for prefix in _SCHEMA_STYLE_PREFIXES):
            channel_style = min(channel_style, 0.45)
            final_response_quality = min(final_response_quality, 0.55)
        if source == "telegram" and any(token in cleaned for token in ("**", "```", "__")):
            channel_style = min(channel_style, 0.6)
        if "?" in eval_message and len(cleaned) < 8:
            final_response_quality = min(final_response_quality, 0.5)

    if response_metadata.get("tool_count"):
        errors = int(response_metadata.get("errors", 0) or 0)
        tool_use_quality = max(0.3, 1.0 - (errors * 0.3)) if errors else 0.95

    if (
        response_metadata.get("source_count")
        or response_metadata.get("citations")
        or int(context_inspection.get("rag_chunks_included", 0) or 0) > 0
    ):
        grounding = 0.9

    return EvaluationResult(
        passes=passes,
        issue=issue,
        suggestion=suggestion,
        context_quality=None,
        tool_use_quality=tool_use_quality,
        final_response_quality=final_response_quality,
        grounding=grounding,
        channel_style=channel_style,
    )


def _extract_current_message(message: str) -> str:
    """Strip assembled context wrappers before deterministic evaluation."""
    current = message
    if "Current message:" in current:
        current = current.split("Current message:")[-1].strip()
    if "[System note:" in current:
        current = current.split("[System note:")[0].strip()
    return current.strip()
