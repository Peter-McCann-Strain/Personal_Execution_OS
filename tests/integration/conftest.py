"""Integration test fixtures.

Two fixture families live here:

1. **Mocked-session fixtures** (`integration_client`, `mock_anthropic_client`) -
   original pattern, fast, no Docker. Used by most existing files until they
   are migrated.

2. **Real-database fixtures** (`postgres_container`, `db_engine`,
   `db_session`, `db_integration_client`) - spin up a `pgvector/pgvector:pg16`
   container via testcontainers, enable `vector`, `ltree`, `pg_trgm`, run
   Alembic migrations, and yield a savepoint-rolled-back `AsyncSession`.
   Tests that use these fixtures exercise real SQL behaviour.

The real-DB fixtures gracefully `pytest.skip` the test when Docker is not
reachable, so contributors without a local Docker daemon can still run the
rest of the suite.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Set test environment before importing app
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")

# Resolved at import time so the async migration fixture doesn't trip ASYNC240.
_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def mock_anthropic_client():
    """Mock Anthropic client for integration tests."""
    client = AsyncMock()
    return client


def make_anthropic_response(text: str, input_tokens: int = 50, output_tokens: int = 100):
    """Build a mock Anthropic API response."""
    content_block = MagicMock()
    content_block.type = "text"
    content_block.text = text

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    response = MagicMock()
    response.content = [content_block]
    response.usage = usage
    response.model = "claude-haiku-4-5-20251001"
    return response


@pytest_asyncio.fixture
async def integration_client(mock_anthropic_client):
    """FastAPI test client with mocked dependencies for integration tests.

    Yields a tuple of (AsyncClient, mock_session, mock_anthropic_client) so
    tests can configure mock return values on the session and LLM client.

    The full app (create_app()) is used — lifespan is disabled via a patch
    so that we don't need real Postgres, Redis, Telegram, etc.
    """
    from src.app.api.deps import get_anthropic_client, get_db, verify_api_key
    from src.app.api.idempotency import IdempotencyMiddleware
    from src.app.api.rate_limiting import _counter
    from src.app.main import create_app

    # Build a fresh app so dependency overrides don't leak between tests
    app = create_app()
    # These fast route-contract tests use a mocked database. Idempotency has
    # separate middleware unit tests and real-Postgres integration coverage.
    app.user_middleware = [
        middleware
        for middleware in app.user_middleware
        if middleware.cls is not IdempotencyMiddleware
    ]
    app.middleware_stack = None

    # Reset the global in-memory rate limiter so one test file does not poison another.
    with _counter._lock:
        _counter._requests.clear()

    # --- Mock database session ---
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    mock_session.add = MagicMock()
    mock_session.begin = MagicMock()
    # Make begin() work as async context manager
    mock_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    async def override_db():
        yield mock_session

    async def override_verify():
        return "owner"

    def override_anthropic(_request=None):
        return mock_anthropic_client

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[verify_api_key] = override_verify
    app.dependency_overrides[get_anthropic_client] = override_anthropic

    # Disable the lifespan entirely so we don't need real services
    app.router.lifespan_context = _null_lifespan

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": os.environ["CHAT_API_KEY"]},
    ) as client:
        yield client, mock_session, mock_anthropic_client

    with _counter._lock:
        _counter._requests.clear()

    app.dependency_overrides.clear()


@asynccontextmanager
async def _null_lifespan(_app: object) -> AsyncIterator[None]:
    """No-op lifespan that skips DB/Redis/Telegram/telemetry init."""
    yield


# ---------------------------------------------------------------------------
# Real-database fixtures (testcontainers + pgvector)
#
# Usage in a test:
#
#     async def test_my_thing(db_integration_client):
#         client, session = db_integration_client
#         # ... insert ORM rows via session, hit routes via client ...
#
# A single pgvector container is shared across the whole test session
# (session-scoped). Each test gets an isolated transaction that is rolled
# back on teardown (function-scoped savepoint pattern).
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    """Return True if a Docker-compatible daemon is reachable."""
    if shutil.which("docker") is None:
        return False
    try:
        # Docker contexts such as Colima do not necessarily expose the active
        # daemon at /var/run/docker.sock. Test through the same client library
        # that testcontainers uses so a reachable context is not skipped.
        from testcontainers.core.docker_client import DockerClient

        DockerClient().client.ping()
    except Exception:
        return False
    else:
        return True


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[object]:
    """Start a pgvector/pgvector:pg16 container for the whole test session."""
    if not _docker_available():
        pytest.skip("Docker daemon unavailable - skipping real-Postgres tests")

    from testcontainers.postgres import PostgresContainer

    # The pgvector image is Debian-based PG16 with the `vector` extension
    # precompiled. ltree and pg_trgm ship with the base postgres image.
    container = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="test",
        password="test",
        dbname="test",
        driver=None,  # we build our own asyncpg URL below
    ).with_env("POSTGRES_HOST_AUTH_METHOD", "trust")
    container.start()
    try:
        yield container
    finally:
        container.stop()


def _async_url_for(container: object) -> str:
    """Return an asyncpg-style URL for a running PostgresContainer."""
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    return f"postgresql+asyncpg://test:test@{host}:{port}/test"


@pytest_asyncio.fixture
async def db_engine(postgres_container):
    """Create a loop-local engine, run Alembic migrations, and yield it.

    Migrations are driven directly via `command.upgrade` bound to our async
    engine through `connection.run_sync`, which sidesteps env.py entirely
    and means the app's Settings singleton is untouched. The PostgreSQL
    container remains session-scoped, while each test gets an engine created
    on its own event loop to avoid cross-loop asyncpg connections.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.ext.asyncio import create_async_engine

    url = _async_url_for(postgres_container)
    engine = create_async_engine(url, echo=False, future=True)

    # Enable required extensions. `vector` is provided by the pgvector image;
    # `ltree` and `pg_trgm` ship with every stock Postgres build.
    async with engine.begin() as conn:
        await conn.exec_driver_sql('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS ltree")
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    alembic_cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option(
        "script_location",
        str(_REPO_ROOT / "src/app/persistence/migrations"),
    )

    def _run_upgrade(sync_connection) -> None:
        alembic_cfg.attributes["connection"] = sync_connection
        command.upgrade(alembic_cfg, "head")

    async with engine.begin() as conn:
        await conn.run_sync(_run_upgrade)

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Yield an AsyncSession wrapped in a transaction rolled back on teardown.

    Uses the SQLAlchemy "nested savepoint on rollback" pattern so each test
    sees a clean DB without having to re-run migrations.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    async with db_engine.connect() as connection:
        trans = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            try:
                yield session
            finally:
                await session.close()
                if trans.is_active:
                    await trans.rollback()


@pytest_asyncio.fixture
async def db_integration_client(db_engine, mock_anthropic_client):
    """FastAPI client backed by a real container DB session.

    Yields `(AsyncClient, AsyncSession)`. The session is transactional and
    rolled back at test end. Anthropic is still mocked so tests remain
    deterministic and don't hit a paid API.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.app.api.deps import get_anthropic_client, get_db, verify_api_key
    from src.app.api.rate_limiting import _counter
    from src.app.main import create_app
    from src.app.persistence import database as database_module

    app = create_app()
    original_session_factory = database_module._session_factory
    database_module._session_factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    with _counter._lock:
        _counter._requests.clear()

    session = AsyncSession(bind=db_engine, expire_on_commit=False)

    async def override_db():
        # Yield the same session for every request in this test so direct
        # fixture inserts are visible through the API.
        yield session

    async def override_verify():
        return "owner"

    def override_anthropic(_request=None):
        return mock_anthropic_client

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[verify_api_key] = override_verify
    app.dependency_overrides[get_anthropic_client] = override_anthropic
    app.router.lifespan_context = _null_lifespan

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": os.environ["CHAT_API_KEY"]},
        ) as client:
            yield client, session
    finally:
        await session.rollback()
        await session.close()
        # Middleware-owned sessions commit independently, so an outer
        # transaction cannot isolate these tests. Clean every application
        # table while preserving Alembic's revision marker.
        async with db_engine.begin() as connection:
            result = await connection.exec_driver_sql(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
            tables = [str(row[0]) for row in result]
            if tables:
                quoted = ", ".join(f'"{name.replace(chr(34), chr(34) * 2)}"' for name in tables)
                await connection.exec_driver_sql(
                    f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"
                )
            # The product-foundation migration creates the local owner that
            # subsequent account-scoped tests rely on. Recreate that seed
            # after isolation cleanup because this container is reused.
            await connection.exec_driver_sql(
                """
                INSERT INTO accounts (id, name, slug, status, plan)
                VALUES (
                  '00000000-0000-0000-0000-000000000001'::uuid,
                  'Owner Account',
                  'owner',
                  'active',
                  'pro'
                )
                """
            )
            await connection.exec_driver_sql(
                """
                INSERT INTO users (id, clerk_user_id, email, display_name, status)
                VALUES (
                  '00000000-0000-0000-0000-000000000010'::uuid,
                  'seeded-owner',
                  'owner@example.com',
                  'Owner',
                  'active'
                )
                """
            )
            await connection.exec_driver_sql(
                """
                INSERT INTO account_memberships (id, account_id, user_id, role, status)
                VALUES (
                  gen_random_uuid(),
                  '00000000-0000-0000-0000-000000000001'::uuid,
                  '00000000-0000-0000-0000-000000000010'::uuid,
                  'owner',
                  'active'
                )
                """
            )
        with _counter._lock:
            _counter._requests.clear()
        app.dependency_overrides.clear()
        database_module._session_factory = original_session_factory
