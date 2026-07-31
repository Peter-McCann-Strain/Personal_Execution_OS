"""Email API routes — delegates to GmailService."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src.app.api.deps import get_current_principal
from src.app.config import get_settings

logger = structlog.get_logger()

router = APIRouter(
    prefix="/email",
    tags=["email"],
    dependencies=[Depends(get_current_principal)],
)

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class EmailDTO(BaseModel):
    """Email returned to the frontend."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    thread_id: str | None = Field(None, alias="threadId")
    snippet: str = ""
    headers: dict[str, str] = {}
    body: str | None = None
    label_ids: list[str] = Field(default_factory=list, alias="labelIds")
    internal_date: str | None = Field(None, alias="internalDate")
    triage: str | None = None


class PaginatedResponse(BaseModel):
    items: list[EmailDTO]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_google_configured() -> None:
    """Raise 503 using route-local settings resolution.

    Tests patch ``src.app.api.routes.email.get_settings`` directly, so this
    wrapper must resolve configuration from the route module rather than the
    shared utility module.
    """
    settings = get_settings()
    if not settings.google_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "Google is not configured. "
                "Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REFRESH_TOKEN."
            ),
        )


def _make_gmail_service():
    """Create a GmailService from current settings."""
    from src.app.agents.tools.email import GmailService

    settings = get_settings()
    return GmailService(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        refresh_token=settings.google_refresh_token.get_secret_value(),
    )


def _translate_gmail_error(exc: BaseException):
    """Convert raw Google failures into connector errors handled by middleware."""
    from src.app.agents.tools.google_auth import translate_google_error

    return translate_google_error(exc, connector="gmail")


def _raw_to_dto(raw: dict[str, Any]) -> EmailDTO:
    """Convert a raw Gmail API dict to an EmailDTO.

    Handles both metadata-format responses (from search_emails) and
    full-format responses (from get_email_detail).
    """
    # get_email_detail returns a clean dict with headers as a flat dict.
    # search_emails returns the raw Gmail API response with nested payload.headers.
    if "headers" in raw and isinstance(raw["headers"], dict):
        # Already processed by get_email_detail
        return EmailDTO(
            id=raw["id"],
            thread_id=raw.get("threadId"),
            snippet=raw.get("snippet", ""),
            headers=raw["headers"],
            body=raw.get("body"),
            label_ids=raw.get("labelIds", []),
            internal_date=raw.get("internalDate"),
        )

    # Raw Gmail API metadata format — extract headers from payload
    header_list = raw.get("payload", {}).get("headers", [])
    header_dict = {h["name"]: h["value"] for h in header_list}

    return EmailDTO(
        id=raw["id"],
        thread_id=raw.get("threadId"),
        snippet=raw.get("snippet", ""),
        headers=header_dict,
        label_ids=raw.get("labelIds", []),
        internal_date=raw.get("internalDate"),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/inbox", response_model=PaginatedResponse)
async def get_inbox(
    search: str | None = Query(None, description="Gmail search query"),
    triage: str | None = Query(None, description="Triage category filter"),
    unread_only: bool = Query(False, description="Only return unread emails"),
    limit: int = Query(25, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> PaginatedResponse:
    """Get paginated inbox emails with optional search and filters."""
    _check_google_configured()

    # Build Gmail search query from params
    query_parts: list[str] = []
    if search:
        query_parts.append(search)
    if unread_only:
        query_parts.append("is:unread")
    if triage:
        # Triage is a client-side concept — map to label if applicable
        query_parts.append(f"label:{triage}")

    gmail_query = " ".join(query_parts) if query_parts else "in:inbox"

    service = _make_gmail_service()
    try:
        # Fetch more than needed to handle offset pagination
        # Gmail API doesn't support offset natively, so we fetch limit+offset
        try:
            raw_emails = await service.search_emails(
                query=gmail_query,
                max_results=limit + offset,
            )
        except Exception as exc:
            raise _translate_gmail_error(exc) from exc
    finally:
        await service.close()

    total = len(raw_emails)
    # Apply offset pagination
    page = raw_emails[offset : offset + limit]

    items = [_raw_to_dto(e) for e in page]

    logger.info("email_inbox_returned", count=len(items), total=total)
    return PaginatedResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{message_id}", response_model=EmailDTO)
async def get_email(message_id: str) -> EmailDTO:
    """Get full detail for a single email."""
    _check_google_configured()

    service = _make_gmail_service()
    try:
        try:
            raw = await service.get_email_detail(message_id)
        except Exception as exc:
            raise _translate_gmail_error(exc) from exc
    finally:
        await service.close()

    logger.info("email_detail_returned", message_id=message_id)
    return _raw_to_dto(raw)
