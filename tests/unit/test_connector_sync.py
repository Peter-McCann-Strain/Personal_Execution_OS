"""Tests for persisted connector sync routines."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.domain.services.connector_sync import sync_connector_account


@pytest.mark.asyncio
async def test_sync_connector_account_google_drive_indexes_files():
    """Google Drive sync should normalize documents instead of raising NotImplementedError."""
    session = AsyncMock()
    account = MagicMock()
    account.id = uuid.uuid4()
    account.connector_type = "google_drive"

    mock_service = AsyncMock()
    mock_service.list_files = AsyncMock(
        return_value=[
            {
                "id": "doc-1",
                "name": "Launch brief",
                "mimeType": "application/vnd.google-apps.document",
                "description": "Draft launch brief",
                "webViewLink": "https://example.com/doc-1",
                "owners": [{"displayName": "Alex", "emailAddress": "alex@example.com"}],
            },
            {
                "id": "sheet-1",
                "name": "Roadmap",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "webViewLink": "https://example.com/sheet-1",
                "owners": [],
            },
            {
                "id": "folder-1",
                "name": "Ignored folder",
                "mimeType": "application/vnd.google-apps.folder",
            },
        ]
    )
    mock_service.get_text_content = AsyncMock(
        side_effect=["Launch narrative and milestones", "M1,Done\nM2,In progress"]
    )
    mock_service.close = AsyncMock()

    with (
        patch(
            "src.app.domain.services.connector_sync._make_drive_service",
            return_value=mock_service,
        ),
        patch(
            "src.app.domain.services.connector_sync.upsert_connector_document",
            new_callable=AsyncMock,
        ) as mock_upsert,
    ):
        count = await sync_connector_account(session, account=account, max_items=10)

    assert count == 2
    assert mock_upsert.await_count == 2
    first_call = mock_upsert.await_args_list[0]
    second_call = mock_upsert.await_args_list[1]
    assert first_call.kwargs["source_type"] == "google_doc"
    assert "Launch narrative and milestones" in first_call.kwargs["content"]
    assert second_call.kwargs["source_type"] == "google_sheet"
    assert second_call.kwargs["source_url"] == "https://example.com/sheet-1"
    mock_service.close.assert_awaited_once()
    session.flush.assert_awaited()
