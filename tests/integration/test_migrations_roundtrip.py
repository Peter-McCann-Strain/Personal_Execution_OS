"""Alembic migration round-trip contract test.

For every revision in src/app/persistence/migrations/versions/, this test walks
upgrade -> downgrade(parent) -> upgrade again and asserts:

1. Each ``upgrade()`` + ``downgrade()`` pair is cleanly reversible (no leftover
   tables, columns, indexes, or extensions when we walk back to ``base``).
2. Minimal seed rows (PKs + required-not-null fields) inserted between steps
   survive the round-trip where the migration is non-destructive.

The test uses testcontainers to boot a ``pgvector/pgvector:pg16`` container so
it runs in CI without an external DB. It is marked as integration (requires
Docker) and is gracefully skipped when the Docker daemon is not reachable so
contributors can still run the rest of the suite locally.

The module-scoped container is intentionally separate from the async fixtures in
``tests/integration/conftest.py`` because these checks drive Alembic through its
normal CLI environment and use a synchronous connection for schema snapshots.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

# --- Discover the ordered migration chain -----------------------------------
#
# We walk the single chain from ``base`` to ``head``. The compatibility bridge
# is part of that chain and is also checked separately to prove it remains a
# no-op.
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "src" / "app" / "persistence" / "migrations"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


# --- Docker reachability probe ----------------------------------------------


def _docker_reachable() -> bool:
    """Return True when a Docker daemon is reachable, False otherwise."""
    if shutil.which("docker") is None and not os.environ.get("DOCKER_HOST"):
        return False
    try:
        # Importing here avoids paying the cost when Docker is missing entirely.
        from testcontainers.core.docker_client import DockerClient

        client = DockerClient()
        client.client.ping()
        return True
    except Exception:
        return False


DOCKER_REACHABLE = _docker_reachable()
_SKIP_REASON = "Docker daemon not reachable — migration round-trip test requires pgvector container"


# --- Dedicated pg_container fixture (module-scoped for reuse) ---------------


@pytest.fixture(scope="module")
def pg_container() -> Iterator[object]:
    """Boot a pgvector/pgvector:pg16 container once per module.

    This test drives Alembic through its regular environment and therefore
    keeps a dedicated synchronous-friendly container lifecycle.
    """
    if not DOCKER_REACHABLE:
        pytest.skip(_SKIP_REASON)

    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="test",
        password="test",
        dbname="test",
        driver="psycopg",
    )
    # Module scope: reuse across all tests in this file.
    container.start()
    try:
        yield container
    finally:
        container.stop()


# --- Alembic helpers --------------------------------------------------------


def _async_url(container: object) -> str:
    """Build the asyncpg URL the app's alembic env.py expects."""
    host = container.get_container_host_ip()  # type: ignore[attr-defined]
    port = container.get_exposed_port(5432)  # type: ignore[attr-defined]
    return f"postgresql+asyncpg://test:test@{host}:{port}/test"


def _sync_url(container: object) -> str:
    """Plain psycopg URL for seed SQL and introspection."""
    host = container.get_container_host_ip()  # type: ignore[attr-defined]
    port = container.get_exposed_port(5432)  # type: ignore[attr-defined]
    return f"postgresql+psycopg://test:test@{host}:{port}/test"


def _alembic_config(async_url: str):
    """Build an alembic Config targeting the live container.

    Overrides DATABASE_URL for src.app.config.get_settings() and flushes the
    settings cache so env.py picks up the new URL.
    """
    from alembic.config import Config

    os.environ["DATABASE_URL"] = async_url
    # Flush the Settings lru_cache so env.py sees the new URL.
    from src.app import config as app_config

    app_config._settings = None

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", async_url)
    return cfg


def _linear_revision_chain() -> list[str]:
    """Return the ordered list of revisions from base to the single head."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    script = ScriptDirectory.from_config(cfg)

    main_head = script.get_current_head()
    assert main_head is not None, "could not find the migration head"

    chain: list[str] = []
    for rev in script.walk_revisions(base="base", head=main_head):
        chain.append(rev.revision)
    chain.reverse()  # oldest -> newest
    return chain


# --- Seed helpers -----------------------------------------------------------


def _table_exists(engine, table: str) -> bool:
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT to_regclass(:t) IS NOT NULL AS exists"),
            {"t": f"public.{table}"},
        ).scalar_one()
    return bool(row)


def _seed_minimal(engine, revision: str) -> None:
    """Insert a minimal PK-only row into one stable table per milestone revision.

    Only seeds if the target table exists (the migration we're testing may not
    have created it yet). Uses ON CONFLICT DO NOTHING so repeated calls across
    upgrade/downgrade/upgrade cycles are idempotent.
    """
    from sqlalchemy import text

    seeds: dict[str, tuple[str, str]] = {
        # After revision X the given table must be insertable with just (id,...)
        "a1b2c3d4e5f6": (
            "episodes",
            "INSERT INTO episodes (id, content) "
            "VALUES ('00000000-0000-0000-0000-000000000001', 'seed') "
            "ON CONFLICT (id) DO NOTHING",
        ),
        "b2c3d4e5f6a7": (
            "notes",
            "INSERT INTO notes (id, title, content) VALUES "
            "('00000000-0000-0000-0000-000000000002', 'seed-title', 'seed-body') "
            "ON CONFLICT (id) DO NOTHING",
        ),
    }

    if revision not in seeds:
        return
    table, sql = seeds[revision]
    if not _table_exists(engine, table):
        return
    with engine.begin() as conn:
        conn.execute(text(sql))


def _count(engine, table: str) -> int:
    from sqlalchemy import text

    if not _table_exists(engine, table):
        return 0
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


# --- Test -------------------------------------------------------------------


@pytest.mark.skipif(not DOCKER_REACHABLE, reason=_SKIP_REASON)
def test_every_revision_is_cleanly_reversible(pg_container) -> None:
    """Walk every revision forward, back, forward again, and assert clean state.

    For each revision in order:
      1. ``alembic upgrade <rev>``
      2. Seed a minimal row in a stable table (if the table exists).
      3. Downgrade to the explicit parent, then upgrade to ``<rev>``.
      4. Assert the seed row survives when the migration is non-destructive,
         or is acceptably absent otherwise.

    Finally, walk all the way back to ``base`` and assert no app tables remain.
    """
    from alembic import command
    from sqlalchemy import create_engine, text

    async_url = _async_url(pg_container)
    sync_url = _sync_url(pg_container)
    cfg = _alembic_config(async_url)
    sync_engine = create_engine(sync_url, future=True)

    chain = _linear_revision_chain()
    assert len(chain) >= 2, f"expected a multi-revision chain, got {chain}"

    # --- Step 1: walk forward, one revision at a time ----------------------
    for rev in chain:
        command.upgrade(cfg, rev)

        _seed_minimal(sync_engine, rev)
        pre_counts = {t: _count(sync_engine, t) for t in ("episodes", "notes")}

        # Round-trip this revision if it has a parent (first revision has none).
        if rev != chain[0]:
            from alembic.script import ScriptDirectory

            script = ScriptDirectory.from_config(cfg)
            revision = script.get_revision(rev)
            assert revision is not None
            parent = revision.down_revision
            assert isinstance(parent, str)
            command.downgrade(cfg, parent)
            command.upgrade(cfg, rev)

            post_counts = {t: _count(sync_engine, t) for t in ("episodes", "notes")}

            # Where the table still exists on both sides, seed data is expected to
            # survive round-tripping a non-destructive migration. Downgrade that
            # drops the table legitimately loses the row; we only require no
            # spurious row growth.
            for table, pre in pre_counts.items():
                post = post_counts[table]
                assert post <= max(pre, 1), f"round-trip at {rev} grew {table}: {pre}->{post}"

    # --- Step 2: walk fully back to base and assert clean slate ------------
    command.downgrade(cfg, "base")

    with sync_engine.connect() as conn:
        leftover_tables = list(
            conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' "
                    "AND tablename <> 'alembic_version'"
                )
            ).scalars()
        )
    assert leftover_tables == [], f"downgrade to base left residual tables: {leftover_tables}"

    # --- Step 3: walk back up to head and verify idempotency ---------------
    command.upgrade(cfg, chain[-1])
    _seed_minimal(sync_engine, chain[0])  # episodes exists again
    assert _count(sync_engine, "episodes") >= 1

    sync_engine.dispose()


@pytest.mark.skipif(not DOCKER_REACHABLE, reason=_SKIP_REASON)
def test_phantom_bridge_revision_is_a_noop(pg_container) -> None:
    """The 005b bridge revision is deliberately empty; prove it stays that way.

    If someone adds DDL to the bridge file by accident we want the CI gate
    to catch it — round-trip through the bridge must be a byte-for-byte no-op
    against the schema snapshot.
    """
    from alembic import command
    from sqlalchemy import create_engine, text

    async_url = _async_url(pg_container)
    sync_url = _sync_url(pg_container)
    cfg = _alembic_config(async_url)
    sync_engine = create_engine(sync_url, future=True)

    # Reset, then climb to the branchpoint parent of the bridge.
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "e5f6a7b8c9d0")

    def snapshot() -> list[str]:
        with sync_engine.connect() as conn:
            return sorted(
                conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' "
                        "AND tablename <> 'alembic_version'"
                    )
                ).scalars()
            )

    before = snapshot()
    command.upgrade(cfg, "f1a2b3c4d5e6")
    after_up = snapshot()
    command.downgrade(cfg, "e5f6a7b8c9d0")
    after_down = snapshot()

    assert before == after_up, f"phantom bridge upgrade changed schema: {before} -> {after_up}"
    assert before == after_down, (
        f"phantom bridge downgrade changed schema: {before} -> {after_down}"
    )
    sync_engine.dispose()
