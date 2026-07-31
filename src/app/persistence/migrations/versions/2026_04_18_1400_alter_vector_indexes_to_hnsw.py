"""Ensure every pgvector column is backed by an HNSW index with tuned params.

Phase 7.7 — HNSW tuning.

Why this migration exists
-------------------------

The initial schema (migration ``001_initial_schema``) and the control-plane
migration (``007_world_class_control_plane``) already declared HNSW indexes
for ``episodes.embedding``, ``notes.embedding`` and
``connector_documents.embedding``. However:

1. Some production databases were created out-of-band (see the 2026-04-18
   web-push fix for precedent). They may still carry pre-HNSW IVFFLAT
   indexes — or no vector index at all — which silently degrades recall
   and latency once the corpus grows beyond a few thousand rows.
2. pgvector 0.8.0 ships iterative index scanning and better filter cost
   estimation. We want to re-create the indexes cleanly under that version
   so the planner's statistics are fresh and ``maintenance_work_mem`` is
   explicitly raised during the build (default 64 MB is too small to
   construct ``ef_construction`` >= 64 without thrashing spill files).
3. We wanted a single, idempotent, auditable migration that we can point
   ops runbooks at — rather than scattering the HNSW state across two
   earlier migrations.

What this migration does
------------------------

For each vector column:

* ``SET LOCAL maintenance_work_mem = '1GB';`` (only affects this txn).
* ``DROP INDEX IF EXISTS`` both the known legacy IVFFLAT name
  (``ix_<table>_embedding_ivfflat``) and the existing HNSW name
  (``ix_<table>_embedding_hnsw``). Idempotent — if neither exists the
  statement is a no-op.
* ``CREATE INDEX IF NOT EXISTS ix_<table>_embedding_hnsw ... USING hnsw``
  with ``m = 16``, ``ef_construction = 64`` and ``vector_cosine_ops``
  (matches how nomic-embed-text-v2-moe output is scored at query time).

These parameters are the pgvector 0.8.0 recommended starting point for
corpora in the 10k-1M vector range on a modest 8 GB host.
``ef_construction`` can be raised to 128/256 in a follow-up
when the corpus justifies it — this migration only establishes the floor.

Why we do NOT migrate column type to halfvec here
-------------------------------------------------

``halfvec(768)`` would halve storage (roughly 3 kB -> 1.5 kB per row) and
nomic-embed-text-v2-moe's 768-d float32 output fits losslessly-enough
for cosine retrieval. However the SQLAlchemy ORM models still declare
``Vector(768)``. Flipping the column type now would:

* Create a permanent drift between ORM and DB that ``alembic revision
  --autogenerate`` would try to "fix" on every future run.
* Require touching every repository that casts ``:embedding AS vector``
  (see ``src/app/persistence/repositories/vector.py``).

The halfvec switchover will happen in a dedicated follow-up migration
once the ORM type is swapped too. This migration is intentionally index-
only so it is trivially reversible.

Rollback
--------

``downgrade()`` drops the HNSW index and re-creates an IVFFLAT index with
``lists = 100`` (pgvector default heuristic for ~100k rows). That's an
approximation of the pre-HNSW state — enough to keep query paths
functional while an operator decides next steps.

Revision ID: a4b5c6d7e8f9
Revises: f2a3b4c5d6e7
Create Date: 2026-04-18 14:00:00.000000+00:00

Linear chain (resolved 2026-04-18 after sibling migrations landed in the
same push):
  c9d0e1f2a3b4  (009_web_push_subscriptions)
  d0e1f2a3b4c5  (2026_04_18_1200_add_deleted_at_to_web_push_subscriptions)
  e1f2a3b4c5d6  (010_dlq_jobs)
  f2a3b4c5d6e7  (2026_04_18_1300_add_idempotency_keys)
  a4b5c6d7e8f9  (2026_04_18_1400_alter_vector_indexes_to_hnsw)   ← this
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table_name, column_name) for every vector column we manage.
# Keep this in sync with `Vector(` usages in src/app/persistence/models.py.
_VECTOR_COLUMNS: tuple[tuple[str, str], ...] = (
    ("episodes", "embedding"),
    ("notes", "embedding"),
    ("connector_documents", "embedding"),
)

_HNSW_M = 16
_HNSW_EF_CONSTRUCTION = 64
_IVFFLAT_LISTS = 100
_MAINTENANCE_WORK_MEM = "1GB"


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _hnsw_index_name(table: str) -> str:
    return f"ix_{table}_embedding_hnsw"


def _ivfflat_index_name(table: str) -> str:
    return f"ix_{table}_embedding_ivfflat"


def upgrade() -> None:
    # Raise maintenance_work_mem for the duration of this transaction so
    # CREATE INDEX ... USING hnsw with ef_construction >= 64 doesn't spill
    # to disk. SET LOCAL reverts at COMMIT; it never leaks to other
    # sessions.
    op.execute(sa.text(f"SET LOCAL maintenance_work_mem = '{_MAINTENANCE_WORK_MEM}'"))

    for table, column in _VECTOR_COLUMNS:
        if not _has_table(table):
            # Migration 007 is conditional on schema state too — skip any
            # table that hasn't been created yet.
            continue

        hnsw_name = _hnsw_index_name(table)
        ivfflat_name = _ivfflat_index_name(table)

        # Drop both the legacy IVFFLAT name and the existing HNSW name.
        # IF EXISTS makes this a no-op when they're missing, so the
        # migration is safe to re-run or to apply against environments
        # where the original 001 migration already planted the HNSW
        # index correctly.
        op.execute(sa.text(f"DROP INDEX IF EXISTS {ivfflat_name}"))
        op.execute(sa.text(f"DROP INDEX IF EXISTS {hnsw_name}"))

        op.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS {hnsw_name} "
                f"ON {table} USING hnsw ({column} vector_cosine_ops) "
                f"WITH (m = {_HNSW_M}, ef_construction = {_HNSW_EF_CONSTRUCTION})"
            )
        )


def downgrade() -> None:
    # On downgrade we fall back to IVFFLAT(lists=100) which approximates
    # the pre-HNSW state. Operators running the downgrade should plan to
    # ANALYZE the tables afterwards to refresh the planner's statistics.
    op.execute(sa.text(f"SET LOCAL maintenance_work_mem = '{_MAINTENANCE_WORK_MEM}'"))

    for table, column in _VECTOR_COLUMNS:
        if not _has_table(table):
            continue

        hnsw_name = _hnsw_index_name(table)
        ivfflat_name = _ivfflat_index_name(table)

        op.execute(sa.text(f"DROP INDEX IF EXISTS {hnsw_name}"))
        op.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS {ivfflat_name} "
                f"ON {table} USING ivfflat ({column} vector_cosine_ops) "
                f"WITH (lists = {_IVFFLAT_LISTS})"
            )
        )
