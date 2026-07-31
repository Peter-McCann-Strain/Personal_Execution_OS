"""Integration test for Phase 7.7 HNSW tuning.

Verifies that after Alembic migrations are applied against a real
pgvector/pgvector:pg16 container:

1. Every managed vector column is backed by an HNSW index (not IVFFLAT,
   not "no index").
2. Per-query ``hnsw.ef_search`` tuning via :mod:`src.app.persistence.vector_search`
   actually takes effect.
3. PostgreSQL can use the HNSW index for vector ordering, proved from the
   query plan rather than from probabilistic differences in search results.

This file relies on the session-scoped ``db_engine`` fixture from
``tests/integration/conftest.py`` which already boots pgvector and runs
``alembic upgrade head`` once per ``pytest`` invocation. If Docker is not
reachable the fixture calls ``pytest.skip`` cleanly.
"""

from __future__ import annotations

import json
import random

import pytest
from sqlalchemy import text

from src.app.persistence.vector_search import (
    Preset,
    ef_search_scope,
    hnsw_ef_search,
)

_DIM = 768
_SEED_ROWS = 50

pytestmark = pytest.mark.asyncio


async def _seed_episode_embeddings(db_session, count: int = _SEED_ROWS) -> None:
    """Insert `count` episodes with random 768-d embeddings.

    We bypass the ORM and hit SQL directly so the test doesn't depend on
    the rest of the Episode model surface; all we care about here is the
    vector column + index behaviour.
    """
    rng = random.Random(0xCAFE)
    for i in range(count):
        raw = [rng.gauss(0, 1) for _ in range(_DIM)]
        norm = sum(x * x for x in raw) ** 0.5 or 1.0
        vec = [x / norm for x in raw]
        await db_session.execute(
            text(
                "INSERT INTO episodes (id, content, created_at, embedding) "
                "VALUES (gen_random_uuid(), :content, NOW(), "
                "CAST(:embedding AS vector))"
            ),
            {
                "content": f"bench-seed-{i}",
                "embedding": json.dumps(vec, separators=(",", ":")),
            },
        )
    await db_session.flush()


async def test_every_vector_column_has_hnsw_index(db_session):
    """After `alembic upgrade head`, every known vector column is HNSW."""
    expected = {
        ("episodes", "ix_episodes_embedding_hnsw"),
        ("notes", "ix_notes_embedding_hnsw"),
        ("connector_documents", "ix_connector_documents_embedding_hnsw"),
    }

    for table, index_name in expected:
        row = (
            await db_session.execute(
                text(
                    "SELECT am.amname "
                    "FROM pg_class c "
                    "JOIN pg_index i ON i.indexrelid = c.oid "
                    "JOIN pg_am am ON am.oid = c.relam "
                    "WHERE c.relname = :index_name"
                ),
                {"index_name": index_name},
            )
        ).first()
        assert row is not None, f"{index_name} missing on {table}"
        assert row[0] == "hnsw", f"{index_name} should be HNSW, got {row[0]}"


async def test_ef_search_preset_sets_guc(db_session):
    """`hnsw_ef_search` writes the expected value into the current txn.

    The `db_session` fixture already wraps every test in an outer
    transaction, so `SET LOCAL` is valid without opening another one.
    """
    await hnsw_ef_search(db_session, Preset.MEMORY)
    value = (await db_session.execute(text("SHOW hnsw.ef_search"))).scalar_one()
    assert int(value) == int(Preset.MEMORY) == 20

    await hnsw_ef_search(db_session, Preset.RESEARCH)
    value = (await db_session.execute(text("SHOW hnsw.ef_search"))).scalar_one()
    assert int(value) == int(Preset.RESEARCH) == 80


async def test_ef_search_scope_roundtrip(db_session):
    """`ef_search_scope` applies the GUC inside the block."""
    # The session starts with no active transaction — the context manager
    # should open one for the duration of the block.
    async with ef_search_scope(db_session, Preset.DEFAULT):
        value = (await db_session.execute(text("SHOW hnsw.ef_search"))).scalar_one()
        assert int(value) == int(Preset.DEFAULT) == 40


async def test_ef_search_rejects_out_of_range(db_session):
    with pytest.raises(ValueError, match=r"hnsw\.ef_search must be in"):
        await hnsw_ef_search(db_session, 0)
    with pytest.raises(ValueError, match=r"hnsw\.ef_search must be in"):
        await hnsw_ef_search(db_session, 10_000)


async def test_hnsw_index_is_available_to_vector_query_planner(db_session):
    """Prove the HNSW index is usable without a probabilistic assertion."""
    await _seed_episode_embeddings(db_session)

    rng = random.Random(0xF00D)
    raw = [rng.gauss(0, 1) for _ in range(_DIM)]
    norm = sum(x * x for x in raw) ** 0.5 or 1.0
    probe = json.dumps([x / norm for x in raw], separators=(",", ":"))

    await hnsw_ef_search(db_session, Preset.MEMORY)
    # A tiny fixture may legitimately make a sequential scan cheaper. Disable
    # it here to ask the planner whether the production index is valid and
    # usable for this operator/order combination.
    await db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = (
        await db_session.execute(
            text(
                "EXPLAIN (FORMAT JSON) "
                "SELECT id FROM episodes "
                "WHERE embedding IS NOT NULL "
                "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 10"
            ),
            {"q": probe},
        )
    ).scalar_one()
    assert "ix_episodes_embedding_hnsw" in json.dumps(plan)


async def test_research_preset_recall_at_least_as_good_as_memory(db_session):
    """Higher ef_search should not reduce recall vs the low preset."""
    await _seed_episode_embeddings(db_session)

    rng = random.Random(0xBEEF)

    def _probe_vector() -> str:
        raw = [rng.gauss(0, 1) for _ in range(_DIM)]
        norm = sum(x * x for x in raw) ** 0.5 or 1.0
        return json.dumps([x / norm for x in raw], separators=(",", ":"))

    await db_session.execute(text("SET LOCAL enable_indexscan = off"))
    await db_session.execute(text("SET LOCAL enable_bitmapscan = off"))

    truth: list[set[str]] = []
    probes: list[str] = []
    for _ in range(5):
        probe = _probe_vector()
        probes.append(probe)
        rows = (
            await db_session.execute(
                text(
                    "SELECT id::text FROM episodes "
                    "WHERE embedding IS NOT NULL "
                    "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 10"
                ),
                {"q": probe},
            )
        ).all()
        truth.append({r[0] for r in rows})

    await db_session.execute(text("SET LOCAL enable_indexscan = on"))
    await db_session.execute(text("SET LOCAL enable_bitmapscan = on"))

    async def _recall_at_10(preset: Preset) -> float:
        await hnsw_ef_search(db_session, preset)
        overlaps = []
        for probe, truth_set in zip(probes, truth, strict=True):
            rows = (
                await db_session.execute(
                    text(
                        "SELECT id::text FROM episodes "
                        "WHERE embedding IS NOT NULL "
                        "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 10"
                    ),
                    {"q": probe},
                )
            ).all()
            approx = {r[0] for r in rows}
            overlaps.append(len(approx & truth_set) / 10.0)
        return sum(overlaps) / len(overlaps)

    low = await _recall_at_10(Preset.MEMORY)
    high = await _recall_at_10(Preset.RESEARCH)
    # RESEARCH should always weakly dominate MEMORY on recall. Use a tiny
    # tolerance so pathological corpus shapes don't flake the test.
    assert high + 1e-9 >= low, f"Expected RESEARCH recall >= MEMORY recall, got {high=} {low=}"
