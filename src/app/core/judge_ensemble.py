"""Judge ensembles — jury voting + self-consistency for robust eval scoring.

Single-judge runs have ~25% disagreement on hard cases (Anthropic & DeepMind
benchmarks, 2025). Two mitigations:

* **Self-consistency** — the same model, same rubric, N samples at temp=0.3,
  take the median. Cheap. Used for daily auto-judge traffic where we just
  want the noise floor down.
* **Jury** — 3 independent model configurations score the same interaction,
  then majority-vote the verdict and average the numeric scores. More
  expensive (~3x). Used for GATE decisions: A/B rollout, calibration
  against golden sets, prompt-version promotion.

Cost-ceiling impact: every call here is tagged ``purpose="evaluation"`` via
the structlog contextvars so the cost-alerts worker (P4.10) can split eval
spend from product spend.

Design choices
--------------

* No new Anthropic client — reuse ``score_interaction`` from ``auto_judge``.
  Every jury member is just another call with a different (model, temp) pair.
* Aggregation happens on the *numeric* scores per dimension, not on a single
  verdict — callers can decide their own threshold. The aggregate result
  also carries a ``disagreement`` flag for observability.
* Self-consistency median is implemented as ``statistics.median`` which is
  robust to a single outlier (N=3 → middle value wins).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import structlog

from src.app.core.auto_judge import AutoJudgeScores, score_interaction

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeConfig:
    """One member of a jury or self-consistency sample set."""

    model: str
    temperature: float = 0.1
    label: str = ""  # human-readable tag for logs (e.g. "sonnet-4-6-t0.1")

    def slug(self) -> str:
        """Return a stable label for logging / aggregation keys."""
        return self.label or f"{self.model}-t{self.temperature}"


@dataclass
class JuryScore:
    """Result of an ensemble run (jury or self-consistency)."""

    mode: Literal["jury", "self_consistency"]
    members: list[JudgeConfig]
    per_member_scores: list[AutoJudgeScores] = field(default_factory=list)
    aggregated: AutoJudgeScores | None = None
    verdict: str = "neutral"  # "pass" | "fail" | "neutral"
    disagreement: bool = False
    notes: str = ""

    def mean_score(self) -> float:
        """Aggregated mean of the 4 universal dimensions."""
        if self.aggregated is None:
            raise ValueError("JuryScore not aggregated yet")
        dims = (
            self.aggregated.relevance,
            self.aggregated.actionability,
            self.aggregated.tone,
            self.aggregated.conciseness,
        )
        return sum(dims) / len(dims)


# ---------------------------------------------------------------------------
# Aggregators
# ---------------------------------------------------------------------------


def aggregate_median(scores: list[AutoJudgeScores]) -> AutoJudgeScores:
    """Take the median per dimension — robust to one outlier in N=3.

    Used by self-consistency: same model, same rubric, different temp-0.3
    samples. A single judge flub (wrong JSON, one hallucinated dimension)
    won't move the median.
    """
    if not scores:
        raise ValueError("Cannot aggregate empty score list")
    return AutoJudgeScores(
        relevance=statistics.median(s.relevance for s in scores),
        actionability=statistics.median(s.actionability for s in scores),
        tone=statistics.median(s.tone for s in scores),
        conciseness=statistics.median(s.conciseness for s in scores),
        reasoning=_join_reasoning(scores, label="median"),
    )


def aggregate_mean(scores: list[AutoJudgeScores]) -> AutoJudgeScores:
    """Arithmetic mean per dimension — used by jury mode.

    Jury members use different models (e.g. sonnet-4-6 @ t=0.1,
    sonnet-4-6 @ t=0.3, haiku-4-5 @ thinking). The mean captures the
    overall signal without being dominated by one member.
    """
    if not scores:
        raise ValueError("Cannot aggregate empty score list")
    n = len(scores)
    return AutoJudgeScores(
        relevance=sum(s.relevance for s in scores) / n,
        actionability=sum(s.actionability for s in scores) / n,
        tone=sum(s.tone for s in scores) / n,
        conciseness=sum(s.conciseness for s in scores) / n,
        reasoning=_join_reasoning(scores, label="mean"),
    )


def majority_verdict(
    scores: list[AutoJudgeScores],
    *,
    pass_threshold: float = 0.7,
) -> tuple[str, bool]:
    """Return (verdict, disagreement) from a jury's per-member scores.

    Each member "votes" ``pass`` when its aggregate score >= threshold.
    Majority wins; disagreement is True if the members split (i.e. not
    all members agreed).
    """
    if not scores:
        return ("neutral", False)
    votes: list[str] = []
    for s in scores:
        agg = (s.relevance + s.actionability + s.tone + s.conciseness) / 4
        votes.append("pass" if agg >= pass_threshold else "fail")
    pass_count = votes.count("pass")
    fail_count = votes.count("fail")
    disagreement = pass_count > 0 and fail_count > 0
    if pass_count > fail_count:
        return ("pass", disagreement)
    if fail_count > pass_count:
        return ("fail", disagreement)
    return ("neutral", disagreement)


def _join_reasoning(scores: list[AutoJudgeScores], *, label: str) -> str:
    """Concatenate each member's reasoning for audit trails."""
    parts = [f"[{label} of {len(scores)}]"]
    for i, s in enumerate(scores):
        parts.append(f"#{i + 1}: {s.reasoning}")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def ensemble_score(
    client: AsyncAnthropic,
    *,
    user_message: str,
    response_content: str,
    specialist: str,
    mode: Literal["jury", "self_consistency"],
    members: list[JudgeConfig],
    max_tokens: int = 512,
    pass_threshold: float = 0.7,
) -> JuryScore:
    """Run an ensemble of judges against one interaction.

    Each member is a ``JudgeConfig``. Results are aggregated:

    * ``mode="jury"`` → arithmetic mean per dimension + majority-vote verdict.
    * ``mode="self_consistency"`` → median per dimension; verdict falls back
      to comparing the median aggregate against ``pass_threshold``.

    Every call is tagged ``purpose="evaluation"`` via ``structlog.contextvars``
    so P4.10 can split eval cost from product cost downstream. The tag is
    applied here (not inside ``score_interaction``) so ordinary auto-judge
    runs aren't accidentally tagged as evaluation spend.
    """
    if not members:
        raise ValueError("ensemble_score requires at least one member")

    per_member: list[AutoJudgeScores] = []
    # Bind `purpose="evaluation"` into the structlog contextvars so every
    # llm_call_success log line in this scope carries the tag.
    import structlog.contextvars as ctxvars

    ctxvars.bind_contextvars(purpose="evaluation", ensemble_mode=mode)
    try:
        for member in members:
            scores = await score_interaction(
                client,
                model=member.model,
                max_tokens=max_tokens,
                user_message=user_message,
                response_content=response_content,
                specialist=specialist,
            )
            logger.info(
                "judge_ensemble_member_scored",
                member=member.slug(),
                mode=mode,
                aggregate=round(
                    (scores.relevance + scores.actionability + scores.tone + scores.conciseness)
                    / 4,
                    4,
                ),
            )
            per_member.append(scores)
    finally:
        ctxvars.unbind_contextvars("purpose", "ensemble_mode")

    if mode == "self_consistency":
        aggregated = aggregate_median(per_member)
        agg_mean = (
            aggregated.relevance
            + aggregated.actionability
            + aggregated.tone
            + aggregated.conciseness
        ) / 4
        verdict = "pass" if agg_mean >= pass_threshold else "fail"
        disagreement = _pairs_disagree(per_member, pass_threshold)
    else:  # jury
        aggregated = aggregate_mean(per_member)
        verdict, disagreement = majority_verdict(per_member, pass_threshold=pass_threshold)

    result = JuryScore(
        mode=mode,
        members=list(members),
        per_member_scores=per_member,
        aggregated=aggregated,
        verdict=verdict,
        disagreement=disagreement,
    )
    logger.info(
        "judge_ensemble_aggregated",
        mode=mode,
        verdict=verdict,
        disagreement=disagreement,
        aggregate_score=round(result.mean_score(), 4),
    )
    return result


def _pairs_disagree(
    scores: list[AutoJudgeScores],
    pass_threshold: float,
) -> bool:
    """Return True if any pair of scores would produce opposite verdicts."""
    verdicts: list[str] = []
    for s in scores:
        agg = (s.relevance + s.actionability + s.tone + s.conciseness) / 4
        verdicts.append("pass" if agg >= pass_threshold else "fail")
    return len(set(verdicts)) > 1


__all__ = [
    "JudgeConfig",
    "JuryScore",
    "aggregate_mean",
    "aggregate_median",
    "ensemble_score",
    "majority_verdict",
]
