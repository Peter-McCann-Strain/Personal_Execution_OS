"""Integration tests for memory endpoints through the full FastAPI app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_entity(
    *,
    entity_id: uuid.UUID | None = None,
    name: str = "Alice",
    entity_type: str = "person",
    canonical_name: str | None = None,
    mention_count: int = 5,
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    entity = MagicMock()
    entity.id = entity_id or uuid.uuid4()
    entity.name = name
    entity.entity_type = entity_type
    entity.canonical_name = canonical_name
    entity.mention_count = mention_count
    entity.first_seen = now
    entity.last_seen = now
    entity.metadata_ = {"source": "test"}
    entity.created_at = now
    return entity


def _make_relationship(
    *,
    relationship_id: uuid.UUID | None = None,
    source_entity_id: uuid.UUID | None = None,
    target_entity_id: uuid.UUID | None = None,
    relationship_type: str = "knows",
) -> MagicMock:
    relationship = MagicMock()
    relationship.id = relationship_id or uuid.uuid4()
    relationship.source_entity_id = source_entity_id or uuid.uuid4()
    relationship.target_entity_id = target_entity_id or uuid.uuid4()
    relationship.relationship_type = relationship_type
    relationship.valid_from = None
    relationship.valid_to = None
    relationship.created_at = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    return relationship


class TestMemoryContracts:
    """Verify memory response contracts through the real app router."""

    async def test_search_memory_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        rows = [
            {
                "id": uuid.uuid4(),
                "summary": "Morning walk entry",
                "content": "Had a great morning walk today.",
                "rank": 0.85,
            }
        ]

        with patch(
            "src.app.api.routes.memory.search_episodes_bm25",
            new_callable=AsyncMock,
            return_value=rows,
        ):
            response = await client.post(
                "/api/search",
                json={"query": "morning walk"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Morning walk entry"
        assert data["confidence"] == 0.2
        assert len(data["sources"]) == 1
        assert data["sources"][0]["source_type"] == "episode"
        assert len(data["follow_up_suggestions"]) == 3

    async def test_list_entities_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        entity = _make_entity()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [entity]
        mock_session.execute = AsyncMock(return_value=result)

        response = await client.get("/api/entities")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Alice"
        assert data[0]["entity_type"] == "person"

    async def test_list_entities_with_search_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        entity = _make_entity(name="Alice Smith")
        result = MagicMock()
        result.scalars.return_value.all.return_value = [entity]
        mock_session.execute = AsyncMock(return_value=result)
        search_results = [
            {
                "id": entity.id,
                "name": "Alice Smith",
                "entity_type": "person",
                "mention_count": 5,
                "sim": 0.9,
            }
        ]

        with patch(
            "src.app.api.routes.memory.search_entities",
            new_callable=AsyncMock,
            return_value=search_results,
        ):
            response = await client.get("/api/entities", params={"search": "alice"})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Alice Smith"

    async def test_list_relationships_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        relationship = _make_relationship()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [relationship]
        mock_session.execute = AsyncMock(return_value=result)

        response = await client.get("/api/entities/relationships")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["relationship_type"] == "knows"

    async def test_get_entity_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        entity_id = uuid.uuid4()
        mock_session.get = AsyncMock(return_value=_make_entity(entity_id=entity_id))

        response = await client.get(f"/api/entities/{entity_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(entity_id)
        assert data["name"] == "Alice"

    async def test_get_entity_not_found_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        entity_id = uuid.uuid4()
        mock_session.get = AsyncMock(return_value=None)

        response = await client.get(f"/api/entities/{entity_id}")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_find_related_entities_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        entity_id = uuid.uuid4()
        rows = [
            {
                "id": uuid.uuid4(),
                "name": "Bob",
                "entity_type": "person",
                "relationship_type": "knows",
                "depth": 1,
            }
        ]

        with patch(
            "src.app.api.routes.memory.repo_find_related_entities",
            new_callable=AsyncMock,
            return_value=rows,
        ):
            response = await client.get(
                f"/api/entities/{entity_id}/related",
                params={"max_depth": 2, "limit": 20},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Bob"
        assert data[0]["relationship_type"] == "knows"
