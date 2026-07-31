"""Auto-judge — Haiku-based quality scorer for interaction records.

Scores every interaction on 4 universal dimensions (5-point Likert), plus the
specialist-specific binary sub-checks defined in that agent's rubric.

Universal dimensions (unchanged — Likert 1-5 scaled to 0.0-1.0):
- relevance, actionability, tone, conciseness

Specialist dimensions (new — binary per-check answers, summed per dimension):
- Parsed from ``data/evaluation/rubrics/<agent>.md``
- Each sub-check is Y (True, 1 point) or N (False, 0 points)
- Dimension score = sum of Trues

Does NOT fail-open. Errors propagate so the worker can handle retries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field

from src.app.core.exceptions import EvaluationError
from src.app.core.llm_helpers import call_and_parse_with_retry
from src.app.core.rubric_loader import (
    SpecialistRubric,
    load_specialist_rubric,
    rubric_prompt_snippet,
)
from src.app.domain.models import Specialist

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = structlog.get_logger()


class AutoJudgeScores(BaseModel):
    """Structured output from the auto-judge.

    ``specialist_checks`` is an optional nested mapping keyed by
    ``dimension_key -> {"Q1": bool, "Q2": bool, ...}``. The field is optional
    so agents without a loadable rubric still produce valid scores.
    """

    relevance: float = Field(
        ge=0.0,
        le=1.0,
        description="Does the response address the user's intent?",
    )
    actionability: float = Field(
        ge=0.0,
        le=1.0,
        description="Can the user act on this response?",
    )
    tone: float = Field(
        ge=0.0,
        le=1.0,
        description="Is the tone appropriate for a personal assistant?",
    )
    conciseness: float = Field(
        ge=0.0,
        le=1.0,
        description="Is the response appropriately concise?",
    )
    reasoning: str = Field(description="Brief explanation of the scores")
    specialist_checks: dict[str, dict[str, bool]] = Field(
        default_factory=dict,
        description=(
            "Per-dimension binary sub-check answers keyed by dimension_key "
            "and then by question id (e.g. {'grounding': {'Q1': True, ...}})."
        ),
    )


_UNIVERSAL_INSTRUCTIONS = """\
You are a quality evaluator for a personal AI assistant. Score the assistant's \
response on 4 universal dimensions (each 0.0 to 1.0), plus the specialist binary \
sub-checks listed below.

## Universal Scoring Dimensions (0.0-1.0)

1. **relevance** — Does the response directly address what the user asked or said? \
Score 1.0 for perfectly on-topic, 0.0 for completely irrelevant.

2. **actionability** — Can the user act on the response? For informational queries, \
does it provide the information needed? For tasks, does it confirm what was done? \
Score 1.0 for fully actionable, 0.0 for no actionable content. \
Note: not all messages require actionability (e.g. greetings) — score 0.8+ for \
appropriately low-actionability responses.

3. **tone** — Is the tone appropriate for a personal assistant? Warm but professional, \
not robotic, not overly effusive. Score 1.0 for perfect tone, 0.0 for inappropriate.

4. **conciseness** — Is the response the right length? Not padded with filler, not \
truncated. Score 1.0 for ideal length, 0.0 for extremely verbose or incomplete.

## Rules
- Be calibrated: most good responses should score 0.7-0.9 on each universal dimension.
- Reserve 0.95+ for exceptional responses and below 0.5 for clearly problematic ones.
- The reasoning field should be 1-2 sentences explaining the most notable aspect.
"""


_NO_RUBRIC_OUTPUT_SHAPE = """\
Return JSON with this exact shape:
{"relevance": float, "actionability": float, "tone": float, "conciseness": float, \
"reasoning": "brief explanation", "specialist_checks": {}}\
"""


def _build_system_prompt(rubric: SpecialistRubric | None) -> str:
    """Compose the auto-judge system prompt with specialist-specific binary checks."""
    if rubric is None:
        return f"{_UNIVERSAL_INSTRUCTIONS}\n\n{_NO_RUBRIC_OUTPUT_SHAPE}"

    keys_example = ", ".join(
        f'"{dim.key}": {{"Q1": true, "Q2": false, ...}}' for dim in rubric.dimensions
    )

    return (
        f"{_UNIVERSAL_INSTRUCTIONS}\n\n"
        "## Specialist Binary Sub-Checks\n\n"
        "For each specialist dimension below, answer every sub-check with a strict "
        "true (the claim holds) or false (it does not). Do not hedge. If a check is "
        "genuinely not applicable, answer false with a brief reason in the reasoning "
        "field. These answers must appear in the 'specialist_checks' field keyed by "
        "the dimension key.\n\n"
        f"{rubric_prompt_snippet(rubric)}\n\n"
        "Return JSON with this shape:\n"
        '{"relevance": float, "actionability": float, "tone": float, '
        '"conciseness": float, "reasoning": "brief explanation", '
        f'"specialist_checks": {{{keys_example}}}}}'
    )


def _resolve_rubric(specialist: str) -> SpecialistRubric | None:
    """Return the binary rubric for a specialist or None if unavailable."""
    try:
        enum_value = Specialist(specialist)
    except ValueError:
        return None
    try:
        return load_specialist_rubric(enum_value)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        logger.warning(
            "auto_judge_rubric_unavailable",
            specialist=specialist,
            error=str(exc),
        )
        return None


async def score_interaction(
    client: AsyncAnthropic,
    *,
    model: str,
    max_tokens: int,
    user_message: str,
    response_content: str,
    specialist: str,
) -> AutoJudgeScores:
    """Score a single interaction using the auto-judge.

    Raises EvaluationError on any failure — does NOT fail-open.
    The worker is responsible for retry logic.

    Tags the call with ``purpose="evaluation"`` via structlog contextvars
    so P4.10's cost-alerts worker can split eval spend from product spend.
    The binding is scoped to this function so product LLM calls (ie.
    specialist responses) remain untagged.
    """
    import structlog.contextvars as ctxvars

    rubric = _resolve_rubric(specialist)
    system_prompt = _build_system_prompt(rubric)

    ctxvars.bind_contextvars(purpose="evaluation", eval_component="auto_judge")
    try:
        try:
            scores = await call_and_parse_with_retry(
                client,
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"## User message\n{user_message[:1000]}\n\n"
                            f"## Specialist\n{specialist}\n\n"
                            f"## Assistant response\n{response_content[:2000]}\n\n"
                            "Score this interaction on the universal dimensions and "
                            "the specialist binary sub-checks."
                        ),
                    }
                ],
                response_model=AutoJudgeScores,
                error_context="auto_judge",
                inject_personality=False,
            )
        except Exception as e:
            raise EvaluationError(f"Auto-judge scoring failed: {e}") from e

        logger.info(
            "auto_judge_scored",
            specialist=specialist,
            relevance=scores.relevance,
            actionability=scores.actionability,
            tone=scores.tone,
            conciseness=scores.conciseness,
            specialist_dims=list(scores.specialist_checks.keys()),
        )
        return scores
    finally:
        ctxvars.unbind_contextvars("purpose", "eval_component")


def summarize_specialist_dimensions(
    rubric: SpecialistRubric,
    scores: AutoJudgeScores,
) -> dict[str, dict[str, object]]:
    """Collapse per-check booleans into a dimension summary for persistence.

    Returns a dict keyed by dimension key with ``score`` (int sum of Trues),
    ``max`` (max possible score), ``normalized`` (0.0-1.0), and the raw
    ``checks`` mapping that produced the score.
    """
    summary: dict[str, dict[str, object]] = {}
    for dim in rubric.dimensions:
        raw = scores.specialist_checks.get(dim.key, {})
        answers = {k.upper(): bool(v) for k, v in raw.items()}
        raw_score = dim.score(answers)
        checks = {check.id: bool(answers.get(check.id.upper(), False)) for check in dim.checks}
        summary[dim.key] = {
            "name": dim.name,
            "score": raw_score,
            "max": dim.max_score,
            "normalized": round(raw_score / dim.max_score, 3) if dim.max_score else 0.0,
            "checks": checks,
        }
    return summary


__all__ = [
    "AutoJudgeScores",
    "score_interaction",
    "summarize_specialist_dimensions",
]
