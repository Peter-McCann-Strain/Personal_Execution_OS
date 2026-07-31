"""Tests for the memory API routes — search, entities, relationships."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import Principal, get_current_principal, get_db
from src.app.api.routes.memory import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _mock_get_db():
    """Yield a mock session so routes don't need a real DB."""
    yield AsyncMock()


def _build_app(*, override_auth: bool = True) -> FastAPI:
    """Create a minimal FastAPI app with the memory router for testing."""
    app = FastAPI()
    app.dependency_overrides[get_db] = _mock_get_db

    if override_auth:

        async def _always_principal() -> Principal:
            return Principal(
                subject="owner",
                external_subject=None,
                user_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
                account_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                role="owner",
                plan="pro",
                scopes=("admin",),
                auth_method="api_key",
            )

        app.dependency_overrides[get_current_principal] = _always_principal

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.include_router(router, prefix="/api/memory")
    return app


def _make_mock_entity(
    *,
    entity_id: uuid.UUID | None = None,
    name: str = "Alice",
    entity_type: str = "person",
    canonical_name: str | None = None,
    mention_count: int = 5,
) -> MagicMock:
    """Build a MagicMock that behaves like an Entity ORM instance."""
    now = datetime.now(UTC)
    m = MagicMock()
    m.id = entity_id or uuid.uuid4()
    m.name = name
    m.entity_type = entity_type
    m.canonical_name = canonical_name
    m.mention_count = mention_count
    m.first_seen = now
    m.last_seen = now
    m.metadata_ = {"source": "test"}
    m.created_at = now
    return m


def _make_mock_relationship(
    *,
    rel_id: uuid.UUID | None = None,
    source_entity_id: uuid.UUID | None = None,
    target_entity_id: uuid.UUID | None = None,
    relationship_type: str = "knows",
) -> MagicMock:
    """Build a MagicMock that behaves like an EntityRelationship ORM instance."""
    m = MagicMock()
    m.id = rel_id or uuid.uuid4()
    m.source_entity_id = source_entity_id or uuid.uuid4()
    m.target_entity_id = target_entity_id or uuid.uuid4()
    m.relationship_type = relationship_type
    m.valid_from = None
    m.valid_to = None
    m.created_at = datetime.now(UTC)
    return m


# ---------------------------------------------------------------------------
# POST /memory/search
# ---------------------------------------------------------------------------


async def test_search_memory_with_results():
    """POST /memory/search returns MemoryAnswer with sources when results found."""
    mock_rows = [
        {
            "id": uuid.uuid4(),
            "summary": "Morning walk entry",
            "content": "Had a great morning walk today.",
            "rank": 0.85,
        },
    ]

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with (
        patch(
            "src.app.api.routes.memory.search_episodes_bm25",
            new_callable=AsyncMock,
            return_value=mock_rows,
        ),
        patch(
            "src.app.api.routes.memory.search_notes",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.memory.search_saved_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.memory.search_connector_documents",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/memory/search",
                json={"query": "morning walk"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "Morning walk entry"
    assert data["confidence"] == 0.2  # 1 result / 5.0
    assert len(data["sources"]) == 1
    assert data["sources"][0]["source_type"] == "episode"
    assert data["sources"][0]["source_label"] == "Recent chat"
    assert data["sources"][0]["relevance_score"] == 0.85
    assert len(data["follow_up_suggestions"]) == 3


async def test_search_memory_no_results():
    """POST /memory/search returns empty answer when no results found."""
    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with (
        patch(
            "src.app.api.routes.memory.search_episodes_bm25",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.memory.search_notes",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.memory.search_saved_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.memory.search_connector_documents",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/memory/search",
                json={"query": "something nonexistent"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "No matching memories found."
    assert data["confidence"] == 0.0
    assert data["sources"] == []
    assert data["follow_up_suggestions"] == []


async def test_search_memory_ignores_empty_summary_and_content():
    """Rows without summary or content should still return a source but no summary text."""
    mock_rows = [
        {
            "id": uuid.uuid4(),
            "summary": "",
            "content": "",
            "rank": 0.33,
        },
    ]

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with (
        patch(
            "src.app.api.routes.memory.search_episodes_bm25",
            new_callable=AsyncMock,
            return_value=mock_rows,
        ),
        patch(
            "src.app.api.routes.memory.search_notes",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.memory.search_saved_memories",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.memory.search_connector_documents",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/memory/search",
                json={"query": "blank row"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "No matching memories found."
    assert data["sources"][0]["content"] == ""
    assert data["sources"][0]["relevance_score"] == 0.33


async def test_search_memory_sensitive_mode_suppresses_saved_and_connector_sources():
    """Sensitive mode should omit explicit memories and synced connector documents."""
    memory_row = MagicMock()
    memory_row.id = uuid.uuid4()
    memory_row.title = "Private preference"
    memory_row.content = "Only use this outside sensitive mode."
    memory_row.scope = "global"

    connector_row = MagicMock()
    connector_row.id = uuid.uuid4()
    connector_row.title = "Inbox thread"
    connector_row.content = "Synced connector content"
    connector_row.source_url = "https://example.com/thread"
    connector_row.source_type = "gmail_message"

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with (
        patch(
            "src.app.api.routes.memory.search_episodes_bm25",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.memory.search_notes",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.api.routes.memory.search_saved_memories",
            new_callable=AsyncMock,
            return_value=[memory_row],
        ) as search_saved,
        patch(
            "src.app.api.routes.memory.search_connector_documents",
            new_callable=AsyncMock,
            return_value=[connector_row],
        ) as search_connectors,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/memory/search",
                json={"query": "private", "sensitive_mode": True},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["sources"] == []
    search_saved.assert_not_awaited()
    search_connectors.assert_not_awaited()


# ---------------------------------------------------------------------------
# GET /memory/entities
# ---------------------------------------------------------------------------


async def test_list_entities_success():
    """GET /memory/entities returns list of EntityDTO."""
    entity = _make_mock_entity()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [entity]
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/memory/entities")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "Alice"
    assert data[0]["entity_type"] == "person"
    assert data[0]["mention_count"] == 5


async def test_list_entities_with_search():
    """GET /memory/entities?search=... uses trigram search."""
    entity = _make_mock_entity(name="Alice Smith")

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [entity]
    mock_session.execute = AsyncMock(return_value=mock_result)

    search_results = [
        {
            "id": entity.id,
            "name": "Alice Smith",
            "entity_type": "person",
            "mention_count": 5,
            "sim": 0.9,
        }
    ]

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.memory.search_entities",
        new_callable=AsyncMock,
        return_value=search_results,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/memory/entities",
                params={"search": "alice"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "Alice Smith"


# ---------------------------------------------------------------------------
# GET /memory/entities/relationships
# ---------------------------------------------------------------------------


async def test_list_relationships_success():
    """GET /memory/entities/relationships returns list of EntityRelationshipDTO."""
    rel = _make_mock_relationship()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [rel]
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/memory/entities/relationships")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["relationship_type"] == "knows"


# ---------------------------------------------------------------------------
# GET /memory/entities/{entity_id}
# ---------------------------------------------------------------------------


async def test_get_entity_success():
    """GET /memory/entities/{id} returns the entity DTO."""
    entity_id = uuid.uuid4()
    entity = _make_mock_entity(entity_id=entity_id, name="Bob")

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=entity)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/memory/entities/{entity_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(entity_id)
    assert data["name"] == "Bob"


async def test_get_entity_not_found():
    """GET /memory/entities/{id} returns 404 when entity does not exist."""
    entity_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/memory/entities/{entity_id}")

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "not_found"


async def test_find_related_entities_success():
    """GET /memory/entities/{id}/related returns related entity DTOs."""
    entity_id = uuid.uuid4()
    rows = [
        {
            "id": uuid.uuid4(),
            "name": "Redis",
            "entity_type": "concept",
            "relationship_type": "references",
            "depth": 1,
        }
    ]

    mock_session = AsyncMock()

    async def _mock_db():
        yield mock_session

    app = _build_app()
    app.dependency_overrides[get_db] = _mock_db

    with patch(
        "src.app.api.routes.memory.repo_find_related_entities",
        new_callable=AsyncMock,
        return_value=rows,
    ) as mock_related:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/memory/entities/{entity_id}/related",
                params={"max_depth": 3, "limit": 5},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data == [
        {
            "id": str(rows[0]["id"]),
            "name": "Redis",
            "entity_type": "concept",
            "relationship_type": "references",
            "depth": 1,
        }
    ]
    mock_related.assert_awaited_once_with(
        mock_session,
        entity_id=entity_id,
        max_depth=3,
        limit=5,
    )
