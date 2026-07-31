"""Google Drive integration via the Drive REST API."""

from __future__ import annotations

from typing import Any

import structlog

from .google_auth import GoogleOAuthClient, google_http_retry

logger = structlog.get_logger()

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"

_EXPORT_MIME_TYPES: dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
}

_DIRECT_TEXT_MIME_TYPES = {
    "application/json",
    "application/ld+json",
    "application/rtf",
    "application/xml",
    "text/csv",
    "text/html",
    "text/markdown",
    "text/plain",
    "text/tab-separated-values",
}


class GoogleDriveService(GoogleOAuthClient):
    """Google Drive file listing and lightweight text extraction."""

    @google_http_retry
    async def list_files(
        self,
        *,
        query: str = "trashed = false",
        max_results: int = 25,
    ) -> list[dict[str, Any]]:
        """List recent Drive files with metadata suitable for sync/indexing."""
        token = await self._get_access_token()
        response = await self._http_client.get(
            f"{DRIVE_API_BASE}/files",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "q": query,
                "pageSize": max_results,
                "orderBy": "modifiedTime desc",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
                "fields": (
                    "files("
                    "id,"
                    "name,"
                    "mimeType,"
                    "description,"
                    "webViewLink,"
                    "modifiedTime,"
                    "createdTime,"
                    "fileExtension,"
                    "size,"
                    "iconLink,"
                    "owners(displayName,emailAddress)"
                    ")"
                ),
            },
        )
        response.raise_for_status()
        files = response.json().get("files", [])
        logger.info("google_drive_files_listed", count=len(files))
        return files

    @google_http_retry
    async def get_text_content(self, file_id: str, mime_type: str) -> str | None:
        """Fetch best-effort text for Drive files when a text representation exists."""
        token = await self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        export_mime = _EXPORT_MIME_TYPES.get(mime_type)
        if export_mime is not None:
            response = await self._http_client.get(
                f"{DRIVE_API_BASE}/files/{file_id}/export",
                headers=headers,
                params={"mimeType": export_mime},
            )
            if response.status_code in {400, 403, 404}:
                return None
            response.raise_for_status()
            text = response.text.strip()
            return text or None

        if mime_type.startswith("text/") or mime_type in _DIRECT_TEXT_MIME_TYPES:
            response = await self._http_client.get(
                f"{DRIVE_API_BASE}/files/{file_id}",
                headers=headers,
                params={"alt": "media", "supportsAllDrives": "true"},
            )
            if response.status_code in {400, 403, 404}:
                return None
            response.raise_for_status()
            text = response.text.strip()
            return text or None

        return None
