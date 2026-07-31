"""Integration tests for contacts endpoints through the full FastAPI app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_contact(
    *,
    contact_id: uuid.UUID | None = None,
    first_name: str = "Alice",
    last_name: str | None = "Smith",
    email: str | None = "alice@example.com",
    tags: list[str] | None = None,
    how_we_met: str | None = "Conference",
    interaction_frequency_days: int | None = 14,
    relationship_score: float = 75.0,
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    contact = MagicMock()
    contact.id = contact_id or uuid.uuid4()
    contact.first_name = first_name
    contact.last_name = last_name
    contact.email = email
    contact.tags = tags or ["friend"]
    contact.how_we_met = how_we_met
    contact.interaction_frequency_days = interaction_frequency_days
    contact.relationship_score = relationship_score
    contact.last_interaction_at = now
    contact.created_at = now
    contact.updated_at = now
    return contact


def _make_interaction(*, contact_id: uuid.UUID | None = None) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    interaction = MagicMock()
    interaction.id = uuid.uuid4()
    interaction.contact_id = contact_id or uuid.uuid4()
    interaction.interaction_type = "meeting"
    interaction.direction = "outgoing"
    interaction.channel = "in-person"
    interaction.summary = "Had coffee together"
    interaction.topics = ["project", "catch-up"]
    interaction.interaction_at = now
    interaction.created_at = now
    return interaction


class TestContactsContracts:
    """Verify contacts response contracts through the real app router."""

    async def test_list_contacts_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [_make_contact()]
        mock_session.execute = AsyncMock(side_effect=[count_result, list_result])

        response = await client.get("/api/contacts")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["page"] == 1
        assert data["page_size"] == 25
        assert data["has_more"] is False
        assert len(data["items"]) == 1
        assert data["items"][0]["first_name"] == "Alice"

    async def test_list_contacts_contract_with_filters(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [
            _make_contact(first_name="Alicia", tags=["friend", "work"]),
        ]
        mock_session.execute = AsyncMock(side_effect=[count_result, list_result])

        response = await client.get(
            "/api/contacts",
            params={
                "search": "Ali",
                "tags": "friend, work",
                "score_min": 50,
                "score_max": 90,
                "sort": "name",
                "limit": 5,
                "offset": 2,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["page_size"] == 5
        assert len(data["items"]) == 1
        assert data["items"][0]["first_name"] == "Alicia"
        assert data["items"][0]["tags"] == ["friend", "work"]

    async def test_search_contacts_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        rows = [
            {
                "id": uuid.uuid4(),
                "first_name": "Alice",
                "last_name": "Smith",
                "email": "alice@example.com",
                "tags": ["friend"],
                "relationship_score": 88.0,
            }
        ]

        with patch(
            "src.app.api.routes.contacts.repo_search_contacts",
            new_callable=AsyncMock,
            return_value=rows,
        ):
            response = await client.get("/api/contacts/search", params={"q": "Alice"})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["first_name"] == "Alice"
        assert data[0]["relationship_score"] == 88.0

    async def test_get_contact_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        contact_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.contacts.repo_get_contact_by_id",
            new_callable=AsyncMock,
            return_value=_make_contact(contact_id=contact_id),
        ):
            response = await client.get(f"/api/contacts/{contact_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(contact_id)
        assert data["first_name"] == "Alice"
        assert data["relationship_score"] == 75.0

    async def test_get_contact_not_found_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        contact_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.contacts.repo_get_contact_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"/api/contacts/{contact_id}")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_create_contact_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        contact_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.contacts.repo_create_contact",
            new_callable=AsyncMock,
            return_value=_make_contact(contact_id=contact_id, first_name="Bob", last_name="Jones"),
        ) as create_contact:
            response = await client.post(
                "/api/contacts",
                json={"first_name": "Bob", "last_name": "Jones"},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(contact_id)
        assert data["first_name"] == "Bob"
        assert data["last_name"] == "Jones"
        create_contact.assert_awaited_once()
        mock_session.refresh.assert_awaited()

    async def test_create_contact_rejects_invalid_email_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client

        response = await client.post(
            "/api/contacts",
            json={"first_name": "Bob", "email": "not-an-email"},
        )

        assert response.status_code == 422
        assert response.json()["error"] == "validation_error"

    async def test_list_contact_interactions_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        contact_id = uuid.uuid4()
        mock_session.get = AsyncMock(return_value=_make_contact(contact_id=contact_id))
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [
            _make_interaction(contact_id=contact_id)
        ]
        mock_session.execute = AsyncMock(return_value=list_result)

        response = await client.get(f"/api/contacts/{contact_id}/interactions")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["contact_id"] == str(contact_id)
        assert data[0]["interaction_type"] == "meeting"

    async def test_log_interaction_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        contact_id = uuid.uuid4()

        with (
            patch(
                "src.app.api.routes.contacts.repo_get_contact_by_id",
                new_callable=AsyncMock,
                return_value=_make_contact(contact_id=contact_id),
            ),
            patch(
                "src.app.api.routes.contacts.repo_log_interaction",
                new_callable=AsyncMock,
                return_value=_make_interaction(contact_id=contact_id),
            ) as log_interaction,
        ):
            response = await client.post(
                f"/api/contacts/{contact_id}/interactions",
                json={
                    "interaction_type": "meeting",
                    "direction": "outgoing",
                    "channel": "in-person",
                    "summary": "Had coffee together",
                    "topics": ["project", "catch-up"],
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert data["contact_id"] == str(contact_id)
        assert data["summary"] == "Had coffee together"
        log_interaction.assert_awaited_once()
        mock_session.refresh.assert_awaited()

    async def test_log_interaction_not_found_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        contact_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.contacts.repo_get_contact_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.post(
                f"/api/contacts/{contact_id}/interactions",
                json={
                    "interaction_type": "meeting",
                    "direction": "outgoing",
                    "summary": "Had coffee together",
                },
            )

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_decaying_contacts_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client

        with patch(
            "src.app.api.routes.contacts.repo_get_decaying_relationships",
            new_callable=AsyncMock,
            return_value=[_make_contact()],
        ):
            response = await client.get("/api/contacts/decaying")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["first_name"] == "Alice"
        assert data[0]["relationship_health"] is not None
