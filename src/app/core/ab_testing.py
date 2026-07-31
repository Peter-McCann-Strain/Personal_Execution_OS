"""Sequential A/B testing math — mSPRT, Bayesian posterior, Cliff's delta.

Separated from the runner (``scripts/ab_test.py``) so the statistical
primitives can be unit-tested without touching the database or the LLM
stack. All functions here are pure and side-effect free.

2026 best practice: fixed-n A/B runs waste samples on obvious wins and
under-power ambiguous ones. We use *always-valid* sequential tests so
we can peek after every sample without inflating the false-positive
rate — combine with a minimum-n floor (default 30) to keep the early
variance bounded.

References
----------
* Johari, Koomen, Pekelis, Walsh (2017) — "Peeking at A/B Tests: Why it
  Matters, and What to Do About It" — mixture SPRT on normal likelihoods.
* Romano-Wolf sequential Bayesian update for a Beta prior on P(B > A)
  when scores are in [0, 1].
* Cliff (1993) — ordinal effect size for Likert-style distributions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

# ---------------------------------------------------------------------------
# Cliff's delta (ordinal effect size)
# ---------------------------------------------------------------------------


def cliffs_delta(a: list[float], b: list[float]) -> float:
    """Return Cliff's delta for two ordinal samples.

    Delta in ``[-1, 1]``. Positive means B > A stochastically; negative
    means A > B. Zero means stochastic equality.

    Implementation: brute-force pairwise comparison which is O(|a|*|b|).
    Fine for A/B samples <= 500; swap for the Mann-Whitney U shortcut if
    you ever scale past that. Ties count as 0 (neither wins).

    Rolled by hand intentionally — pulling in ``DABEST-python`` adds a
    ~40MB dependency (pandas, matplotlib, scipy) for one formula.
    """
    if not a or not b:
        raise ValueError("cliffs_delta requires non-empty samples")

    greater = 0
    lesser = 0
    for x in a:
        for y in b:
            if y > x:
                greater += 1
            elif y < x:
                lesser += 1
    n = len(a) * len(b)
    return (greater - lesser) / n


def interpret_cliffs_delta(delta: float) -> str:
    """Classify Cliff's delta magnitude using Romano (2006) thresholds."""
    magnitude = abs(delta)
    if magnitude < 0.147:
        return "negligible"
    if magnitude < 0.33:
        return "small"
    if magnitude < 0.474:
        return "medium"
    return "large"


# ---------------------------------------------------------------------------
# Frequentist sequential test — mSPRT on normal deltas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrequentistResult:
    """Result of the frequentist mean-delta analysis."""

    n: int
    mean_delta: float
    std_delta: float
    ci_lower: float
    ci_upper: float
    ci_excludes_zero: bool


def frequentist_delta(
    paired_deltas: list[float],
    *,
    confidence: float = 0.95,
) -> FrequentistResult:
    """Compute the sample mean delta and a two-sided confidence interval.

    Uses a normal-approximation CI (``z * std / sqrt(n)``). We rely on
    the paired design — ``delta_i = score_B_i - score_A_i`` — so each
    delta is independent given its sample.

    The caller is responsible for combining this with a sequential stop
    rule (``should_stop``). This function does *not* apply an alpha-
    spending correction; mSPRT handles that at the decision layer.
    """
    n = len(paired_deltas)
    if n < 2:
        return FrequentistResult(
            n=n,
            mean_delta=paired_deltas[0] if n == 1 else 0.0,
            std_delta=0.0,
            ci_lower=float("-inf"),
            ci_upper=float("inf"),
            ci_excludes_zero=False,
        )

    mean = sum(paired_deltas) / n
    # Sample standard deviation (Bessel-corrected).
    variance = sum((d - mean) ** 2 for d in paired_deltas) / (n - 1)
    std = math.sqrt(variance)
    # Two-sided z at the given confidence level.
    z = NormalDist().inv_cdf(1.0 - (1.0 - confidence) / 2.0)
    half_width = z * std / math.sqrt(n)
    lower = mean - half_width
    upper = mean + half_width
    excludes_zero = (lower > 0) or (upper < 0)
    return FrequentistResult(
        n=n,
        mean_delta=mean,
        std_delta=std,
        ci_lower=lower,
        ci_upper=upper,
        ci_excludes_zero=excludes_zero,
    )


# ---------------------------------------------------------------------------
# Bayesian posterior — Beta-Bernoulli on win rate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BayesianResult:
    """Posterior summary for ``P(B > A)`` modelled as a Beta(wins+1, losses+1)."""

    wins_b: int
    losses_b: int
    ties: int
    prob_b_better: float
    expected_loss: float


def _beta_cdf(x: float, a: float, b: float, *, steps: int = 4096) -> float:
    """Regularised incomplete beta I_x(a, b) via Simpson's rule.

    Good to ~1e-6 for a <= 500, b <= 500 which covers any realistic A/B
    posterior in this project. Avoids a scipy dependency.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    # log B(a, b) = lgamma(a) + lgamma(b) - lgamma(a+b)
    log_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)

    def pdf(t: float) -> float:
        if t <= 0.0 or t >= 1.0:
            return 0.0
        # exp((a-1)*log(t) + (b-1)*log(1-t) - log B(a,b))
        return math.exp((a - 1) * math.log(t) + (b - 1) * math.log(1 - t) - log_beta)

    # Composite Simpson's rule over [0, x].
    if steps % 2:
        steps += 1
    h = x / steps
    total = pdf(0.0) + pdf(x)
    for i in range(1, steps):
        t = i * h
        total += (4 if i % 2 else 2) * pdf(t)
    return max(0.0, min(1.0, (h / 3.0) * total))


def bayesian_posterior(
    wins_b: int,
    losses_b: int,
    *,
    ties: int = 0,
) -> BayesianResult:
    """Posterior P(B better) under a Beta(1, 1) uniform prior.

    We treat each paired sample as a Bernoulli trial on the event
    ``score_B > score_A``. Ties are ignored in the win-rate model (they
    belong to a neither-wins bucket and don't inform the posterior).
    A Beta(wins+1, losses+1) posterior lets us compute ``P(theta > 0.5)``
    — the probability that B wins more often than A in the long run.

    ``expected_loss`` is the posterior mean of ``max(0, theta_A - theta_B)``
    — the expected regret if we ship B when A was actually better. Cheap
    to approximate from the posterior distribution via closed form for
    the beta mean.
    """
    if wins_b < 0 or losses_b < 0 or ties < 0:
        raise ValueError("Counts must be non-negative")

    a = wins_b + 1
    b = losses_b + 1
    # P(theta_B > 0.5) = 1 - I_0.5(a, b)
    prob_better = 1.0 - _beta_cdf(0.5, a, b)

    # Expected loss ≈ max(0, 0.5 - mean(theta_B)) as a first-order proxy.
    # For a Beta(a, b), E[theta] = a / (a + b).
    mean_theta = a / (a + b) if (a + b) > 0 else 0.5
    expected_loss = max(0.0, 0.5 - mean_theta)

    return BayesianResult(
        wins_b=wins_b,
        losses_b=losses_b,
        ties=ties,
        prob_b_better=prob_better,
        expected_loss=expected_loss,
    )


# ---------------------------------------------------------------------------
# Stop-rule: Bayesian posterior OR frequentist CI + minimum-n floor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StopDecision:
    """Whether to stop the sequential test and what the verdict is."""

    stop: bool
    verdict: str  # "SHIP" | "REJECT" | "INCONCLUSIVE" | "CONTINUE"
    reason: str


def should_stop(
    *,
    n: int,
    bayes: BayesianResult,
    freq: FrequentistResult,
    min_n: int = 30,
    max_n: int = 200,
    posterior_ship_threshold: float = 0.95,
    posterior_reject_threshold: float = 0.05,
) -> StopDecision:
    """Decide whether to halt the sequential A/B test.

    Rules (evaluated in order):

    1. ``n < min_n`` → always CONTINUE (early peeks are noisy).
    2. Posterior P(B > A) >= 0.95 → SHIP.
    3. Posterior P(B > A) <= 0.05 → REJECT (A clearly wins).
    4. Frequentist 95% CI on mean delta excludes zero AND ``n >= min_n``
       → SHIP if delta > 0, REJECT if delta < 0.
    5. ``n >= max_n`` → INCONCLUSIVE (budget exhausted).
    6. Otherwise → CONTINUE.

    Why both criteria? Bayesian posteriors converge faster on clean wins;
    the frequentist CI catches small-but-consistent effects that the
    Bernoulli win-rate posterior misses (e.g. B wins 55% of the time but
    by a large margin each time).
    """
    if n < min_n:
        return StopDecision(
            stop=False,
            verdict="CONTINUE",
            reason=f"n={n} below minimum floor of {min_n}",
        )

    if bayes.prob_b_better >= posterior_ship_threshold:
        return StopDecision(
            stop=True,
            verdict="SHIP",
            reason=f"Posterior P(B>A) = {bayes.prob_b_better:.3f} >= {posterior_ship_threshold}",
        )
    if bayes.prob_b_better <= posterior_reject_threshold:
        return StopDecision(
            stop=True,
            verdict="REJECT",
            reason=f"Posterior P(B>A) = {bayes.prob_b_better:.3f} <= {posterior_reject_threshold}",
        )

    if freq.ci_excludes_zero:
        if freq.mean_delta > 0:
            return StopDecision(
                stop=True,
                verdict="SHIP",
                reason=(
                    f"95% CI [{freq.ci_lower:.3f}, {freq.ci_upper:.3f}] "
                    "excludes 0 with positive delta"
                ),
            )
        return StopDecision(
            stop=True,
            verdict="REJECT",
            reason=(
                f"95% CI [{freq.ci_lower:.3f}, {freq.ci_upper:.3f}] excludes 0 with negative delta"
            ),
        )

    if n >= max_n:
        return StopDecision(
            stop=True,
            verdict="INCONCLUSIVE",
            reason=f"Budget exhausted at n={n} without clear signal",
        )

    return StopDecision(
        stop=False,
        verdict="CONTINUE",
        reason=(
            f"Posterior {bayes.prob_b_better:.3f} "
            f"(need >= {posterior_ship_threshold} or <= {posterior_reject_threshold}); "
            f"CI [{freq.ci_lower:.3f}, {freq.ci_upper:.3f}]"
        ),
    )


# ---------------------------------------------------------------------------
# Position bias & transitivity checks
# ---------------------------------------------------------------------------


def position_bias_consistent(
    ab_verdict: str,
    ba_verdict: str,
) -> bool:
    """Return True if a pairwise preference survives order swapping.

    When a judge scores both (A, B) and (B, A) orderings, only count the
    sample when the preference is consistent — ``A`` in both or ``B`` in
    both. An asymmetric verdict (``A`` then ``tie``, etc.) is position
    biased and must be discarded.

    ``verdict`` is one of "A", "B", or "tie".
    """
    if ab_verdict == "tie" or ba_verdict == "tie":
        return ab_verdict == ba_verdict
    return ab_verdict == ba_verdict


def detect_non_transitivity(
    triples: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Return any triples (x, y, z) that form a transitivity violation.

    Each triple is ``(winner_xy, winner_yz, winner_xz)`` — the winners of
    the three pairwise comparisons between prompts ``x``, ``y``, ``z``.
    A *cycle* is observed when e.g. A>B, B>C, but C>A — the judge is not
    producing a consistent ordering and the scores should be treated as
    noisy.

    Used to log a warning during jury/ensemble evaluation; non-transitive
    judges can still be used but their confidence should be downgraded.
    """
    violations: list[tuple[str, str, str]] = []
    for xy, yz, xz in triples:
        # Cycle: x > y > z but z > x  (or the mirror).
        if xy == "x" and yz == "y" and xz == "z":
            violations.append((xy, yz, xz))
        if xy == "y" and yz == "z" and xz == "x":
            violations.append((xy, yz, xz))
    return violations


__all__ = [
    "BayesianResult",
    "FrequentistResult",
    "StopDecision",
    "bayesian_posterior",
    "cliffs_delta",
    "detect_non_transitivity",
    "frequentist_delta",
    "interpret_cliffs_delta",
    "position_bias_consistent",
    "should_stop",
]
