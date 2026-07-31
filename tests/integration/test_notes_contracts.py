"""Integration tests for notes endpoints through the full FastAPI app."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_note(
    *,
    note_id: uuid.UUID | None = None,
    title: str = "Atomic note",
    content: str = "A durable note about testing.",
) -> MagicMock:
    now = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    note = MagicMock()
    note.id = note_id or uuid.uuid4()
    note.title = title
    note.content = content
    note.note_type = "literature"
    note.para_category = "resource"
    note.tags = ["testing", "notes"]
    note.source_url = "https://example.com/testing"
    note.progressive_summary_level = 1
    note.executive_summary = "Testing note"
    note.created_at = now
    note.updated_at = now
    return note


class TestNotesContracts:
    """Verify notes response contracts through the real app router."""

    async def test_search_notes_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        rows = [
            {
                "id": uuid.uuid4(),
                "title": "Atomic note",
                "content": "A durable note about testing.",
                "note_type": "literature",
                "para_category": "resource",
                "tags": ["testing"],
                "created_at": datetime(2026, 3, 15, 10, 0, tzinfo=UTC),
            }
        ]

        with patch(
            "src.app.api.routes.notes.repo_search_notes",
            new_callable=AsyncMock,
            return_value=rows,
        ):
            response = await client.get("/api/notes/search", params={"q": "testing"})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Atomic note"
        assert data[0]["tags"] == ["testing"]

    async def test_create_note_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client

        with patch(
            "src.app.api.routes.notes.repo_create_note",
            new_callable=AsyncMock,
            return_value=_make_note(),
        ):
            response = await client.post(
                "/api/notes",
                json={"title": "Atomic note", "content": "A durable note about testing."},
            )

        assert response.status_code == 201
        assert response.json()["title"] == "Atomic note"
        mock_session.refresh.assert_awaited()

    async def test_get_note_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        note_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.notes.repo_get_note_by_id",
            new_callable=AsyncMock,
            return_value=_make_note(note_id=note_id),
        ):
            response = await client.get(f"/api/notes/{note_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(note_id)
        assert data["title"] == "Atomic note"

    async def test_update_note_contract(self, integration_client):
        client, mock_session, _mock_anthropic = integration_client
        note_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.notes.repo_update_note",
            new_callable=AsyncMock,
            return_value=_make_note(note_id=note_id, title="Updated note"),
        ):
            response = await client.patch(
                f"/api/notes/{note_id}",
                json={"title": "Updated note"},
            )

        assert response.status_code == 200
        assert response.json()["title"] == "Updated note"
        mock_session.refresh.assert_awaited()

    async def test_delete_note_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        note_id = uuid.uuid4()
        note = _make_note(note_id=note_id)
        note.soft_delete = MagicMock()

        with patch(
            "src.app.api.routes.notes.repo_get_note_by_id",
            new_callable=AsyncMock,
            return_value=note,
        ):
            response = await client.delete(f"/api/notes/{note_id}")

        assert response.status_code == 204
        note.soft_delete.assert_called_once()

    async def test_get_linked_notes_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        note_id = uuid.uuid4()
        linked_rows = [
            {
                "id": uuid.uuid4(),
                "title": "Linked note",
                "content": "Connected thought",
                "note_type": "permanent",
                "para_category": "resource",
                "tags": ["zettel"],
                "created_at": datetime(2026, 3, 15, 10, 0, tzinfo=UTC),
                "link_reason": "shared entity",
                "similarity_score": 0.8,
            }
        ]

        with (
            patch(
                "src.app.api.routes.notes.repo_get_note_by_id",
                new_callable=AsyncMock,
                return_value=_make_note(note_id=note_id),
            ),
            patch(
                "src.app.api.routes.notes.repo_get_linked_notes",
                new_callable=AsyncMock,
                return_value=linked_rows,
            ),
        ):
            response = await client.get(f"/api/notes/{note_id}/links")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Linked note"
        assert data[0]["link_reason"] == "shared entity"

    async def test_create_note_link_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        note_id = uuid.uuid4()
        target_id = uuid.uuid4()

        with (
            patch(
                "src.app.api.routes.notes.repo_get_note_by_id",
                new_callable=AsyncMock,
                side_effect=[
                    _make_note(note_id=note_id),
                    _make_note(note_id=target_id, title="Target note"),
                ],
            ),
            patch(
                "src.app.api.routes.notes.repo_create_note_link",
                new_callable=AsyncMock,
            ) as create_link,
        ):
            response = await client.post(
                f"/api/notes/{note_id}/links",
                json={"target_note_id": str(target_id), "link_reason": "shared entity"},
            )

        assert response.status_code == 201
        assert response.json() == {"status": "created"}
        create_link.assert_awaited_once()

    async def test_get_note_not_found_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        note_id = uuid.uuid4()

        with patch(
            "src.app.api.routes.notes.repo_get_note_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"/api/notes/{note_id}")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"
