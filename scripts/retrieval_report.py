"""CLI: generate a per-dataset retrieval-quality markdown report.

Runs the same harness as ``tests/evaluation/test_retrieval_quality.py`` but
writes a human-readable report to
``data/evaluation/reports/retrieval_YYYY-MM-DD.md``.

Usage
-----
    # Report against current baselines (read-only)
    uv run python -m scripts.retrieval_report

    # Regenerate baselines from the current run's scores
    uv run python -m scripts.retrieval_report --write-baseline

    # Override cutoff or output path
    uv run python -m scripts.retrieval_report --k 10 --out custom.md
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from src.app.core.retrieval_metrics import (
    context_precision,
    mrr,
    ndcg_at_k,
    recall_at_k,
)

# Import the harness helpers from the test module.  Using the test module's
# already-implemented logic means CI and the CLI can never drift apart.
from tests.evaluation.test_retrieval_quality import (  # type: ignore[import-not-found]
    BASELINE_PATH,
    MAX_REGRESSION_DEFAULT,
    _build_corpus_for_case,
    _fake_retrieve,
    _iter_cases,
    _load_baselines,
    _load_datasets,
    _stub_faithfulness,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "data" / "evaluation" / "reports"

METRIC_KEYS = (
    "ndcg_at_10",
    "mrr",
    "recall_at_10",
    "context_precision_at_10",
    "faithfulness",
)


def _score_dataset(dataset: dict, k: int) -> dict[str, float]:
    """Return the five averaged metrics for a single dataset."""
    buckets: dict[str, list[float]] = {key: [] for key in METRIC_KEYS}
    for case in _iter_cases(dataset):
        if not case["prompt"].strip():
            continue
        docs, relevant_ids = _build_corpus_for_case(case)
        ranked = _fake_retrieve(case["prompt"], docs)
        buckets["ndcg_at_10"].append(ndcg_at_k(ranked, relevant_ids, k=k))
        buckets["mrr"].append(mrr(ranked, relevant_ids))
        buckets["recall_at_10"].append(recall_at_k(ranked, relevant_ids, k=k))
        buckets["context_precision_at_10"].append(
            context_precision(ranked, relevant_ids, k=k),
        )
        answer = case["summary"] or " ".join(case["expected_fragments"]) or case["prompt"]
        top_contexts = [next(d["text"] for d in docs if d["id"] == doc_id) for doc_id in ranked[:k]]
        buckets["faithfulness"].append(_stub_faithfulness(answer, top_contexts))

    return {key: (sum(values) / len(values)) if values else 0.0 for key, values in buckets.items()}


def _format_row(
    name: str,
    scores: dict[str, float],
    baseline: dict[str, float],
    max_reg: float,
) -> str:
    cells = [f"`{name}`"]
    for key in METRIC_KEYS:
        observed = scores[key]
        base = baseline.get(key, 0.0)
        floor = base - max_reg
        marker = "" if observed >= floor else " FAIL"
        cells.append(f"{observed:.3f} (Δ{observed - base:+.3f}){marker}")
    return "| " + " | ".join(cells) + " |"


def _write_report(all_scores: dict[str, dict[str, float]], out_path: Path, baselines: dict) -> None:
    max_reg = baselines.get("max_regression", MAX_REGRESSION_DEFAULT)
    lines = [
        "# RAG Retrieval Quality",
        "",
        f"Generated: {datetime.now(UTC).isoformat(timespec='seconds')}",
        "",
        "**Harness:** in-memory lexical retriever + stubbed Haiku faithfulness.",
        "Replace with real pgvector once P2.1's fixture lands.",
        "",
        "| Dataset | nDCG@10 | MRR | Recall@10 | Ctx Precision@10 | Faithfulness |",
        "|---|---|---|---|---|---|",
    ]
    for dataset_id, scores in all_scores.items():
        baseline = baselines.get("datasets", {}).get(
            dataset_id,
            baselines.get("datasets", {}).get("_default", {}),
        )
        lines.append(_format_row(dataset_id, scores, baseline, max_reg))

    out_path.write_text("\n".join(lines) + "\n")


def _write_baseline(all_scores: dict[str, dict[str, float]], baseline_path: Path) -> None:
    payload = {
        "version": "v1",
        "_description": (
            "Baseline retrieval-quality metrics per dataset. Regenerate via "
            "`uv run python -m scripts.retrieval_report --write-baseline`."
        ),
        "_generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "max_regression": MAX_REGRESSION_DEFAULT,
        "datasets": all_scores,
    }
    baseline_path.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG retrieval-quality report")
    parser.add_argument("--k", type=int, default=10, help="cut-off (default 10)")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output markdown path (default: reports/retrieval_<DATE>.md)",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="overwrite data/evaluation/baselines/retrieval.json with current scores",
    )
    args = parser.parse_args()

    baselines = _load_baselines()

    all_scores: dict[str, dict[str, float]] = {}
    for dataset_id, dataset in _load_datasets():
        all_scores[dataset_id] = _score_dataset(dataset, k=args.k)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = args.out or REPORTS_DIR / f"retrieval_{datetime.now(UTC):%Y-%m-%d}.md"
    _write_report(all_scores, out, baselines)
    print(f"wrote {out}")

    if args.write_baseline:
        _write_baseline(all_scores, BASELINE_PATH)
        print(f"updated {BASELINE_PATH}")

    # Return non-zero if any metric is below (baseline - max_regression).
    max_reg = baselines.get("max_regression", MAX_REGRESSION_DEFAULT)
    regressions = 0
    for dataset_id, scores in all_scores.items():
        baseline = baselines.get("datasets", {}).get(
            dataset_id,
            baselines.get("datasets", {}).get("_default", {}),
        )
        for key, observed in scores.items():
            floor = baseline.get(key, 0.0) - max_reg
            if observed < floor:
                regressions += 1
                print(f"REGRESSION {dataset_id}.{key}: {observed:.3f} < {floor:.3f}")

    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
