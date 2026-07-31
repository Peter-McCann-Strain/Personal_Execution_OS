"""Tests for the notes API routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import get_db
from src.app.api.routes.notes import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from tests.unit.api.auth_helpers import override_current_principal


def _make_mock_note(
    *,
    note_id: uuid.UUID | None = None,
    title: str = "Atomic note",
    content: str = "A durable note about testing.",
) -> MagicMock:
    now = datetime.now(UTC)
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


def _make_mock_canvas(
    *, canvas_id: uuid.UUID | None = None, primary_note_id: uuid.UUID | None = None
) -> MagicMock:
    now = datetime.now(UTC)
    canvas = MagicMock()
    canvas.id = canvas_id or uuid.uuid4()
    canvas.title = "Research canvas"
    canvas.description = "Connected work"
    canvas.primary_note_id = primary_note_id
    canvas.nodes = [{"id": "note-1", "type": "note"}]
    canvas.edges = [{"id": "edge-1", "source": "note-1", "target": "note-2"}]
    canvas.viewport = {"x": 0, "y": 0, "zoom": 1}
    canvas.created_at = now
    canvas.updated_at = now
    return canvas


def _build_app(mock_session: AsyncMock) -> FastAPI:
    app = FastAPI()

    async def _mock_db():
        yield mock_session

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.dependency_overrides[get_db] = _mock_db
    override_current_principal(app)
    app.include_router(router, prefix="/api")
    return app


async def test_search_notes_success():
    mock_session = AsyncMock()
    rows = [
        {
            "id": uuid.uuid4(),
            "title": "Atomic note",
            "content": "A durable note about testing.",
            "note_type": "literature",
            "para_category": "resource",
            "tags": ["testing"],
            "created_at": datetime.now(UTC),
        }
    ]

    with patch(
        "src.app.api.routes.notes.repo_search_notes",
        new_callable=AsyncMock,
        return_value=rows,
    ):
        app = _build_app(mock_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/notes/search", params={"q": "testing"})

    assert response.status_code == 200
    data = response.json()
    assert data[0]["title"] == "Atomic note"
    assert data[0]["tags"] == ["testing"]


async def test_list_notes_success():
    mock_session = AsyncMock()
    mock_note = _make_mock_note()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_list_notes",
        new_callable=AsyncMock,
        return_value=([mock_note], 1),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/notes", params={"kind": "moc"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["title"] == "Atomic note"


async def test_get_note_graph_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    graph_payload = {
        "nodes": [
            {
                "id": str(uuid.uuid4()),
                "title": "Source note",
                "slug": "source-note",
                "kind": "permanent",
                "note_type": "literature",
                "para_category": "resource",
                "tags": ["graph"],
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ],
        "edges": [
            {
                "id": str(uuid.uuid4()),
                "source": "source",
                "target": "target",
                "link_type": "wiki",
                "origin": "wiki",
                "similarity_score": None,
                "link_reason": "explicit link",
            }
        ],
    }

    with patch(
        "src.app.api.routes.notes.repo_get_note_graph",
        new_callable=AsyncMock,
        return_value=graph_payload,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/notes/graph", params={"depth": 2})

    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 1
    assert data["edges"][0]["link_type"] == "wiki"


async def test_create_note_success():
    mock_session = AsyncMock()
    mock_note = _make_mock_note()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_create_note",
        new_callable=AsyncMock,
        return_value=mock_note,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/notes",
                json={"title": "Atomic note", "content": "A durable note about testing."},
            )

    assert response.status_code == 201
    assert response.json()["title"] == "Atomic note"


async def test_get_note_success():
    note_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_note = _make_mock_note(note_id=note_id)
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_get_note_by_id",
        new_callable=AsyncMock,
        return_value=mock_note,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/notes/{note_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(note_id)


async def test_get_note_not_found():
    note_id = uuid.uuid4()
    mock_session = AsyncMock()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_get_note_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/notes/{note_id}")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_update_note_success():
    note_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_note = _make_mock_note(note_id=note_id, title="Updated note")
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_update_note",
        new_callable=AsyncMock,
        return_value=mock_note,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/notes/{note_id}",
                json={"title": "Updated note"},
            )

    assert response.status_code == 200
    assert response.json()["title"] == "Updated note"


async def test_update_note_not_found():
    note_id = uuid.uuid4()
    mock_session = AsyncMock()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_update_note",
        new_callable=AsyncMock,
        side_effect=ValueError("Note not found"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/notes/{note_id}",
                json={"title": "Updated note"},
            )

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_delete_note_not_found():
    note_id = uuid.uuid4()
    mock_session = AsyncMock()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_get_note_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/notes/{note_id}")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_delete_note_success():
    note_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_note = _make_mock_note(note_id=note_id)
    mock_note.soft_delete = MagicMock()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_get_note_by_id",
        new_callable=AsyncMock,
        return_value=mock_note,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/notes/{note_id}")

    assert response.status_code == 204
    mock_note.soft_delete.assert_called_once()


async def test_get_linked_notes_success():
    note_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_note = _make_mock_note(note_id=note_id)
    linked_rows = [
        {
            "id": uuid.uuid4(),
            "title": "Linked note",
            "content": "Connected thought",
            "note_type": "permanent",
            "para_category": "resource",
            "tags": ["zettel"],
            "created_at": datetime.now(UTC),
            "link_reason": "shared entity",
            "similarity_score": 0.8,
        }
    ]
    app = _build_app(mock_session)

    with (
        patch(
            "src.app.api.routes.notes.repo_get_note_by_id",
            new_callable=AsyncMock,
            return_value=mock_note,
        ),
        patch(
            "src.app.api.routes.notes.repo_get_linked_notes",
            new_callable=AsyncMock,
            return_value=linked_rows,
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/notes/{note_id}/links")

    assert response.status_code == 200
    data = response.json()
    assert data[0]["title"] == "Linked note"
    assert data[0]["link_reason"] == "shared entity"


async def test_get_backlinked_notes_success():
    note_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_note = _make_mock_note(note_id=note_id)
    backlink_rows = [
        {
            "id": uuid.uuid4(),
            "title": "Backlink note",
            "content": "Points back here",
            "note_type": "permanent",
            "para_category": "resource",
            "tags": ["zettel"],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "link_reason": "references source",
            "similarity_score": 0.9,
            "link_type": "manual",
            "origin": "manual",
        }
    ]
    app = _build_app(mock_session)

    with (
        patch(
            "src.app.api.routes.notes.repo_get_note_by_id",
            new_callable=AsyncMock,
            return_value=mock_note,
        ),
        patch(
            "src.app.api.routes.notes.repo_get_backlinked_notes",
            new_callable=AsyncMock,
            return_value=backlink_rows,
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/notes/{note_id}/backlinks")

    assert response.status_code == 200
    data = response.json()
    assert data[0]["title"] == "Backlink note"
    assert data[0]["origin"] == "manual"


async def test_get_unlinked_mentions_success():
    note_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_note = _make_mock_note(note_id=note_id)
    mention_rows = [
        {
            "id": uuid.uuid4(),
            "title": "Mentioning note",
            "slug": "mentioning-note",
            "kind": "permanent",
            "content": "References the source note in passing.",
            "note_type": "permanent",
            "para_category": "resource",
            "tags": ["mentions"],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "link_reason": "Mentions Atomic note",
            "similarity_score": None,
            "link_type": None,
            "origin": "unlinked_mention",
        }
    ]
    app = _build_app(mock_session)

    with (
        patch(
            "src.app.api.routes.notes.repo_get_note_by_id",
            new_callable=AsyncMock,
            return_value=mock_note,
        ),
        patch(
            "src.app.api.routes.notes.repo_get_unlinked_mentions",
            new_callable=AsyncMock,
            return_value=mention_rows,
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/notes/{note_id}/unlinked-mentions")

    assert response.status_code == 200
    data = response.json()
    assert data[0]["title"] == "Mentioning note"
    assert data[0]["origin"] == "unlinked_mention"


async def test_upsert_daily_note_success():
    mock_session = AsyncMock()
    mock_note = _make_mock_note(title="Daily Note 2026-04-13")
    mock_note.kind = "daily"
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_upsert_daily_note",
        new_callable=AsyncMock,
        return_value=mock_note,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/notes/daily/2026-04-13",
                json={"content": "Daily summary", "tags": ["daily"]},
            )

    assert response.status_code == 201
    assert response.json()["title"] == "Daily Note 2026-04-13"


async def test_list_note_canvases_success():
    mock_session = AsyncMock()
    mock_canvas = _make_mock_canvas()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_list_note_canvases",
        new_callable=AsyncMock,
        return_value=([mock_canvas], 1),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/note-canvases")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Research canvas"


async def test_get_linked_notes_not_found():
    note_id = uuid.uuid4()
    mock_session = AsyncMock()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_get_note_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/notes/{note_id}/links")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_create_note_link_success():
    note_id = uuid.uuid4()
    target_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_note = _make_mock_note(note_id=note_id)
    target_note = _make_mock_note(note_id=target_id, title="Target note")
    app = _build_app(mock_session)

    with (
        patch(
            "src.app.api.routes.notes.repo_get_note_by_id",
            new_callable=AsyncMock,
            side_effect=[mock_note, target_note],
        ),
        patch(
            "src.app.api.routes.notes.repo_create_note_link",
            new_callable=AsyncMock,
        ) as mock_create_link,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/notes/{note_id}/links",
                json={"target_note_id": str(target_id), "link_reason": "shared entity"},
            )

    assert response.status_code == 201
    assert response.json() == {"status": "created"}
    mock_create_link.assert_awaited_once()


async def test_create_note_link_source_not_found():
    note_id = uuid.uuid4()
    target_id = uuid.uuid4()
    mock_session = AsyncMock()
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_get_note_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/notes/{note_id}/links",
                json={"target_note_id": str(target_id), "link_reason": "shared entity"},
            )

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_create_note_link_target_not_found():
    note_id = uuid.uuid4()
    target_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_note = _make_mock_note(note_id=note_id)
    app = _build_app(mock_session)

    with patch(
        "src.app.api.routes.notes.repo_get_note_by_id",
        new_callable=AsyncMock,
        side_effect=[mock_note, None],
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/notes/{note_id}/links",
                json={"target_note_id": str(target_id), "link_reason": "shared entity"},
            )

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
