"""RAG faithfulness scoring — is the answer grounded in the retrieved context?

Uses Haiku via the existing ``llm_helpers`` pattern (structured Pydantic
output, retry-with-feedback on parse failures, cost-logged).  Haiku is
explicitly chosen over Sonnet because faithfulness scoring runs over every
golden example in the eval suite and we need to keep the evaluation budget
below the auto-judge's existing ~$3/month envelope.

The judge is asked to:
1. Enumerate the atomic claims in the answer.
2. For each claim, decide whether it is directly supported by the provided
   contexts (NOT by outside knowledge).
3. Report ``supported / total`` — the faithfulness score in ``[0, 1]``.

We fail loudly on malformed output rather than silently returning a default
score — a bad judge run should surface as a CI failure, not a phantom "pass".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field, model_validator

from src.app.core.llm_helpers import call_and_parse_with_retry

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = structlog.get_logger()

# Default model — Haiku.  Kept as a module-level constant so tests can override
# via the ``model`` kwarg without patching internals.
DEFAULT_FAITHFULNESS_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 512


class FaithfulnessReport(BaseModel):
    """Structured output from the faithfulness judge."""

    supported_claims: int = Field(
        ge=0,
        description="Number of atomic claims in the answer that are directly "
        "supported by the provided contexts.",
    )
    total_claims: int = Field(
        ge=0,
        description="Total number of atomic claims in the answer.",
    )
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="supported_claims / total_claims, or 1.0 when "
        "total_claims == 0 (no claims = vacuously faithful).",
    )
    reasoning: str = Field(
        default="",
        description="Short explanation — which claims, if any, were unsupported.",
    )

    @model_validator(mode="after")
    def _check_score_matches(self) -> FaithfulnessReport:
        """Recompute the score from the counts to catch judge arithmetic drift.

        We do NOT trust the judge's reported score — we recompute it from the
        integer counts which are much harder for the model to get wrong.
        """
        if self.total_claims == 0:
            object.__setattr__(self, "score", 1.0)
        else:
            recomputed = self.supported_claims / self.total_claims
            if abs(recomputed - self.score) > 0.01:
                object.__setattr__(self, "score", recomputed)
        if self.supported_claims > self.total_claims:
            msg = (
                f"supported_claims ({self.supported_claims}) exceeds "
                f"total_claims ({self.total_claims})"
            )
            raise ValueError(msg)
        return self


_FAITHFULNESS_SYSTEM = """\
You are a faithfulness evaluator for a Retrieval-Augmented Generation system.

Given an assistant's ANSWER and the CONTEXTS that were retrieved to produce it,
your job is to count how many atomic claims in the answer are directly supported
by the provided contexts.

## Rules

1. Break the answer into atomic factual claims. An atomic claim is a single,
   verifiable proposition (e.g. "The meeting is on Friday" is one claim;
   "The meeting is on Friday at 3pm" is two claims).
2. A claim is SUPPORTED only if it can be verified from the contexts alone.
   Do NOT use outside knowledge. Do NOT accept claims that are merely plausible.
3. Hedging language ("it seems", "possibly") still counts as a claim — evaluate
   whether the hedged proposition is supported.
4. Generic assistant boilerplate ("Let me know if you need more") is NOT a claim
   and should not be counted.
5. Report integer counts — we recompute the final score from them.

Return ONLY valid JSON with this exact schema:
{
  "supported_claims": <int>,
  "total_claims": <int>,
  "score": <float 0-1>,
  "reasoning": "<one short sentence>"
}
"""


async def faithfulness_score(
    answer: str,
    contexts: list[str],
    judge: AsyncAnthropic,
    *,
    model: str = DEFAULT_FAITHFULNESS_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> FaithfulnessReport:
    """Score how faithfully *answer* is grounded in *contexts*.

    Parameters
    ----------
    answer:
        The assistant's response to be scored.
    contexts:
        The retrieved chunks that were supplied to the generator.  Each item
        is rendered to the judge as a numbered context block.
    judge:
        An ``AsyncAnthropic`` client — kept as a parameter (rather than
        instantiated inside) so tests can inject mocks cheaply.
    model:
        Override the default Haiku model (tests may pass a cheap stub).
    max_tokens:
        Upper bound on judge output length.  512 is plenty for the
        four-field JSON payload.

    Returns
    -------
    FaithfulnessReport
        Pydantic model with ``supported_claims``, ``total_claims``, the
        recomputed ``score`` and a short reasoning string.

    Notes
    -----
    * Empty ``answer`` → returns ``score = 1.0`` (nothing to be unfaithful
      about) without calling the LLM, to keep the eval suite cheap.
    * Empty ``contexts`` + non-empty answer → still calls the judge because
      a non-trivial answer with *no* retrieved context is the exact
      pathology we want surfaced.
    """
    if not answer.strip():
        return FaithfulnessReport(
            supported_claims=0,
            total_claims=0,
            score=1.0,
            reasoning="Empty answer — vacuously faithful.",
        )

    rendered_contexts = "\n\n".join(
        f"[Context {i + 1}]\n{chunk.strip()}" for i, chunk in enumerate(contexts)
    )
    if not rendered_contexts:
        rendered_contexts = "(no contexts retrieved)"

    user_message = (
        f"ANSWER:\n{answer.strip()}\n\nCONTEXTS:\n{rendered_contexts}\n\nReturn the JSON report."
    )

    report = await call_and_parse_with_retry(
        judge,
        model=model,
        max_tokens=max_tokens,
        system=_FAITHFULNESS_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
        response_model=FaithfulnessReport,
        error_context="faithfulness_judge",
        inject_personality=False,
    )

    logger.info(
        "faithfulness_score_computed",
        model=model,
        supported=report.supported_claims,
        total=report.total_claims,
        score=report.score,
    )
    return report
