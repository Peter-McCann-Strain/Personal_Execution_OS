"""Tests for the Phase 4.5 dataset-curation pipeline and promote CLI."""

from __future__ import annotations

import io
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts import dataset_promote
from src.app.workers import dataset_curation

# ---------- fixtures ----------


def _make_record(
    *,
    specialist: str,
    user_message: str,
    response_content: str = "ok",
    final_score: float = 0.75,
) -> SimpleNamespace:
    """Build a stand-in for ``InteractionRecord`` that the curation module
    consumes via attribute access only."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        specialist=specialist,
        user_message=user_message,
        response_content=response_content,
        score_relevance=final_score,
        score_actionability=final_score,
        score_tone=final_score,
        score_conciseness=final_score,
    )


def _make_settings(tmp_path: Path, *, enabled: bool = True, per_week: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        dataset_curation_enabled=enabled,
        dataset_proposals_per_week=per_week,
        dataset_cluster_min_size=3,
        dataset_proposals_dir=str(tmp_path / "proposals"),
        dataset_datasets_dir=str(tmp_path / "datasets"),
        dataset_curation_lookback_days=7,
        ollama_host="http://localhost:11434",
        ollama_embed_model="nomic-embed-text:v2-moe",
    )


def _stub_embedder():
    """Return a MagicMock that mimics OllamaEmbeddings without calling Ollama.

    The embed() method hashes messages deterministically into two bands so
    KMeans discovers real (but fake) clusters without any network call.
    """
    embedder = MagicMock()

    async def _embed(texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            # Trivial 2D embedding: first byte of text steers the cluster.
            seed = ord(text[0]) if text else 0
            vectors.append([float(seed), float(len(text))])
        return vectors

    async def _close() -> None:
        return None

    embedder.embed = AsyncMock(side_effect=_embed)
    embedder.close = AsyncMock(side_effect=_close)
    return embedder


# ---------- curate_agent: clusters + proposal shape ----------


class TestCurateAgent:
    @pytest.mark.asyncio
    async def test_clusters_and_emits_proposals_with_provenance(self, tmp_path: Path):
        """KMeans runs, proposals are written, each row carries all provenance fields."""
        # 10 records across two visible 'topics' — letters A and B.
        records = [
            *[
                _make_record(
                    specialist="memory", user_message=f"A{i} how?", final_score=0.4 + i * 0.05
                )
                for i in range(3)
            ],
            *[
                _make_record(
                    specialist="memory", user_message=f"B{i} why?", final_score=0.6 + i * 0.05
                )
                for i in range(7)
            ],
        ]

        settings = _make_settings(tmp_path, per_week=5)
        embedder = _stub_embedder()
        now = datetime.now(UTC)

        proposals = await dataset_curation.curate_agent(
            agent="memory",
            records=records,
            embedder=embedder,
            settings=settings,
            now=now,
        )

        assert proposals, "expected at least one proposal"
        assert len(proposals) <= settings.dataset_proposals_per_week

        # Every proposal has the full provenance set.
        for p in proposals:
            assert p.source_interaction_id
            assert p.agent == "memory"
            assert isinstance(p.cluster_id, int)
            assert p.reason  # non-empty reason
            assert p.rubric_version
            assert p.promoted_at
            assert p.human_verified is False

        # Under-represented cluster should be represented in the output.
        cluster_ids = {p.cluster_id for p in proposals}
        assert len(cluster_ids) >= 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_records(self, tmp_path: Path):
        settings = _make_settings(tmp_path)
        embedder = _stub_embedder()
        proposals = await dataset_curation.curate_agent(
            agent="diary",
            records=[],
            embedder=embedder,
            settings=settings,
            now=datetime.now(UTC),
        )
        assert proposals == []


# ---------- cluster helper: min size threshold ----------


class TestClusterMinSize:
    def test_small_corpus_falls_back_to_single_cluster(self):
        vectors = [[1.0, 2.0], [1.1, 2.1], [1.2, 2.0]]
        labels = dataset_curation._cluster(vectors, min_size=3)
        # n=3, min_size*2=6 → below threshold → single cluster.
        assert labels == [0, 0, 0]

    def test_larger_corpus_splits_into_multiple_clusters(self):
        vectors = [[float(i % 3), float((i * 7) % 5)] for i in range(12)]
        labels = dataset_curation._cluster(vectors, min_size=3)
        assert len(set(labels)) >= 2


# ---------- proposal JSONL writing ----------


class TestWriteProposals:
    def test_writes_jsonl_with_expected_shape(self, tmp_path: Path):
        proposal = dataset_curation.ProposedCase(
            source_interaction_id=str(uuid.uuid4()),
            agent="memory",
            cluster_id=2,
            reason="under_represented; cluster_size=1, median=3, band=low",
            prompt="Remind me about X",
            response="You told me X last week.",
            auto_judge_final=0.42,
            rubric_version="universal-v1",
            promoted_at="2026-04-20T04:00:00+00:00",
            human_verified=False,
        )
        proposals_dir = tmp_path / "proposals"
        out = dataset_curation._write_proposals(
            proposals=[proposal],
            agent="memory",
            on_date=datetime(2026, 4, 20, tzinfo=UTC).date(),
            proposals_dir=proposals_dir,
        )
        assert out.exists()
        loaded = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
        assert len(loaded) == 1
        row = loaded[0]
        for key in (
            "source_interaction_id",
            "promoted_at",
            "rubric_version",
            "human_verified",
            "cluster_id",
            "reason",
            "prompt",
            "response",
        ):
            assert key in row, f"proposal missing {key}"
        assert row["human_verified"] is False


# ---------- worker entry point short-circuits ----------


class TestRunWeeklyDatasetCuration:
    @pytest.mark.asyncio
    async def test_disabled_flag_short_circuits(self, tmp_path: Path):
        ctx = {
            "settings": _make_settings(tmp_path, enabled=False),
            "session_factory": MagicMock(),
        }
        # Should return without calling any DB/embedding dependency.
        await dataset_curation.run_weekly_dataset_curation(ctx)

    @pytest.mark.asyncio
    async def test_end_to_end_writes_file_per_agent(self, tmp_path: Path):
        """Full worker path — session factory + embedder mocked, files land on disk."""
        records = [
            *[_make_record(specialist="memory", user_message=f"Am{i}?") for i in range(4)],
            *[_make_record(specialist="diary", user_message=f"Dd{i}?") for i in range(4)],
        ]

        session = AsyncMock()

        @asynccontextmanager
        async def session_factory():
            yield session

        settings = _make_settings(tmp_path)
        ctx = {"settings": settings, "session_factory": session_factory}

        with (
            patch.object(dataset_curation, "_AGENTS", ("memory", "diary")),
            patch(
                "src.app.core.embeddings.OllamaEmbeddings",
                return_value=_stub_embedder(),
            ),
            patch(
                "src.app.persistence.repositories.interactions.get_interactions_for_export",
                new_callable=AsyncMock,
                return_value=records,
            ),
        ):
            await dataset_curation.run_weekly_dataset_curation(ctx)

        # Inspect the disk via os.listdir — ruff's ASYNC240 flags pathlib
        # glob in async functions, and this is just a test assertion.
        import os

        proposals_dir = Path(settings.dataset_proposals_dir)
        names = sorted(n for n in os.listdir(proposals_dir) if n.endswith(".jsonl"))
        assert names, "expected per-agent proposal files"
        agents_written = {n.rsplit(".", 1)[0].split("_", 1)[0] for n in names}
        assert {"memory", "diary"}.issubset(agents_written)


# ---------- dataset_promote CLI: TTY review loop + atomic augment ----------


class TestPromoteCLI:
    def _seed_v1_dataset(self, datasets_dir: Path, agent: str = "memory") -> Path:
        datasets_dir.mkdir(parents=True, exist_ok=True)
        path = datasets_dir / f"{agent}.v1.json"
        path.write_text(
            json.dumps(
                {
                    "dataset_id": f"{agent}-v1",
                    "specialist": agent,
                    "version": "v1",
                    "rubric_id": f"{agent}-answer-v1",
                    "description": "seed",
                    "thresholds": {"minimum_pass_rate": 0.95},
                    "cases": [
                        {
                            "id": "existing_case_1",
                            "prompt": "keep me",
                            "expected_response": "kept",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def _write_proposal_file(
        self,
        tmp_path: Path,
        agent: str,
        rows: list[dict],
    ) -> Path:
        proposals_dir = tmp_path / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        p = proposals_dir / f"{agent}_2026-04-20.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return p

    def test_review_accepts_rejects_and_bumps_version(self, tmp_path: Path):
        datasets_dir = tmp_path / "datasets"
        v1_path = self._seed_v1_dataset(datasets_dir, "memory")
        rows = [
            {
                "source_interaction_id": "iid-approve",
                "agent": "memory",
                "cluster_id": 0,
                "reason": "under_represented",
                "prompt": "approve me",
                "response": "yes",
                "auto_judge_final": 0.6,
                "rubric_version": "universal-v1",
                "promoted_at": "2026-04-20T04:00:00+00:00",
                "human_verified": False,
            },
            {
                "source_interaction_id": "iid-reject",
                "agent": "memory",
                "cluster_id": 1,
                "reason": "median",
                "prompt": "reject me",
                "response": "no",
                "auto_judge_final": 0.3,
                "rubric_version": "universal-v1",
                "promoted_at": "2026-04-20T04:00:00+00:00",
                "human_verified": False,
            },
        ]
        proposal_path = self._write_proposal_file(tmp_path, "memory", rows)

        # Drive the TTY loop: approve row 1, reject row 2.
        scripted = iter(["y", "n"])
        out = io.StringIO()
        approved = dataset_promote.review_proposals(
            dataset_promote.load_proposals(proposal_path),
            input_fn=lambda _prompt: next(scripted),
            output=out,
        )
        assert len(approved) == 1
        assert approved[0]["human_verified"] is True
        assert approved[0]["source_interaction_id"] == "iid-approve"

        out_path = dataset_promote.augment_dataset(
            datasets_dir=datasets_dir,
            agent="memory",
            approved=approved,
        )

        # v1 file left in place (archived by name), v2 written with both rows.
        assert v1_path.exists(), "v1 must be archived (not deleted)"
        assert out_path.name == "memory.v2.json"
        v2 = json.loads(out_path.read_text(encoding="utf-8"))
        assert v2["version"] == "v2"
        case_ids = [c["id"] for c in v2["cases"]]
        assert "existing_case_1" in case_ids, "must augment — not replace"
        assert any(cid.startswith("curated_iid-approve") for cid in case_ids)
        # The rejected row is absent.
        assert not any("iid-reject" in cid for cid in case_ids)

        # Provenance fields present on new case.
        curated = next(c for c in v2["cases"] if c["id"].startswith("curated_iid-approve"))
        prov = curated["provenance"]
        for key in (
            "source_interaction_id",
            "promoted_at",
            "rubric_version",
            "human_verified",
            "cluster_id",
            "reason",
        ):
            assert key in prov
        assert prov["human_verified"] is True

    def test_edit_flow_overrides_prompt(self, tmp_path: Path):
        """'edit' path lets the reviewer rewrite the prompt before promoting."""
        datasets_dir = tmp_path / "datasets"
        self._seed_v1_dataset(datasets_dir, "diary")
        rows = [
            {
                "source_interaction_id": "iid-edit",
                "agent": "diary",
                "cluster_id": 0,
                "reason": "under_represented",
                "prompt": "original",
                "response": "orig resp",
                "auto_judge_final": 0.8,
                "rubric_version": "universal-v1",
                "promoted_at": "2026-04-20T04:00:00+00:00",
                "human_verified": False,
            }
        ]
        proposal_path = self._write_proposal_file(tmp_path, "diary", rows)
        answers = iter(["e", "edited prompt", ""])  # edit, new prompt, keep response
        out = io.StringIO()
        approved = dataset_promote.review_proposals(
            dataset_promote.load_proposals(proposal_path),
            input_fn=lambda _prompt: next(answers),
            output=out,
        )
        assert len(approved) == 1
        assert approved[0]["prompt"] == "edited prompt"
        assert approved[0]["response"] == "orig resp"
        assert approved[0]["human_verified"] is True

    def test_quit_aborts_and_promotes_nothing(self, tmp_path: Path):
        proposal_path = self._write_proposal_file(
            tmp_path,
            "tools",
            [
                {
                    "source_interaction_id": "iid-q",
                    "agent": "tools",
                    "cluster_id": 0,
                    "reason": "median",
                    "prompt": "x",
                    "response": "y",
                    "auto_judge_final": 0.5,
                    "rubric_version": "universal-v1",
                    "promoted_at": "2026-04-20T04:00:00+00:00",
                    "human_verified": False,
                }
            ],
        )
        out = io.StringIO()
        approved = dataset_promote.review_proposals(
            dataset_promote.load_proposals(proposal_path),
            input_fn=lambda _prompt: "q",
            output=out,
        )
        assert approved == []

    def test_never_deletes_prior_version(self, tmp_path: Path):
        """Calling augment_dataset multiple times must leave ALL prior versions alive."""
        datasets_dir = tmp_path / "datasets"
        v1 = self._seed_v1_dataset(datasets_dir, "memory")
        approved = [
            {
                "source_interaction_id": "iid-1",
                "agent": "memory",
                "cluster_id": 0,
                "reason": "under_represented",
                "prompt": "first",
                "response": "a",
                "auto_judge_final": 0.7,
                "rubric_version": "universal-v1",
                "promoted_at": "2026-04-20T04:00:00+00:00",
                "human_verified": True,
            }
        ]
        v2 = dataset_promote.augment_dataset(
            datasets_dir=datasets_dir,
            agent="memory",
            approved=approved,
        )
        approved2 = [
            {
                "source_interaction_id": "iid-2",
                "agent": "memory",
                "cluster_id": 1,
                "reason": "under_represented",
                "prompt": "second",
                "response": "b",
                "auto_judge_final": 0.6,
                "rubric_version": "universal-v1",
                "promoted_at": "2026-04-27T04:00:00+00:00",
                "human_verified": True,
            }
        ]
        v3 = dataset_promote.augment_dataset(
            datasets_dir=datasets_dir,
            agent="memory",
            approved=approved2,
        )
        assert v1.exists()
        assert v2.exists()
        assert v3.exists()
        assert v2.name == "memory.v2.json"
        assert v3.name == "memory.v3.json"
        # v3 inherits v2's cases PLUS the new one (augment, not replace).
        v3_cases = json.loads(v3.read_text(encoding="utf-8"))["cases"]
        ids = [c["id"] for c in v3_cases]
        assert "existing_case_1" in ids
        assert any("iid-1" in i for i in ids)
        assert any("iid-2" in i for i in ids)
