"""Pure retrieval-quality metrics — no external deps, fully unit-testable.

These functions implement the standard IR formulas used in the RAG-quality
literature.  They operate on simple primitive types so they can be plugged
into any retriever regardless of its backend (BM25, pgvector, hybrid, …).

Definitions
-----------
nDCG@k :
    Discounted Cumulative Gain at cut-off *k*, normalised by the Ideal DCG.
    Uses binary relevance (rel ∈ {0, 1}) and the standard
    ``rel_i / log2(i + 1)`` gain.  Position index *i* is 1-based.
MRR :
    Mean Reciprocal Rank of the **first** relevant item.  Operates on a
    single ranked list here (caller aggregates across queries).  Returns 0
    when no relevant item is found in the top *max_rank* positions
    (default 50, matching the ``k=50`` safety window specified by P2.3).
Recall@k :
    ``|retrieved ∩ relevant| / |relevant|``.
Context Precision :
    ``|retrieved ∩ relevant| / k`` — assesses how much of the returned
    context is actually on-topic.  This is the classic "precision@k" formula
    used by RAGAS when restricted to binary relevance.

All functions tolerate empty inputs by returning 0.0 rather than raising.
Duplicate document ids in *ranked_ids* are preserved — callers are expected
to de-duplicate upstream if that matches their semantics.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

__all__ = [
    "context_precision",
    "mrr",
    "ndcg_at_k",
    "recall_at_k",
]


def _truncate(ranked_ids: Iterable[str], k: int) -> list[str]:
    """Return the first *k* items of *ranked_ids* as a list.

    ``k`` values <= 0 yield an empty list.
    """
    if k <= 0:
        return []
    return list(ranked_ids)[:k]


def ndcg_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Normalised Discounted Cumulative Gain at *k*.

    ``DCG@k = sum_{i=1..k} rel_i / log2(i + 1)``

    ``IDCG@k`` places all relevant items at the top of the list, which — for
    binary relevance — is simply the DCG of ``min(|relevant_ids|, k)`` ones.

    Returns 0.0 when there are no relevant items (IDCG is zero so nDCG is
    undefined; the convention used across the RAGAS / BEIR literature is
    to return 0 in that case).
    """
    if k <= 0 or not relevant_ids:
        return 0.0

    top_k = _truncate(ranked_ids, k)
    dcg = 0.0
    for i, doc_id in enumerate(top_k, start=1):
        if doc_id in relevant_ids:
            dcg += 1.0 / math.log2(i + 1)

    # IDCG: |relevant_ids| hits in the top slots, capped at k.
    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    if idcg == 0.0:
        return 0.0

    return dcg / idcg


def mrr(
    ranked_ids: list[str],
    relevant_ids: set[str],
    max_rank: int = 50,
) -> float:
    """Reciprocal rank of the first relevant item in *ranked_ids*.

    Only inspects the first *max_rank* positions (default 50 as per P2.3's
    "k=50 for safety" window).  Returns 0.0 when no relevant item appears
    in that window.
    """
    if not relevant_ids or max_rank <= 0:
        return 0.0

    for i, doc_id in enumerate(ranked_ids[:max_rank], start=1):
        if doc_id in relevant_ids:
            return 1.0 / i
    return 0.0


def recall_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Recall at cut-off *k*: ``|ret ∩ rel| / |rel|``.

    Returns 0.0 when there are no relevant items (division-by-zero guard).
    """
    if k <= 0 or not relevant_ids:
        return 0.0
    top_k = set(_truncate(ranked_ids, k))
    return len(top_k & relevant_ids) / len(relevant_ids)


def context_precision(
    ranked_ids: list[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    """Precision at cut-off *k*: ``|ret ∩ rel| / k``.

    We normalise by *k* (not by ``len(ranked_ids)``) so the metric is
    comparable across runs where the retriever returns fewer than *k*
    results.  Returns 0.0 if ``k <= 0``.
    """
    if k <= 0:
        return 0.0
    top_k = set(_truncate(ranked_ids, k))
    return len(top_k & relevant_ids) / k
