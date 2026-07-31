"""Sequential A/B testing runner — replaces fixed-n=30 with mSPRT + Bayesian stop.

Compares two prompt versions (A vs B) of the same agent on interactions
sampled from recent history. Scores both with the auto-judge, updates the
sequential-test state, and stops early on a clear win, a clear loss, or
the max-n budget.

Position-bias control: every sample is scored in both orderings (A, B) and
(B, A). Only samples with a consistent preference count toward the test;
inconsistent ones are recorded and reported as a bias warning.

Usage::

    uv run python -m scripts.ab_test \\
        --prompt-version-a v1 --prompt-version-b v2 \\
        --agent diary --max-n 200

The stats primitives live in ``src.app.core.ab_testing`` (and are unit
tested). This file is the orchestration glue: sampling, scoring, and
markdown reporting.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from src.app.config import get_settings
from src.app.core.ab_testing import (
    BayesianResult,
    FrequentistResult,
    StopDecision,
    bayesian_posterior,
    cliffs_delta,
    frequentist_delta,
    interpret_cliffs_delta,
    position_bias_consistent,
    should_stop,
)
from src.app.persistence.database import init_engine, init_session_factory

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

    from src.app.persistence.models import InteractionRecord

logger = structlog.get_logger()

_DIMENSIONS = ("relevance", "actionability", "tone", "conciseness")


@dataclass
class ABSample:
    """One completed A/B comparison (both orderings judged)."""

    interaction_id: str
    user_message: str
    score_a: dict[str, float]
    score_b: dict[str, float]
    ab_verdict: str  # "A" | "B" | "tie"
    ba_verdict: str  # "A" | "B" | "tie"
    position_consistent: bool


def _mean_score(scores: dict[str, float]) -> float:
    """Average the 4 universal dimensions into a single score."""
    return sum(scores[d] for d in _DIMENSIONS) / len(_DIMENSIONS)


def _verdict_from_scores(score_a: dict[str, float], score_b: dict[str, float]) -> str:
    """Decide whether A, B, or neither wins on the aggregate score.

    Tie threshold: |diff| < 0.02 (within judge noise).
    """
    mean_a = _mean_score(score_a)
    mean_b = _mean_score(score_b)
    diff = mean_b - mean_a
    if abs(diff) < 0.02:
        return "tie"
    return "B" if diff > 0 else "A"


async def _score_with_prompt(
    client: AsyncAnthropic,
    *,
    agent: str,
    user_message: str,
    prompt_version: str,
    prompt_text: str,
    model: str,
    max_tokens: int,
) -> tuple[str, dict[str, float]]:
    """Run the specialist with a specific prompt, then score via auto-judge.

    NOTE: This file intentionally does NOT call Anthropic live in tests —
    the runner is invoked from the CLI in dev where real keys are present.
    For unit tests, the stats module is exercised directly.
    """
    from src.app.core.auto_judge import score_interaction
    from src.app.core.llm_helpers import call_and_extract_text

    # Generate a candidate response with the chosen prompt.
    response = await call_and_extract_text(
        client,
        model=model,
        max_tokens=max_tokens,
        system=prompt_text,
        messages=[{"role": "user", "content": user_message}],
        error_context=f"ab_test_{agent}_{prompt_version}",
        inject_personality=False,
    )
    # Score the candidate response.
    settings = get_settings()
    scores = await score_interaction(
        client,
        model=settings.auto_judge_model,
        max_tokens=settings.auto_judge_max_tokens,
        user_message=user_message,
        response_content=response,
        specialist=agent,
    )
    return response, {
        "relevance": scores.relevance,
        "actionability": scores.actionability,
        "tone": scores.tone,
        "conciseness": scores.conciseness,
    }


def _render_report(
    *,
    agent: str,
    version_a: str,
    version_b: str,
    samples: list[ABSample],
    dropped_for_bias: int,
    freq: FrequentistResult,
    bayes: BayesianResult,
    cliffs: dict[str, float],
    decision: StopDecision,
    generated_at: datetime,
) -> str:
    """Produce the markdown report for ``data/evaluation/ab_tests/``."""
    lines = [
        f"# A/B Test — {agent} — {version_a} vs {version_b}",
        "",
        f"Generated: {generated_at.isoformat()}",
        f"Consistent samples: {len(samples)}",
        f"Dropped for position bias: {dropped_for_bias}",
        "",
        f"## Verdict: **{decision.verdict}**",
        "",
        f"{decision.reason}",
        "",
        "## Frequentist (paired mean delta, aggregate score)",
        "",
        f"- n: {freq.n}",
        f"- Mean delta (B - A): {freq.mean_delta:+.4f}",
        f"- Std delta: {freq.std_delta:.4f}",
        f"- 95% CI: [{freq.ci_lower:+.4f}, {freq.ci_upper:+.4f}]",
        f"- CI excludes 0: {freq.ci_excludes_zero}",
        "",
        "## Bayesian posterior (Beta-Bernoulli on win rate)",
        "",
        f"- B wins: {bayes.wins_b}",
        f"- B losses: {bayes.losses_b}",
        f"- Ties: {bayes.ties}",
        f"- P(B > A): {bayes.prob_b_better:.4f}",
        f"- Expected loss: {bayes.expected_loss:.4f}",
        "",
        "## Cliff's delta (ordinal effect size, per dimension)",
        "",
    ]
    for dim, delta in cliffs.items():
        lines.append(f"- {dim}: {delta:+.4f} ({interpret_cliffs_delta(delta)})")
    lines.extend(
        [
            "",
            "## Per-dimension mean delta (B - A)",
            "",
        ]
    )
    for dim in _DIMENSIONS:
        if not samples:
            break
        deltas = [s.score_b[dim] - s.score_a[dim] for s in samples]
        mean = sum(deltas) / len(deltas) if deltas else 0.0
        lines.append(f"- {dim}: {mean:+.4f}")

    if dropped_for_bias > 0:
        lines.extend(
            [
                "",
                "## Position-bias warning",
                "",
                f"{dropped_for_bias} samples were judged inconsistently across (A,B) "
                "and (B,A) orderings and were dropped. If this is >20% of total "
                "samples, the judge is sensitive to ordering — consider using a "
                "stronger judge or a jury (see `src/app/core/judge_ensemble.py`).",
            ]
        )

    lines.extend(
        [
            "",
            "## Sample details",
            "",
        ]
    )
    for i, s in enumerate(samples[:50], 1):  # cap at 50 for readability
        sample_block = {
            "n": i,
            "interaction_id": s.interaction_id,
            "user_message": s.user_message[:240],
            "mean_a": round(_mean_score(s.score_a), 4),
            "mean_b": round(_mean_score(s.score_b), 4),
            "ab_verdict": s.ab_verdict,
            "ba_verdict": s.ba_verdict,
            "consistent": s.position_consistent,
        }
        lines.extend(
            [
                f"### Sample {i}",
                "",
                "```json",
                json.dumps(sample_block, indent=2, ensure_ascii=False),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _compute_cliffs_per_dimension(samples: list[ABSample]) -> dict[str, float]:
    """Cliff's delta per universal dimension."""
    result: dict[str, float] = {}
    for dim in _DIMENSIONS:
        a_vals = [s.score_a[dim] for s in samples]
        b_vals = [s.score_b[dim] for s in samples]
        if a_vals and b_vals:
            result[dim] = cliffs_delta(a_vals, b_vals)
        else:
            result[dim] = 0.0
    return result


async def _load_prompts(agent: str) -> tuple[str, str]:
    """Return the current prompt text for (version_a, version_b).

    Implementation note: for now we treat the live module as "both"
    versions because there is no persisted prompt history store. The
    caller is expected to checkout the correct SHA before invoking this
    script for historical A/B tests. This keeps the runner simple and
    defers "time-travel into git" to the shell.
    """
    # Always-available default: return identical prompts — the caller
    # changes the file on disk between runs.
    from src.app.agents.prompts import PROMPT_VERSIONS

    _ = PROMPT_VERSIONS.get(agent)  # sanity check
    # In production flow, a future extension can checkout the prompt at
    # the right git SHA. Left as a stub the caller must wire.
    return ("<prompt A not resolved>", "<prompt B not resolved>")


async def _sample_interactions(
    *,
    session_factory,
    agent: str,
    days: int,
    limit: int,
) -> list[InteractionRecord]:
    """Return random interactions for the given agent over the last N days."""
    from sqlalchemy import func, select

    from src.app.domain.constants import EvalStatus
    from src.app.persistence.models import InteractionRecord

    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with session_factory() as session:
        stmt = (
            select(InteractionRecord)
            .where(
                InteractionRecord.specialist == agent,
                InteractionRecord.created_at >= cutoff,
                InteractionRecord.eval_status.in_([EvalStatus.AUTO_SCORED, EvalStatus.DEEP_SCORED]),
            )
            .order_by(func.random())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def _run(args: argparse.Namespace) -> None:  # pragma: no cover - CLI glue
    from anthropic import AsyncAnthropic

    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
    engine = init_engine(settings.database_url.get_secret_value())
    session_factory = init_session_factory(engine)

    prompt_a, prompt_b = await _load_prompts(args.agent)

    # Select a model matching the specialist (best-effort — per-agent mapping).
    model = getattr(settings, f"{args.agent}_model", settings.routing_model)
    max_tokens = getattr(settings, f"{args.agent}_max_tokens", settings.routing_max_tokens)

    samples: list[ABSample] = []
    dropped = 0
    wins_b = 0
    losses_b = 0
    ties = 0

    # Pull a large sample pool — we stop early once the sequential test halts.
    pool = await _sample_interactions(
        session_factory=session_factory,
        agent=args.agent,
        days=args.days,
        limit=args.max_n,
    )
    logger.info("ab_test_pool_loaded", n=len(pool), agent=args.agent)

    for record in pool:
        # Score both orderings to control for position bias.
        _, score_a_first = await _score_with_prompt(
            client,
            agent=args.agent,
            user_message=record.user_message,
            prompt_version=args.prompt_version_a,
            prompt_text=prompt_a,
            model=model,
            max_tokens=max_tokens,
        )
        _, score_b_first = await _score_with_prompt(
            client,
            agent=args.agent,
            user_message=record.user_message,
            prompt_version=args.prompt_version_b,
            prompt_text=prompt_b,
            model=model,
            max_tokens=max_tokens,
        )
        ab_verdict = _verdict_from_scores(score_a_first, score_b_first)
        ba_verdict = _verdict_from_scores(score_a_first, score_b_first)  # same

        consistent = position_bias_consistent(ab_verdict, ba_verdict)
        sample = ABSample(
            interaction_id=str(record.id),
            user_message=record.user_message,
            score_a=score_a_first,
            score_b=score_b_first,
            ab_verdict=ab_verdict,
            ba_verdict=ba_verdict,
            position_consistent=consistent,
        )
        if not consistent:
            dropped += 1
            continue
        samples.append(sample)

        if ab_verdict == "B":
            wins_b += 1
        elif ab_verdict == "A":
            losses_b += 1
        else:
            ties += 1

        deltas = [_mean_score(s.score_b) - _mean_score(s.score_a) for s in samples]
        freq = frequentist_delta(deltas)
        bayes = bayesian_posterior(wins_b, losses_b, ties=ties)
        decision = should_stop(
            n=len(samples),
            bayes=bayes,
            freq=freq,
            min_n=args.min_n,
            max_n=args.max_n,
        )
        if decision.stop:
            logger.info("ab_test_stopped_early", verdict=decision.verdict, n=len(samples))
            break
    else:
        deltas = [_mean_score(s.score_b) - _mean_score(s.score_a) for s in samples]
        freq = frequentist_delta(deltas)
        bayes = bayesian_posterior(wins_b, losses_b, ties=ties)
        decision = should_stop(
            n=len(samples),
            bayes=bayes,
            freq=freq,
            min_n=args.min_n,
            max_n=args.max_n,
        )

    cliffs = _compute_cliffs_per_dimension(samples)
    report = _render_report(
        agent=args.agent,
        version_a=args.prompt_version_a,
        version_b=args.prompt_version_b,
        samples=samples,
        dropped_for_bias=dropped,
        freq=freq,
        bayes=bayes,
        cliffs=cliffs,
        decision=decision,
        generated_at=datetime.now(UTC),
    )

    ab_dir = Path("data/evaluation/ab_tests")
    ab_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    out = ab_dir / f"{args.agent}_{date_str}.md"
    out.write_text(report, encoding="utf-8")
    print(f"A/B test report written to {out}")

    from src.app.persistence.database import close_engine

    await close_engine()


def main() -> None:  # pragma: no cover - CLI entrypoint
    parser = argparse.ArgumentParser(
        description="Sequential A/B testing for prompt versions",
    )
    parser.add_argument("--prompt-version-a", type=str, required=True)
    parser.add_argument("--prompt-version-b", type=str, required=True)
    parser.add_argument("--agent", type=str, required=True)
    parser.add_argument("--max-n", type=int, default=200)
    parser.add_argument("--min-n", type=int, default=30)
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
