"""Connector sync routines backed by the existing Google service clients."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from src.app.agents.tools.calendar import CalendarService
from src.app.agents.tools.email import GmailService
from src.app.agents.tools.google_drive import GoogleDriveService
from src.app.config import get_settings
from src.app.core.secret_box import decrypt_secret
from src.app.persistence.models import ConnectorAccount
from src.app.persistence.repositories.connectors import upsert_connector_document


def _connector_refresh_token(account: ConnectorAccount) -> str:
    settings = get_settings()
    if account.encrypted_refresh_token:
        return decrypt_secret(
            account.encrypted_refresh_token,
            key=settings.connector_token_encryption_key,
        )
    return settings.google_refresh_token.get_secret_value()


def _make_gmail_service(account: ConnectorAccount) -> GmailService:
    settings = get_settings()
    return GmailService(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        refresh_token=_connector_refresh_token(account),
    )


def _make_calendar_service(account: ConnectorAccount) -> CalendarService:
    settings = get_settings()
    return CalendarService(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        refresh_token=_connector_refresh_token(account),
    )


def _make_drive_service(account: ConnectorAccount) -> GoogleDriveService:
    settings = get_settings()
    return GoogleDriveService(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        refresh_token=_connector_refresh_token(account),
    )


def _gmail_headers(raw_message: dict[str, Any]) -> dict[str, str]:
    header_list = raw_message.get("payload", {}).get("headers", [])
    return {
        str(header.get("name", "")): str(header.get("value", ""))
        for header in header_list
        if isinstance(header, dict)
    }


def _gmail_document_payload(
    raw_message: dict[str, Any],
) -> tuple[str, str, str | None, dict[str, Any]]:
    headers = _gmail_headers(raw_message)
    subject = headers.get("Subject") or raw_message.get("snippet") or "Untitled email"
    sender = headers.get("From", "")
    snippet = str(raw_message.get("snippet", "") or "")
    body = "\n".join(part for part in [subject, sender, snippet] if part)
    source_url = None
    metadata = {
        "thread_id": raw_message.get("threadId"),
        "label_ids": raw_message.get("labelIds", []),
        "internal_date": raw_message.get("internalDate"),
        "headers": headers,
    }
    return subject, body or subject, source_url, metadata


def _calendar_document_payload(event: Any) -> tuple[str, str, str | None, dict[str, Any]]:
    summary = str(getattr(event, "summary", "") or "Untitled event")
    description = str(getattr(event, "description", "") or "")
    location = str(getattr(event, "location", "") or "")
    attendees = [str(email) for email in getattr(event, "attendees", [])]
    start = getattr(event, "start", None)
    end = getattr(event, "end", None)
    content_parts = [
        summary,
        description,
        location,
        f"Attendees: {', '.join(attendees)}" if attendees else "",
    ]
    start_isoformat = getattr(start, "isoformat", None)
    end_isoformat = getattr(end, "isoformat", None)
    metadata = {
        "start": start_isoformat() if callable(start_isoformat) else None,
        "end": end_isoformat() if callable(end_isoformat) else None,
        "location": location or None,
        "attendees": attendees,
    }
    return summary, "\n".join(part for part in content_parts if part), None, metadata


def _drive_source_type(mime_type: str) -> str:
    if mime_type == "application/vnd.google-apps.document":
        return "google_doc"
    if mime_type == "application/vnd.google-apps.spreadsheet":
        return "google_sheet"
    if mime_type == "application/vnd.google-apps.presentation":
        return "google_slide"
    return "drive_file"


def _drive_document_payload(
    file_record: dict[str, Any],
    *,
    text_content: str | None,
) -> tuple[str, str, str | None, dict[str, Any]]:
    title = str(file_record.get("name", "") or "Untitled file")
    mime_type = str(file_record.get("mimeType", "") or "")
    description = str(file_record.get("description", "") or "")
    owners = [
        {
            "display_name": str(owner.get("displayName", "") or ""),
            "email": str(owner.get("emailAddress", "") or ""),
        }
        for owner in file_record.get("owners", [])
        if isinstance(owner, dict)
    ]
    owner_summary = ", ".join(
        owner["display_name"] or owner["email"]
        for owner in owners
        if owner["display_name"] or owner["email"]
    )
    content_parts = [
        title,
        description,
        f"Owners: {owner_summary}" if owner_summary else "",
        (text_content or "").strip(),
    ]
    metadata = {
        "mime_type": mime_type,
        "description": description or None,
        "web_view_link": file_record.get("webViewLink"),
        "modified_time": file_record.get("modifiedTime"),
        "created_time": file_record.get("createdTime"),
        "file_extension": file_record.get("fileExtension"),
        "size": file_record.get("size"),
        "icon_link": file_record.get("iconLink"),
        "owners": owners,
        "source_type": _drive_source_type(mime_type),
    }
    return (
        title,
        "\n".join(part for part in content_parts if part),
        str(file_record.get("webViewLink", "") or "") or None,
        metadata,
    )


async def sync_connector_account(
    session,
    *,
    account: ConnectorAccount,
    max_items: int = 25,
) -> int:
    """Fetch and persist normalized documents for one connector account."""
    created_or_updated = 0

    if account.connector_type == "gmail":
        service = _make_gmail_service(account)
        try:
            raw_messages = await service.search_emails("newer_than:30d", max_results=max_items)
        finally:
            await service.close()
        for raw_message in raw_messages:
            external_id = str(raw_message.get("id", "") or "")
            if not external_id:
                continue
            title, content, source_url, metadata = _gmail_document_payload(raw_message)
            await upsert_connector_document(
                session,
                account_id=account.id,
                external_id=external_id,
                source_type="gmail_message",
                title=title,
                content=content,
                source_url=source_url,
                metadata=metadata,
            )
            created_or_updated += 1
    elif account.connector_type == "google_calendar":
        service = _make_calendar_service(account)
        try:
            events = await service.list_events_between(
                datetime.now(UTC) - timedelta(days=14),
                datetime.now(UTC) + timedelta(days=45),
                max_results=max_items,
            )
        finally:
            await service.close()
        for event in events:
            external_id = str(getattr(event, "id", "") or "")
            if not external_id:
                continue
            title, content, source_url, metadata = _calendar_document_payload(event)
            await upsert_connector_document(
                session,
                account_id=account.id,
                external_id=external_id,
                source_type="calendar_event",
                title=title,
                content=content,
                source_url=source_url,
                metadata=metadata,
            )
            created_or_updated += 1
    elif account.connector_type == "google_drive":
        service = _make_drive_service(account)
        try:
            files = await service.list_files(max_results=max_items)
            for file_record in files:
                external_id = str(file_record.get("id", "") or "")
                mime_type = str(file_record.get("mimeType", "") or "")
                if not external_id or mime_type == "application/vnd.google-apps.folder":
                    continue
                text_content = await service.get_text_content(external_id, mime_type)
                title, content, source_url, metadata = _drive_document_payload(
                    file_record,
                    text_content=text_content,
                )
                await upsert_connector_document(
                    session,
                    account_id=account.id,
                    external_id=external_id,
                    source_type=_drive_source_type(mime_type),
                    title=title,
                    content=content,
                    source_url=source_url,
                    metadata=metadata,
                )
                created_or_updated += 1
        finally:
            await service.close()
    else:
        msg = f"Unsupported connector type: {account.connector_type}"
        raise ValueError(msg)

    account.last_sync_at = datetime.now(UTC)
    account.updated_at = datetime.now(UTC)
    await session.flush()
    return created_or_updated


def connector_default_display_name(connector_type: str) -> str:
    """Return a stable human label for a connector type."""
    labels = {
        "gmail": "Gmail",
        "google_calendar": "Google Calendar",
        "google_drive": "Google Drive",
    }
    return labels.get(connector_type, connector_type.replace("_", " ").title())


def connector_account_metadata(*, connected_via: str = "settings") -> dict[str, Any]:
    """Small helper for connector-account provenance."""
    return {
        "connected_via": connected_via,
        "connected_at": datetime.now(UTC).isoformat(),
        "account_ref": str(uuid.uuid4()),
    }
