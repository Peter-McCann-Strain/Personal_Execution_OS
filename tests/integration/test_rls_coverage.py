"""RLS coverage contract for every account-scoped public table.

Boots a ``pgvector/pgvector:pg16`` container (via testcontainers), runs
``alembic upgrade head``, then asserts account tables have both RLS enabled
and the account-isolation policy installed.

This test is the counterpart to the deploy-gate step wired into
``.github/workflows/deploy-release.yml`` and the ``--check`` mode of
``scripts/enable_rls.py``.

Gracefully skips when Docker is unreachable so the rest of the suite
stays fast on laptops without a local daemon.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "src" / "app" / "persistence" / "migrations"
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


# --- Docker reachability probe ----------------------------------------------


def _docker_reachable() -> bool:
    """Return True when a Docker daemon is reachable, False otherwise."""
    if shutil.which("docker") is None and not os.environ.get("DOCKER_HOST"):
        return False
    try:
        from testcontainers.core.docker_client import DockerClient

        DockerClient().client.ping()
        return True
    except Exception:
        return False


DOCKER_REACHABLE = _docker_reachable()
_SKIP_REASON = "Docker daemon not reachable — RLS coverage test requires pgvector container"


@pytest.fixture(scope="module")
def pg_container() -> Iterator[object]:
    """Boot a pgvector/pgvector:pg16 container once per module."""
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
    container.start()
    try:
        yield container
    finally:
        container.stop()


def _async_url(container: object) -> str:
    host = container.get_container_host_ip()  # type: ignore[attr-defined]
    port = container.get_exposed_port(5432)  # type: ignore[attr-defined]
    return f"postgresql+asyncpg://test:test@{host}:{port}/test"


def _sync_url(container: object) -> str:
    host = container.get_container_host_ip()  # type: ignore[attr-defined]
    port = container.get_exposed_port(5432)  # type: ignore[attr-defined]
    return f"postgresql+psycopg://test:test@{host}:{port}/test"


def _alembic_config(async_url: str):
    from alembic.config import Config

    os.environ["DATABASE_URL"] = async_url
    # Flush the Settings lru_cache so env.py sees the new URL.
    from src.app import config as app_config

    app_config._settings = None

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", async_url)
    return cfg


@pytest.mark.skipif(not DOCKER_REACHABLE, reason=_SKIP_REASON)
def test_every_public_table_has_rls_enabled(pg_container) -> None:
    """After ``alembic upgrade head``, every account table is protected.

    This test is authoritative — the same query is shipped to production
    via ``scripts/enable_rls.py --check`` and run on every deploy.
    """
    from alembic import command
    from sqlalchemy import create_engine, text

    async_url = _async_url(pg_container)
    sync_url = _sync_url(pg_container)
    cfg = _alembic_config(async_url)

    command.upgrade(cfg, "head")

    sync_engine = create_engine(sync_url, future=True)

    with sync_engine.connect() as conn:
        remaining = sorted(
            conn.execute(
                text(
                    "WITH required AS ("
                    " SELECT DISTINCT c.oid, c.relname, c.relrowsecurity"
                    " FROM pg_class c"
                    " JOIN pg_namespace n ON n.oid = c.relnamespace"
                    " LEFT JOIN pg_attribute a ON a.attrelid = c.oid"
                    "  AND a.attname = 'account_id' AND NOT a.attisdropped"
                    " WHERE n.nspname = 'public' AND c.relkind = 'r'"
                    "  AND (a.attname IS NOT NULL OR c.relname IN ('accounts', 'users'))"
                    ")"
                    " SELECT relname FROM required"
                    " WHERE NOT relrowsecurity OR NOT EXISTS ("
                    "  SELECT 1 FROM pg_policy p"
                    "  WHERE p.polrelid = required.oid"
                    "   AND p.polname = 'app_account_isolation'"
                    " )"
                )
            ).scalars()
        )

    sync_engine.dispose()

    assert remaining == [], (
        f"RLS coverage gap — these public tables must have RLS enabled before deploy: {remaining}"
    )


@pytest.mark.skipif(not DOCKER_REACHABLE, reason=_SKIP_REASON)
def test_enable_rls_check_mode_exits_nonzero_when_gaps_exist(pg_container) -> None:
    """``enable_rls.py --check`` must exit non-zero when any public table
    is missing RLS, and zero when every table is protected.
    """
    import subprocess

    from alembic import command
    from sqlalchemy import create_engine, text

    async_url = _async_url(pg_container)
    sync_url = _sync_url(pg_container)
    cfg = _alembic_config(async_url)

    command.upgrade(cfg, "head")

    sync_engine = create_engine(sync_url, future=True)

    # Introduce a deliberate account-scoped schema gap.
    with sync_engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE rls_gap_probe (id uuid PRIMARY KEY, account_id uuid NOT NULL)")
        )

    env = os.environ.copy()
    env["DATABASE_URL"] = async_url
    proc_before = subprocess.run(
        ["python", "-m", "scripts.enable_rls", "--check"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_before.returncode != 0, (
        f"--check must fail when tables lack RLS. stdout={proc_before.stdout!r} "
        f"stderr={proc_before.stderr!r}"
    )
    assert "FAIL" in proc_before.stdout

    # Removing the deliberately invalid table restores a clean migration head.
    with sync_engine.begin() as conn:
        conn.execute(text("DROP TABLE rls_gap_probe"))
    sync_engine.dispose()

    proc_after = subprocess.run(
        ["python", "-m", "scripts.enable_rls", "--check"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_after.returncode == 0, proc_after.stdout + proc_after.stderr
    assert "OK" in proc_after.stdout
