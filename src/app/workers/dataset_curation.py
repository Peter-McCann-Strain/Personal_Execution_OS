"""Weekly golden-dataset curation pipeline (Phase 4.5).

Per 2026 best practice, golden datasets should be curated for DIVERSITY —
not by mining failures alone, which overfits the dataset to current
weaknesses and starves the rubric of novel behaviours to test.

Pipeline (runs Monday 04:00 user-local):
  1. For each agent: pull last 7 days of scored interactions.
  2. Embed ``user_message`` via the shared Ollama helper.
  3. Run KMeans to form clusters of similar prompts.
  4. Pick 1-2 interactions from each UNDER-REPRESENTED cluster
     (count < median cluster size). Within each cluster, spread the
     picks across high / mid / low auto-judge final scores so the
     dataset gets both success and failure shapes.
  5. Write proposals as JSONL to ``data/evaluation/datasets/proposals/
     <agent>_<date>.jsonl``. Each row carries provenance:
       - ``source_interaction_id``
       - ``promoted_at``
       - ``rubric_version``
       - ``human_verified: false`` (flipped to true by the CLI)
       - ``cluster_id``
       - ``reason``

Invariants:
  - Never mutate or delete existing golden datasets.
  - Every proposal row has a ``source_interaction_id`` for audit.
  - Cluster assignment is recorded so future reviewers can see WHY a
    given prompt was picked (rare cluster / mid-scoring / etc.).
"""

from __future__ import annotations

import json
import math
import statistics
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.app.config import Settings
    from src.app.persistence.models import InteractionRecord

logger = structlog.get_logger()

# Agent names to iterate — matches the ``specialist`` column and the
# dataset filenames already present in data/evaluation/datasets/*.v1.json.
_AGENTS: tuple[str, ...] = (
    "diary",
    "memory",
    "research",
    "review",
    "notification",
    "tools",
    "project",
    "communications",
    "plan_day",
    "save",
    "socratic",
)

# Rubric version stamped onto every proposal so later auditors know
# which scoring regime the interaction was measured under. Bumped by
# hand when the universal rubric changes shape.
_CURRENT_RUBRIC_VERSION: str = "universal-v1"


@dataclass(frozen=True)
class ProposedCase:
    """One proposed golden-dataset row awaiting human approval."""

    source_interaction_id: str
    agent: str
    cluster_id: int
    reason: str
    prompt: str
    response: str
    auto_judge_final: float | None
    rubric_version: str
    promoted_at: str
    human_verified: bool = False

    def to_jsonl(self) -> str:
        """Serialise to a single JSONL line."""
        payload = {
            "source_interaction_id": self.source_interaction_id,
            "agent": self.agent,
            "cluster_id": self.cluster_id,
            "reason": self.reason,
            "prompt": self.prompt,
            "response": self.response,
            "auto_judge_final": self.auto_judge_final,
            "rubric_version": self.rubric_version,
            "promoted_at": self.promoted_at,
            "human_verified": self.human_verified,
        }
        return json.dumps(payload, ensure_ascii=False)


async def run_weekly_dataset_curation(ctx: dict) -> None:
    """ARQ cron entry point — orchestrate the pipeline for every agent."""
    settings: Settings = ctx["settings"]
    if not settings.dataset_curation_enabled:
        logger.info("dataset_curation_disabled")
        return

    session_factory = ctx.get("session_factory")
    if session_factory is None:
        logger.warning("dataset_curation_no_session_factory")
        return

    # Lazy import so the worker never crashes on Ollama/sklearn at module load.
    from src.app.core.embeddings import OllamaEmbeddings
    from src.app.persistence.repositories.interactions import (
        get_interactions_for_export,
    )

    now = datetime.now(UTC)
    start = now - timedelta(days=settings.dataset_curation_lookback_days)

    embedder = OllamaEmbeddings(
        host=settings.ollama_host,
        model=settings.ollama_embed_model,
    )
    try:
        for agent in _AGENTS:
            try:
                async with session_factory() as session:
                    records = await get_interactions_for_export(
                        session,
                        start=start,
                        end=now,
                        limit=2000,
                    )
                agent_records = [r for r in records if r.specialist == agent]
                if len(agent_records) < settings.dataset_cluster_min_size:
                    logger.info(
                        "dataset_curation_skip_small_agent",
                        agent=agent,
                        records=len(agent_records),
                    )
                    continue

                proposals = await curate_agent(
                    agent=agent,
                    records=agent_records,
                    embedder=embedder,
                    settings=settings,
                    now=now,
                )
                if proposals:
                    _write_proposals(
                        proposals=proposals,
                        agent=agent,
                        on_date=now.date(),
                        proposals_dir=Path(settings.dataset_proposals_dir),
                    )
                    logger.info(
                        "dataset_curation_wrote_proposals",
                        agent=agent,
                        count=len(proposals),
                    )
            except Exception:
                logger.exception("dataset_curation_agent_failed", agent=agent)
    finally:
        await embedder.close()


async def curate_agent(
    *,
    agent: str,
    records: Sequence[InteractionRecord],
    embedder: Any,
    settings: Settings,
    now: datetime,
) -> list[ProposedCase]:
    """Cluster one agent's interactions and pick a diverse sample.

    ``embedder`` duck-types the ``OllamaEmbeddings.embed`` signature so
    tests can pass a stub that returns deterministic vectors without
    calling Ollama.
    """
    messages = [r.user_message for r in records]
    embeddings = await embedder.embed(messages)
    if len(embeddings) != len(records):
        raise RuntimeError(
            f"Embedder returned {len(embeddings)} vectors for {len(records)} records "
            f"(agent={agent})"
        )

    labels = _cluster(embeddings, min_size=settings.dataset_cluster_min_size)

    return _select_diverse_samples(
        records=list(records),
        labels=labels,
        agent=agent,
        proposals_per_week=settings.dataset_proposals_per_week,
        now=now,
    )


def _cluster(vectors: Sequence[Sequence[float]], *, min_size: int) -> list[int]:
    """Run KMeans and return a cluster label per vector.

    Small datasets (n < min_size*2) collapse to a single cluster —
    clustering adds no information there, and we still want to emit
    mid/low/high spread from that one bucket.

    Prefers scikit-learn's KMeans. If sklearn is unavailable (e.g. the
    worker image did not install the [eval] extra), falls back to a
    lightweight pure-Python k-means so the pipeline degrades gracefully
    rather than crashing the weekly cron.
    """
    n = len(vectors)
    if n == 0:
        return []
    if n < min_size * 2:
        return [0] * n

    # Heuristic: sqrt(n/2) clusters, capped at 8 so we never over-split.
    k = max(2, min(8, round(math.sqrt(n / 2))))
    k = min(k, n)

    try:
        from sklearn.cluster import KMeans  # lazy import — optional dep
    except ImportError:
        return _fallback_kmeans(list(vectors), k=k, seed=42)

    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    km.fit(list(vectors))
    return [int(label) for label in km.labels_]


def _fallback_kmeans(
    vectors: list[Sequence[float]],
    *,
    k: int,
    seed: int,
    max_iter: int = 25,
) -> list[int]:
    """Pure-Python KMeans (Lloyd's algorithm). No numpy required.

    Only used when scikit-learn is not available. Good enough for the
    curation use-case (hundreds of embeddings, not millions).
    """
    import random

    rng = random.Random(seed)  # noqa: S311  # nosec B311 — reproducible sampling, not crypto
    n = len(vectors)
    if k <= 1 or n <= k:
        # Trivial case: one cluster or each vector its own.
        return [i % max(1, k) for i in range(n)]

    # Seed centroids by picking k distinct input vectors (k-means++ lite).
    indices = rng.sample(range(n), k)
    centroids: list[list[float]] = [list(vectors[i]) for i in indices]

    labels = [0] * n
    for _ in range(max_iter):
        changed = False
        # Assign each vector to the nearest centroid.
        for i, v in enumerate(vectors):
            best_c, best_d = 0, float("inf")
            for c_idx, c in enumerate(centroids):
                d = sum((a - b) ** 2 for a, b in zip(v, c, strict=False))
                if d < best_d:
                    best_d = d
                    best_c = c_idx
            if labels[i] != best_c:
                labels[i] = best_c
                changed = True

        # Recompute centroids.
        sums: list[list[float]] = [[0.0] * len(vectors[0]) for _ in range(k)]
        counts = [0] * k
        for i, v in enumerate(vectors):
            c_idx = labels[i]
            counts[c_idx] += 1
            for dim, val in enumerate(v):
                sums[c_idx][dim] += val
        for c_idx in range(k):
            if counts[c_idx] == 0:
                continue
            centroids[c_idx] = [s / counts[c_idx] for s in sums[c_idx]]

        if not changed:
            break
    return labels


def _select_diverse_samples(
    *,
    records: list[InteractionRecord],
    labels: list[int],
    agent: str,
    proposals_per_week: int,
    now: datetime,
) -> list[ProposedCase]:
    """Pick ~proposals_per_week rows, favouring under-represented clusters.

    Strategy:
      1. Count records per cluster; "under-represented" = count < median.
      2. For each under-represented cluster, pick up to 2 records spread
         across score bands (high / mid / low). If the cluster is too
         small for three bands, fall back to the records it has.
      3. Stop when we've hit proposals_per_week or run out of clusters.
    """
    if not records:
        return []

    cluster_to_indices: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        cluster_to_indices.setdefault(label, []).append(idx)

    counts = [len(v) for v in cluster_to_indices.values()]
    median = statistics.median(counts) if counts else 0

    # Clusters with count < median come first (most under-represented).
    # Ties broken by smaller cluster_id for deterministic output.
    sorted_clusters = sorted(
        cluster_to_indices.items(),
        key=lambda kv: (len(kv[1]), kv[0]),
    )

    proposals: list[ProposedCase] = []
    promoted_at = now.isoformat()

    for cluster_id, indices in sorted_clusters:
        if len(proposals) >= proposals_per_week:
            break
        under = len(indices) < median or median == 0
        reason_tag = "under_represented" if under else "median"
        per_cluster_budget = 2 if under else 1

        picked = _pick_by_score_spread(
            [records[i] for i in indices],
            budget=per_cluster_budget,
        )
        for rec in picked:
            if len(proposals) >= proposals_per_week:
                break
            proposals.append(
                ProposedCase(
                    source_interaction_id=str(rec.id),
                    agent=agent,
                    cluster_id=cluster_id,
                    reason=(
                        f"{reason_tag}; cluster_size={len(indices)}, "
                        f"median={median}, band={_score_band(_final_score(rec))}"
                    ),
                    prompt=rec.user_message,
                    response=rec.response_content,
                    auto_judge_final=_final_score(rec),
                    rubric_version=_CURRENT_RUBRIC_VERSION,
                    promoted_at=promoted_at,
                    human_verified=False,
                )
            )
    return proposals


def _pick_by_score_spread(
    records: list[InteractionRecord],
    *,
    budget: int,
) -> list[InteractionRecord]:
    """Spread picks across high / mid / low auto-judge final scores."""
    if not records:
        return []
    scored = [(r, _final_score(r)) for r in records]
    scored_sorted = sorted(scored, key=lambda t: (t[1] is None, t[1] or 0.0))
    # Target bands: low (lowest), mid (median), high (highest).
    if budget <= 0:
        return []
    if budget == 1 or len(scored_sorted) == 1:
        return [scored_sorted[len(scored_sorted) // 2][0]]
    if budget == 2:
        return [scored_sorted[0][0], scored_sorted[-1][0]]
    low = scored_sorted[0][0]
    high = scored_sorted[-1][0]
    mid = scored_sorted[len(scored_sorted) // 2][0]
    picks = [low, mid, high]
    # Dedupe while preserving order (tiny lists can repeat).
    seen: set[uuid.UUID] = set()
    unique_picks: list[InteractionRecord] = []
    for r in picks:
        if r.id in seen:
            continue
        seen.add(r.id)
        unique_picks.append(r)
        if len(unique_picks) >= budget:
            break
    return unique_picks


def _final_score(record: InteractionRecord) -> float | None:
    """Mean of the four auto-judge dimensions, or None if not yet scored."""
    dims = (
        record.score_relevance,
        record.score_actionability,
        record.score_tone,
        record.score_conciseness,
    )
    if any(d is None for d in dims):
        return None
    return sum(dims) / 4  # type: ignore[arg-type]


def _score_band(score: float | None) -> str:
    """Label a score as high/mid/low/unscored for the provenance reason field."""
    if score is None:
        return "unscored"
    if score >= 0.8:
        return "high"
    if score >= 0.5:
        return "mid"
    return "low"


def _write_proposals(
    *,
    proposals: Iterable[ProposedCase],
    agent: str,
    on_date: date,
    proposals_dir: Path,
) -> Path:
    """Write proposals as JSONL. Returns the path written."""
    proposals_dir.mkdir(parents=True, exist_ok=True)
    out_path = proposals_dir / f"{agent}_{on_date.isoformat()}.jsonl"
    lines = [p.to_jsonl() for p in proposals]
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return out_path
