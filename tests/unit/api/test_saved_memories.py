"""Tests for saved-memory control-center API routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.app.api.deps import Principal, get_current_principal, get_db
from src.app.api.routes.saved_memories import router
from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, ErrorResponse
from src.app.persistence.models import AuditEvent


def _make_memory(*, memory_id: uuid.UUID | None = None, pinned: bool = False) -> MagicMock:
    now = datetime.now(UTC)
    memory = MagicMock()
    memory.id = memory_id or uuid.uuid4()
    memory.user_id = "owner"
    memory.title = "Preferred writing tone"
    memory.content = "Direct, concise, and analytical."
    memory.scope = "global"
    memory.scope_key = None
    memory.state = "active"
    memory.source_type = "manual"
    memory.source_id = None
    memory.provenance = {"created_via": "control_center"}
    memory.pinned = pinned
    memory.auto_captured = False
    memory.last_used_at = now
    memory.last_confirmed_at = now if pinned else None
    memory.created_at = now
    memory.updated_at = now
    return memory


def _build_app(mock_session: AsyncMock) -> FastAPI:
    app = FastAPI()

    async def _mock_db():
        yield mock_session

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

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, error_code = EXCEPTION_STATUS_MAP.get(type(exc), (500, "app_error"))
        body = ErrorResponse(error=error_code, message=str(exc))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    app.dependency_overrides[get_db] = _mock_db
    app.dependency_overrides[get_current_principal] = _always_principal
    app.include_router(router, prefix="/api")
    return app


async def test_list_saved_memories_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    memory = _make_memory()

    with patch(
        "src.app.api.routes.saved_memories.repo_list_saved_memories",
        new_callable=AsyncMock,
        return_value=([memory], 1),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/saved-memories", params={"scope": "global"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["title"] == "Preferred writing tone"


async def test_create_saved_memory_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    memory = _make_memory(pinned=True)

    with patch(
        "src.app.api.routes.saved_memories.repo_create_saved_memory",
        new_callable=AsyncMock,
        return_value=memory,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/saved-memories",
                json={
                    "title": "Preferred writing tone",
                    "content": "Direct, concise, and analytical.",
                    "pinned": True,
                },
            )

    assert response.status_code == 201
    assert response.json()["pinned"] is True
    added_rows = [call.args[0] for call in mock_session.add.await_args_list]
    audit_event = next(row for row in added_rows if isinstance(row, AuditEvent))
    assert audit_event.event_type == "saved_memory.created"
    assert audit_event.resource_id == str(memory.id)


async def test_merge_saved_memories_success():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    target = _make_memory()
    source = _make_memory()

    with patch(
        "src.app.api.routes.saved_memories.repo_merge_saved_memories",
        new_callable=AsyncMock,
        return_value=target,
    ) as merge_repo:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/saved-memories/merge",
                json={
                    "target_memory_id": str(target.id),
                    "source_memory_ids": [str(source.id)],
                },
            )

    assert response.status_code == 200
    assert response.json()["id"] == str(target.id)
    merge_repo.assert_awaited_once()
    added_rows = [call.args[0] for call in mock_session.add.await_args_list]
    audit_event = next(row for row in added_rows if isinstance(row, AuditEvent))
    assert audit_event.event_type == "saved_memory.merged"
    assert audit_event.resource_id == str(target.id)


async def test_update_saved_memory_not_found():
    mock_session = AsyncMock()
    app = _build_app(mock_session)
    memory_id = uuid.uuid4()

    with patch(
        "src.app.api.routes.saved_memories.repo_update_saved_memory",
        new_callable=AsyncMock,
        return_value=None,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/saved-memories/{memory_id}",
                json={"confirm_now": True},
            )

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
