# Integration tests

## What lives here

`tests/integration/` exercises the full FastAPI app, including routing,
middleware, auth, route handlers, and repositories. Expensive or unreliable
external systems such as Anthropic, Redis, and Telegram are mocked.

Two fixture families are available, defined in `conftest.py`:

| Fixture | Scope | DB backing | When to use |
| --- | --- | --- | --- |
| `integration_client` | function | `AsyncMock` session | Request/response contract tests that do not depend on PostgreSQL behavior. |
| `db_integration_client` | function | **Real Postgres + pgvector** (via testcontainers) | Tests that exercise SQL semantics: filtering, ordering, joins, aggregates, `tsvector`, `ltree`, vector distance, transactional side-effects. |

New code that depends on non-trivial SQL **must** use the real-DB fixture.
Leave mocked-session tests alone unless you have a reason to migrate one
(see the migration backlog below).

## Running integration tests

Standard run (requires a local Docker daemon if any real-DB tests are
selected. Otherwise those tests call `pytest.skip` cleanly):

```bash
uv run pytest tests/integration/ -x -v
```

Run *only* the real-DB pilot:

```bash
uv run pytest tests/integration/test_episodes_real_db.py -x -v
```

Skip the real-DB tests explicitly (useful when Docker is installed but you
don't want to spin a container):

```bash
uv run pytest tests/integration/ -k "not real_db" -x
```

## Requirements for the real-DB fixtures

* **Docker, OrbStack, or Colima** with a reachable daemon.
* The first run pulls `pgvector/pgvector:pg16` (about 400 MB). Later runs can
  reuse the local image.
* Python deps: `testcontainers[postgres]` and `psycopg[binary]` are pinned
  in `[dependency-groups].dev`.

If Docker is not available, the session-scoped `postgres_container`
fixture calls `pytest.skip`, so the rest of the suite still runs.

### Colima

The integration fixture inspects the active Docker CLI context before
Testcontainers is imported. When that context points to a live Colima Unix
socket, it configures:

```text
DOCKER_HOST=unix://${HOME}/.colima/default/docker.sock
TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock
```

The first path is the socket visible to Python on the macOS host. The second
is the socket path Ryuk must mount inside the Colima VM. Any values you export
yourself take precedence over automatic detection.

For a custom Colima profile or a Docker context that cannot be inspected,
provide both values before running pytest:

```bash
export DOCKER_HOST="unix://${HOME}/.colima/default/docker.sock"
export TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE="/var/run/docker.sock"
uv run pytest tests/integration/test_episodes_real_db.py -x -v
```

Useful diagnostics:

```bash
docker context show
docker context inspect
docker info
```

Do not disable Ryuk as a workaround. It is responsible for cleaning up
containers when a test process exits unexpectedly.

## Fixture pattern

```python
# Shared session-scoped container + migrated engine
@pytest.fixture(scope="session")
def postgres_container() -> Iterator[object]:
    # pulls pgvector/pgvector:pg16, starts, yields, stops

@pytest_asyncio.fixture(scope="session")
async def db_engine(postgres_container):
    # CREATE EXTENSION vector, ltree, pg_trgm; alembic upgrade head

# Per-test transactional session
@pytest_asyncio.fixture
async def db_session(db_engine):
    # yields AsyncSession bound to a rolled-back connection

# Full app + real DB + mocked Anthropic
@pytest_asyncio.fixture
async def db_integration_client(db_engine, mock_anthropic_client):
    # overrides get_db to return the same transactional session for
    # every request; yields (AsyncClient, AsyncSession)
```

Example test (see `test_episodes_real_db.py`):

```python
from src.app.persistence.models import Episode


async def test_list_episodes_returns_inserted_rows(db_integration_client):
    client, session = db_integration_client
    session.add(Episode(content="Morning walk", episode_type="diary"))
    await session.flush()

    response = await client.get("/api/episodes")

    assert response.status_code == 200
    assert response.json()["total"] == 1
```

Key invariants:

1. The container is **session-scoped**, so it boots once per `pytest`
   invocation.
2. Alembic runs migrations against the container exactly once, via a
   sync connection injected through `config.attributes["connection"]`
   in `src/app/persistence/migrations/env.py`.
3. Each test opens a connection, begins a transaction, yields an
   `AsyncSession` bound to it, then **rolls the transaction back on
   teardown**. Tests never see each other's writes.
4. `get_db` is overridden to return the same session for every HTTP
   request in the test, so changes made in the test body are visible
   to the route code.

## Mock-backed coverage

`test_episodes_real_db.py` uses the real database fixture. The files below
still use a mocked `AsyncSession`. Move a test to the real fixture when its
behavior depends on PostgreSQL rather than the HTTP contract.

| File | Priority | Notes |
| --- | --- | --- |
| `test_api_endpoints.py` | High | Largest file; covers episodes, goals, habits, notes CRUD. Ideal first real migration. |
| `test_memory_contracts.py` | High | Entities and relationships depend on `ltree` and `pg_trgm`, which mocks cannot reproduce. |
| `test_dashboard_contracts.py` | Medium | Heavy aggregate SQL (mood averages, counts). Mocks here are fragile. |
| `test_habits_contracts.py` | Medium | Streak logic. |
| `test_projects_contracts.py` | Medium | WBS + WSJF ordering. |
| `test_goals_contracts.py` | Medium | Self-referential `parent_id`; its cascade behaviour is worth testing live. |
| `test_decisions_contracts.py` | Low | Mostly CRUD contracts; mocks acceptable for now. |
| `test_calendar_contracts.py` | Low | Depends on Google OAuth mocks, not SQL. |
| `test_commitments_contracts.py` | Low | CRUD. |
| `test_contacts_contracts.py` | Low | CRUD. |
| `test_email_contracts.py` | Low | Depends on Gmail OAuth mocks, not SQL. |
| `test_monitoring_contracts.py` | Low | Mostly response-shape contracts. |
| `test_notes_contracts.py` | Low | CRUD. |
| `test_notifications_contracts.py` | Low | Depends on notification delivery, not SQL. |
| `test_reviews_contracts.py` | Low | Depends on review generation logic. |
| `test_tutorials_contracts.py` | Low | Static tutorial content. |
| `test_chat_contracts.py` | Skip | Pure routing and response-shape tests; keep them mocked. |
| `test_chat_routing.py` | Skip | Router classifier tests; keep them mocked. |
| `test_smoke_api.py` | Skip | Smoke-CLI probe, not a SQL test. |

## Adding a new real-DB test

1. Import ORM models from `src.app.persistence.models`.
2. Request `db_integration_client` in the test signature.
3. `session.add(...)` + `await session.flush()` to seed data.
4. Call `await client.get(...)` / `client.post(...)`. The route handler
   will see your seeded rows via the shared transactional session.
5. Do **not** call `session.commit()`. Commits break the savepoint
   rollback and leak state into subsequent tests.

## Running the HNSW migration on managed PostgreSQL

The migration `2026_04_18_1400_alter_vector_indexes_to_hnsw` rebuilds the
pgvector indexes on `episodes.embedding`, `notes.embedding` and
`connector_documents.embedding` with `m = 16, ef_construction = 64`.
`CREATE INDEX ... USING hnsw` with that `ef_construction` will spill to
disk unless `maintenance_work_mem` is at least ~1 GB.

The migration itself issues `SET LOCAL maintenance_work_mem = '1GB'` for
the transaction, which is normally sufficient on self-hosted PostgreSQL.
Managed providers can cap per-session `maintenance_work_mem` according to
the service tier or compute size.

Before running the migration on a managed provider:

1. Check the provider's allowed `maintenance_work_mem` and available memory.
   Increase the database compute size for the migration window if required.
2. If supported, temporarily set `maintenance_work_mem = '1GB'` for the
   migration session or cluster.
3. Apply the migration:

   ```bash
   uv run alembic upgrade head
   ```

4. Revert any temporary compute or configuration increase after the
   migration. Runtime queries can use the normal memory setting once the
   HNSW index exists.

If you cannot grant the session enough memory, the safest alternative is
to test the migration against a restored clone and plan a controlled cutover
instead of letting the live database thrash while re-indexing.
