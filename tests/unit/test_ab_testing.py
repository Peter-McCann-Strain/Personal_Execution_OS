"""Tests for sequential A/B testing math — mSPRT, Bayesian, Cliff's delta."""

from __future__ import annotations

import math

import pytest

from src.app.core.ab_testing import (
    bayesian_posterior,
    cliffs_delta,
    detect_non_transitivity,
    frequentist_delta,
    interpret_cliffs_delta,
    position_bias_consistent,
    should_stop,
)

# ---------------------------------------------------------------------------
# Cliff's delta
# ---------------------------------------------------------------------------


def test_cliffs_delta_identical_samples_is_zero() -> None:
    a = [0.5, 0.5, 0.5, 0.5]
    b = [0.5, 0.5, 0.5, 0.5]
    assert cliffs_delta(a, b) == 0.0


def test_cliffs_delta_b_strictly_dominates() -> None:
    # Every b > every a → delta = +1.0
    a = [0.1, 0.2, 0.3]
    b = [0.7, 0.8, 0.9]
    assert cliffs_delta(a, b) == 1.0


def test_cliffs_delta_a_strictly_dominates() -> None:
    a = [0.7, 0.8, 0.9]
    b = [0.1, 0.2, 0.3]
    assert cliffs_delta(a, b) == -1.0


def test_cliffs_delta_partial_overlap_reference() -> None:
    # Reference values from hand calculation:
    # a = [1, 2, 3], b = [2, 3, 4]
    # pairs (a, b): (1,2)+ (1,3)+ (1,4)+ (2,2)0 (2,3)+ (2,4)+ (3,2)- (3,3)0 (3,4)+
    # greater = 6, lesser = 1, n = 9 → (6-1)/9 = 5/9.
    a = [1.0, 2.0, 3.0]
    b = [2.0, 3.0, 4.0]
    assert cliffs_delta(a, b) == pytest.approx(5 / 9)


def test_cliffs_delta_raises_on_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        cliffs_delta([], [0.5])


def test_interpret_cliffs_delta_thresholds() -> None:
    # Romano (2006) thresholds: 0.147 / 0.33 / 0.474.
    assert interpret_cliffs_delta(0.05) == "negligible"
    assert interpret_cliffs_delta(0.2) == "small"
    assert interpret_cliffs_delta(0.4) == "medium"
    assert interpret_cliffs_delta(0.6) == "large"
    # Mirrored for negative direction.
    assert interpret_cliffs_delta(-0.6) == "large"


# ---------------------------------------------------------------------------
# Frequentist mean delta + CI
# ---------------------------------------------------------------------------


def test_frequentist_delta_zero_mean_ci_straddles_zero() -> None:
    # Symmetric deltas around zero → mean ≈ 0 → CI includes 0.
    deltas = [-0.1, 0.1, -0.05, 0.05, -0.1, 0.1, -0.05, 0.05] * 4
    result = frequentist_delta(deltas)
    assert abs(result.mean_delta) < 0.01
    assert not result.ci_excludes_zero
    assert result.ci_lower < 0 < result.ci_upper


def test_frequentist_delta_strong_positive_excludes_zero() -> None:
    # 30 samples each at +0.3 → very tight CI around +0.3 → excludes 0.
    deltas = [0.3] * 30
    result = frequentist_delta(deltas)
    assert result.mean_delta == pytest.approx(0.3)
    # All identical → std = 0 → CI collapses to [0.3, 0.3].
    assert result.ci_lower == pytest.approx(0.3)
    assert result.ci_excludes_zero


def test_frequentist_delta_n_lt_2_returns_inf_ci() -> None:
    # Too few samples → infinite CI, ci_excludes_zero=False.
    result = frequentist_delta([0.5])
    assert math.isinf(result.ci_upper)
    assert math.isinf(result.ci_lower)
    assert not result.ci_excludes_zero


# ---------------------------------------------------------------------------
# Bayesian posterior
# ---------------------------------------------------------------------------


def test_bayesian_posterior_50_50_prior_centred() -> None:
    # No data → Beta(1,1) → P(theta > 0.5) = 0.5.
    result = bayesian_posterior(0, 0)
    assert result.prob_b_better == pytest.approx(0.5, abs=0.01)


def test_bayesian_posterior_strong_b_wins_pushes_above_95() -> None:
    # 20 wins, 0 losses → posterior should be very confident B is better.
    result = bayesian_posterior(20, 0)
    assert result.prob_b_better > 0.95
    assert result.expected_loss < 0.1


def test_bayesian_posterior_strong_a_wins_drops_below_05() -> None:
    result = bayesian_posterior(0, 20)
    assert result.prob_b_better < 0.05


def test_bayesian_posterior_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        bayesian_posterior(-1, 5)


def test_bayesian_posterior_close_to_even_stays_ambiguous() -> None:
    # 11 / 9 → slight edge for B, but posterior shouldn't hit 0.95.
    result = bayesian_posterior(11, 9)
    assert 0.5 < result.prob_b_better < 0.95


# ---------------------------------------------------------------------------
# Stop rule
# ---------------------------------------------------------------------------


def test_should_stop_waits_below_min_n() -> None:
    bayes = bayesian_posterior(10, 0)  # extremely confident
    freq = frequentist_delta([0.5] * 10)
    decision = should_stop(n=10, bayes=bayes, freq=freq, min_n=30, max_n=200)
    assert not decision.stop
    assert decision.verdict == "CONTINUE"
    assert "minimum floor" in decision.reason


def test_should_stop_ships_on_strong_posterior() -> None:
    bayes = bayesian_posterior(35, 0)
    freq = frequentist_delta([0.3] * 35)
    decision = should_stop(n=35, bayes=bayes, freq=freq, min_n=30, max_n=200)
    assert decision.stop
    assert decision.verdict == "SHIP"


def test_should_stop_rejects_on_strong_posterior_against() -> None:
    bayes = bayesian_posterior(0, 35)
    freq = frequentist_delta([-0.3] * 35)
    decision = should_stop(n=35, bayes=bayes, freq=freq, min_n=30, max_n=200)
    assert decision.stop
    assert decision.verdict == "REJECT"


def test_should_stop_inconclusive_at_max_n() -> None:
    # 100 wins vs 100 losses → 50/50 → budget exhausted.
    bayes = bayesian_posterior(100, 100)
    freq = frequentist_delta([0.0] * 200)
    decision = should_stop(n=200, bayes=bayes, freq=freq, min_n=30, max_n=200)
    assert decision.stop
    assert decision.verdict == "INCONCLUSIVE"


def test_should_stop_continue_when_n_above_min_but_below_max_without_signal() -> None:
    # n=40, posterior is middling, CI includes zero.
    bayes = bayesian_posterior(21, 19)
    freq = frequentist_delta([0.01, -0.01] * 20)
    decision = should_stop(n=40, bayes=bayes, freq=freq, min_n=30, max_n=200)
    assert not decision.stop
    assert decision.verdict == "CONTINUE"


def test_should_stop_frequentist_path_ships_on_tight_positive_ci() -> None:
    # 50 samples each +0.2 → std=0 → tight CI → ships via frequentist path
    # even if posterior isn't above 0.95 (though here it will be too).
    bayes = bayesian_posterior(30, 0)
    freq = frequentist_delta([0.2] * 30)
    decision = should_stop(n=30, bayes=bayes, freq=freq, min_n=30, max_n=200)
    assert decision.stop
    assert decision.verdict == "SHIP"


# ---------------------------------------------------------------------------
# Position bias
# ---------------------------------------------------------------------------


def test_position_bias_consistent_both_prefer_b() -> None:
    assert position_bias_consistent("B", "B")


def test_position_bias_consistent_both_prefer_a() -> None:
    assert position_bias_consistent("A", "A")


def test_position_bias_inconsistent_on_flip() -> None:
    # Judge preferred B in (A,B) order but A in (B,A) order — biased.
    assert not position_bias_consistent("B", "A")


def test_position_bias_tie_in_one_ordering_only_is_inconsistent() -> None:
    assert not position_bias_consistent("B", "tie")
    assert not position_bias_consistent("tie", "A")


def test_position_bias_tie_in_both_orderings_is_consistent() -> None:
    assert position_bias_consistent("tie", "tie")


# ---------------------------------------------------------------------------
# Transitivity
# ---------------------------------------------------------------------------


def test_detect_non_transitivity_clean_ordering_has_no_violations() -> None:
    # A>B, B>C, A>C → transitive.
    triples = [("x", "y", "x")]
    violations = detect_non_transitivity(triples)
    assert violations == []


def test_detect_non_transitivity_cycle_detected() -> None:
    # A>B, B>C, C>A → cycle.
    triples = [("x", "y", "z")]
    violations = detect_non_transitivity(triples)
    assert len(violations) == 1


def test_detect_non_transitivity_mirror_cycle_detected() -> None:
    triples = [("y", "z", "x")]
    violations = detect_non_transitivity(triples)
    assert len(violations) == 1
