"""Unit tests for the pure retrieval metrics in ``src/app/core/retrieval_metrics``.

Worked examples to anchor correctness — if any of these break, the formulas
have drifted from the standard IR definitions.
"""

from __future__ import annotations

import math

import pytest

from src.app.core.retrieval_metrics import (
    context_precision,
    mrr,
    ndcg_at_k,
    recall_at_k,
)


class TestNdcgAtK:
    def test_perfect_ranking_yields_one(self) -> None:
        ranked = ["a", "b", "c"]
        relevant = {"a", "b"}
        # DCG = 1/log2(2) + 1/log2(3); IDCG is identical; ratio = 1.
        assert ndcg_at_k(ranked, relevant, k=3) == pytest.approx(1.0)

    def test_relevant_at_position_two_and_four(self) -> None:
        ranked = ["x", "a", "y", "b"]
        relevant = {"a", "b"}
        # DCG@4  = 0 + 1/log2(3) + 0 + 1/log2(5)
        # IDCG@4 = 1/log2(2) + 1/log2(3)
        dcg = (1 / math.log2(3)) + (1 / math.log2(5))
        idcg = (1 / math.log2(2)) + (1 / math.log2(3))
        assert ndcg_at_k(ranked, relevant, k=4) == pytest.approx(dcg / idcg)

    def test_no_relevant_items_returns_zero(self) -> None:
        assert ndcg_at_k(["a", "b"], set(), k=5) == 0.0

    def test_k_zero_returns_zero(self) -> None:
        assert ndcg_at_k(["a"], {"a"}, k=0) == 0.0

    def test_k_larger_than_list_is_safe(self) -> None:
        # Single hit at rank 1, IDCG is also rank-1 only.
        assert ndcg_at_k(["a"], {"a"}, k=99) == pytest.approx(1.0)


class TestMrr:
    def test_first_hit_at_rank_one(self) -> None:
        assert mrr(["a", "b"], {"a"}) == pytest.approx(1.0)

    def test_first_hit_at_rank_three(self) -> None:
        assert mrr(["x", "y", "a", "b"], {"a", "b"}) == pytest.approx(1 / 3)

    def test_no_hit_returns_zero(self) -> None:
        assert mrr(["x", "y"], {"a"}) == 0.0

    def test_hit_beyond_max_rank_returns_zero(self) -> None:
        ranked = ["x"] * 60 + ["a"]  # relevant is at rank 61
        assert mrr(ranked, {"a"}, max_rank=50) == 0.0


class TestRecallAtK:
    def test_full_recall(self) -> None:
        assert recall_at_k(["a", "b", "c"], {"a", "b"}, k=3) == pytest.approx(1.0)

    def test_half_recall(self) -> None:
        assert recall_at_k(["a", "x", "y"], {"a", "b"}, k=3) == pytest.approx(0.5)

    def test_k_smaller_than_relevant_set(self) -> None:
        assert recall_at_k(["a", "b"], {"a", "b", "c"}, k=2) == pytest.approx(2 / 3)

    def test_empty_relevant_returns_zero(self) -> None:
        assert recall_at_k(["a"], set(), k=1) == 0.0


class TestContextPrecision:
    def test_all_relevant(self) -> None:
        assert context_precision(["a", "b"], {"a", "b"}, k=2) == pytest.approx(1.0)

    def test_half_precision(self) -> None:
        assert context_precision(["a", "x"], {"a", "b"}, k=2) == pytest.approx(0.5)

    def test_precision_normalises_by_k_not_returned_len(self) -> None:
        # Only one item returned but k=4 → precision = 1/4, not 1/1.
        assert context_precision(["a"], {"a"}, k=4) == pytest.approx(0.25)

    def test_k_zero_returns_zero(self) -> None:
        assert context_precision(["a"], {"a"}, k=0) == 0.0
