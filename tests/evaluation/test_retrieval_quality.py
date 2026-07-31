"""Parametrised RAG retrieval-quality suite.

What this actually does (read carefully before changing)
---------------------------------------------------------
* Iterates the 13 golden datasets in ``data/evaluation/datasets/*.v1.json``.
* For each case, builds a **tiny synthetic corpus** of ~6 documents keyed to
  the case's salient tokens (``expected_fragments`` when present, otherwise
  content words from ``prompt``), plus a handful of distractors.
* Runs a deterministic in-memory lexical retriever that ranks documents by
  overlap with the query — this is a proxy for the real hybrid BM25+vector
  pipeline.  The **point** of this test is to exercise the metric plumbing
  and baseline-comparison logic, not to regression-test the real retriever.
* When ``USE_REAL_PGVECTOR=1`` is set **and** the P2.1 ``postgres_container``
  fixture has been extended to seed the ``episodes`` table, this file will
  swap the fake retriever for ``hybrid_search``.  Until then it skips with
  a clear message.
* Computes all five CI-gating metrics (nDCG@10, MRR, Recall@10, Context
  Precision@10, Faithfulness) and asserts each is within the baseline's
  regression budget.

The faithfulness judge is **stubbed** here (never reaches Anthropic) — see
``tests/evaluation/test_retrieval_faithfulness.py`` for the real judge path
covered with an ``AsyncMock``.

Caveats
-------
* The synthetic corpus approach means these scores are *bounded* by the
  synthetic corpus's structure, not by the real retriever's behaviour.
  The baselines in ``data/evaluation/baselines/retrieval.json`` reflect
  that — they're calibrated against this harness, not production recall.
* Once P2.1's real-pgvector fixture lands, regenerate baselines with
  ``uv run python -m scripts.retrieval_report --write-baseline``.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from src.app.core.retrieval_metrics import (
    context_precision,
    mrr,
    ndcg_at_k,
    recall_at_k,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = REPO_ROOT / "data" / "evaluation" / "datasets"
BASELINE_PATH = REPO_ROOT / "data" / "evaluation" / "baselines" / "retrieval.json"

K = 10  # cut-off used for @k metrics throughout
MAX_REGRESSION_DEFAULT = 0.03  # 3% — matches CLAUDE.md's quality envelope

# Stopwords kept tiny on purpose — just enough to stop "a/the/is" dominating
# the salience extractor below.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "do",
        "does",
        "for",
        "from",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "so",
        "that",
        "the",
        "then",
        "this",
        "to",
        "too",
        "was",
        "we",
        "were",
        "what",
        "when",
        "why",
        "will",
        "with",
        "you",
        "your",
        "am",
        "not",
        "no",
        "yes",
        "best",
        "please",
    },
)


# ---------------------------------------------------------------------------
# Dataset loading + normalisation
# ---------------------------------------------------------------------------


def _load_datasets() -> list[tuple[str, dict[str, Any]]]:
    """Return ``(dataset_id, dataset_dict)`` for every ``*.v1.json`` golden."""
    out: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(DATASETS_DIR.glob("*.v1.json")):
        data = json.loads(path.read_text())
        out.append((path.stem, data))
    return out


def _iter_cases(dataset: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield normalised case dicts regardless of which schema the file uses."""
    for raw in dataset.get("cases", []):
        prompt = raw.get("prompt") or ""
        # memory_equivalence uses message lists; flatten to a prompt string.
        if not prompt and raw.get("messages"):
            prompt = " ".join(
                m.get("content", "") for m in raw["messages"] if m.get("role") == "user"
            )
        # assistant_native_continuity uses message_content instead of prompt.
        if not prompt:
            prompt = raw.get("message_content") or raw.get("description") or ""
        yield {
            "id": raw.get("id", "<unknown>"),
            "prompt": prompt,
            "expected_fragments": [f.lower() for f in raw.get("expected_fragments", [])],
            "summary": raw.get("conversation_summary", ""),
        }


# ---------------------------------------------------------------------------
# Synthetic corpus + deterministic lexical retriever
# ---------------------------------------------------------------------------


def _salient_tokens(text: str) -> list[str]:
    """Content tokens — lowercase, stopwords stripped, dedup preserving order."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if len(t) < 3 or t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _build_corpus_for_case(case: dict[str, Any]) -> tuple[list[dict], set[str]]:
    """Build a tiny per-case corpus and return ``(docs, relevant_ids)``.

    Strategy: produce three "relevant" documents that each stitch together a
    disjoint subset of the case's salient tokens (or ``expected_fragments``
    when present), and three distractor docs drawn from the other cases so
    a trivial retriever can still be wrong.
    """
    fragments = case["expected_fragments"]
    if fragments:
        # Use each fragment as its own relevant doc.
        relevant_docs = [
            {"id": f"{case['id']}::rel::{i}", "text": frag} for i, frag in enumerate(fragments)
        ]
    else:
        # Fall back to slicing the prompt's salient tokens into 3 chunks.
        tokens = _salient_tokens(case["prompt"]) or ["placeholder"]
        chunks = max(1, min(3, len(tokens)))
        step = max(1, len(tokens) // chunks)
        relevant_docs = [
            {
                "id": f"{case['id']}::rel::{i}",
                "text": " ".join(tokens[i * step : (i + 1) * step]) or tokens[0],
            }
            for i in range(chunks)
        ]

    distractors = [
        {"id": f"{case['id']}::dist::0", "text": "quarterly review calendar invite"},
        {"id": f"{case['id']}::dist::1", "text": "grocery list milk eggs bread"},
        {"id": f"{case['id']}::dist::2", "text": "meeting notes from last tuesday"},
    ]

    docs = relevant_docs + distractors
    relevant_ids = {d["id"] for d in relevant_docs}
    return docs, relevant_ids


def _fake_retrieve(query: str, docs: list[dict]) -> list[str]:
    """Lexical overlap retriever — returns doc ids sorted by best match first.

    Ties are broken by original order (stable sort) so the test is
    deterministic across runs.
    """
    q_tokens = set(_salient_tokens(query))
    scored: list[tuple[int, int, str]] = []
    for order, doc in enumerate(docs):
        d_tokens = set(_salient_tokens(doc["text"]))
        overlap = len(q_tokens & d_tokens)
        scored.append((-overlap, order, doc["id"]))
    scored.sort()
    return [doc_id for _, _, doc_id in scored]


# ---------------------------------------------------------------------------
# Baseline handling
# ---------------------------------------------------------------------------


def _load_baselines() -> dict[str, Any]:
    if not BASELINE_PATH.exists():
        # Placeholder values — first run writes real numbers via the CLI.
        return {
            "max_regression": MAX_REGRESSION_DEFAULT,
            "datasets": {
                "_default": {
                    "ndcg_at_10": 0.50,
                    "mrr": 0.50,
                    "recall_at_10": 0.50,
                    "context_precision_at_10": 0.05,
                    "faithfulness": 0.80,
                },
            },
        }
    return json.loads(BASELINE_PATH.read_text())


def _baseline_for(dataset_id: str, baselines: dict[str, Any]) -> dict[str, float]:
    datasets = baselines.get("datasets", {})
    if dataset_id in datasets:
        return datasets[dataset_id]
    return datasets.get("_default", {})


# ---------------------------------------------------------------------------
# Real-pgvector toggle — guarded behind an env flag and a fixture check
# ---------------------------------------------------------------------------


def _real_pgvector_available() -> bool:
    """Has P2.1 wired up a seeded-episodes fixture?  Today: no."""
    return bool(os.environ.get("USE_REAL_PGVECTOR"))


# ---------------------------------------------------------------------------
# Faithfulness — stubbed with a small heuristic so CI never hits the API.
# ---------------------------------------------------------------------------


def _stub_faithfulness(answer: str, contexts: list[str]) -> float:
    """Proxy: fraction of answer tokens that appear in at least one context.

    This is a *deterministic* stand-in for the Haiku judge so the CI pipeline
    doesn't need API credentials.  The real judge is tested separately in
    ``test_retrieval_faithfulness.py``.
    """
    if not answer.strip():
        return 1.0
    ans_tokens = set(_salient_tokens(answer))
    if not ans_tokens:
        return 1.0
    ctx_tokens: set[str] = set()
    for c in contexts:
        ctx_tokens.update(_salient_tokens(c))
    supported = len(ans_tokens & ctx_tokens)
    return supported / len(ans_tokens)


# ---------------------------------------------------------------------------
# Parametrised test
# ---------------------------------------------------------------------------


_DATASETS = _load_datasets()


@pytest.mark.parametrize(
    ("dataset_id", "dataset"),
    _DATASETS,
    ids=[d[0] for d in _DATASETS],
)
def test_retrieval_quality_for_dataset(
    dataset_id: str,
    dataset: dict[str, Any],
) -> None:
    """Compute the five metrics per case and assert they clear the baseline.

    Scores are averaged across cases to produce one number per dataset.
    """
    if _real_pgvector_available():
        pytest.skip("real-pgvector path not yet wired — run after P2.1 lands")

    cases = list(_iter_cases(dataset))
    if not cases:
        pytest.skip(f"no cases in {dataset_id}")

    ndcg_scores: list[float] = []
    mrr_scores: list[float] = []
    recall_scores: list[float] = []
    precision_scores: list[float] = []
    faith_scores: list[float] = []

    for case in cases:
        if not case["prompt"].strip():
            continue
        docs, relevant_ids = _build_corpus_for_case(case)
        ranked = _fake_retrieve(case["prompt"], docs)

        ndcg_scores.append(ndcg_at_k(ranked, relevant_ids, k=K))
        mrr_scores.append(mrr(ranked, relevant_ids))
        recall_scores.append(recall_at_k(ranked, relevant_ids, k=K))
        precision_scores.append(context_precision(ranked, relevant_ids, k=K))

        # Faithfulness: pretend the "answer" echoes the summary/expected
        # fragments and the retrieved contexts are the top-k docs.
        answer = case["summary"] or " ".join(case["expected_fragments"]) or case["prompt"]
        top_contexts = [next(d["text"] for d in docs if d["id"] == doc_id) for doc_id in ranked[:K]]
        faith_scores.append(_stub_faithfulness(answer, top_contexts))

    if not ndcg_scores:
        pytest.skip(f"no evaluable cases in {dataset_id}")

    results = {
        "ndcg_at_10": sum(ndcg_scores) / len(ndcg_scores),
        "mrr": sum(mrr_scores) / len(mrr_scores),
        "recall_at_10": sum(recall_scores) / len(recall_scores),
        "context_precision_at_10": sum(precision_scores) / len(precision_scores),
        "faithfulness": sum(faith_scores) / len(faith_scores),
    }

    baselines = _load_baselines()
    baseline = _baseline_for(dataset_id, baselines)
    max_reg = baselines.get("max_regression", MAX_REGRESSION_DEFAULT)

    # Each metric must clear (baseline - max_regression).
    failures: list[str] = []
    for key, observed in results.items():
        floor = baseline.get(key, 0.0) - max_reg
        if observed < floor:
            failures.append(
                f"{key}: observed={observed:.3f} below floor={floor:.3f} "
                f"(baseline={baseline.get(key, 0.0):.3f})",
            )

    assert not failures, f"Retrieval-quality regression in {dataset_id}:\n  " + "\n  ".join(
        failures
    )
