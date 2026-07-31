"""Gmail integration via Google API.

Requires Google OAuth2 credentials in env. No fallback.
"""

import base64
from email.mime.text import MIMEText
from typing import Any

import structlog

from src.app.core.exceptions import AppError

from .google_auth import GoogleOAuthClient, google_http_retry

logger = structlog.get_logger()

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class EmailError(AppError):
    """Email operation failed."""


class GmailService(GoogleOAuthClient):
    """Gmail operations via Google API.

    Uses a shared httpx.AsyncClient for connection reuse and manages
    OAuth2 access token caching with automatic refresh.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        allowed_domains: list[str] | None = None,
    ) -> None:
        super().__init__(client_id, client_secret, refresh_token)
        self.allowed_domains = allowed_domains

    @google_http_retry
    async def get_unread_emails(self, max_results: int = 10) -> list[dict[str, Any]]:
        """Get unread emails from inbox with metadata."""
        token = await self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await self._http_client.get(
            f"{GMAIL_API_BASE}/messages",
            headers=headers,
            params={"q": "is:unread", "maxResults": max_results},
        )
        response.raise_for_status()
        message_list = response.json().get("messages", [])

        emails = []
        for msg in message_list:
            detail = await self._http_client.get(
                f"{GMAIL_API_BASE}/messages/{msg['id']}",
                headers=headers,
                params={"format": "metadata"},
            )
            detail.raise_for_status()
            emails.append(detail.json())

        logger.info("emails_fetched", count=len(emails))
        return emails

    @google_http_retry
    async def search_emails(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Search emails using Gmail search syntax.

        Supports Gmail query operators like:
          'from:john subject:meeting'
          'after:2026/01/01 has:attachment'
          'in:sent to:alice'
        """
        token = await self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await self._http_client.get(
            f"{GMAIL_API_BASE}/messages",
            headers=headers,
            params={"q": query, "maxResults": max_results},
        )
        response.raise_for_status()
        message_list = response.json().get("messages", [])

        emails = []
        for msg in message_list:
            detail = await self._http_client.get(
                f"{GMAIL_API_BASE}/messages/{msg['id']}",
                headers=headers,
                params={"format": "metadata"},
            )
            detail.raise_for_status()
            emails.append(detail.json())

        logger.info("emails_searched", query_length=len(query), count=len(emails))
        return emails

    @google_http_retry
    async def get_email_detail(self, message_id: str) -> dict[str, Any]:
        """Get full email detail including body text.

        Returns a dict with id, threadId, snippet, headers (as dict),
        and body (decoded plain text).
        """
        token = await self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await self._http_client.get(
            f"{GMAIL_API_BASE}/messages/{message_id}",
            headers=headers,
            params={"format": "full"},
        )
        response.raise_for_status()
        data = response.json()

        # Extract headers into a flat dict for easy access
        header_list = data.get("payload", {}).get("headers", [])
        header_dict = {h["name"]: h["value"] for h in header_list}

        # Extract body text — handle single-part and multipart messages
        body_text = _extract_body_text(data.get("payload", {}))

        result: dict[str, Any] = {
            "id": data["id"],
            "threadId": data.get("threadId"),
            "snippet": data.get("snippet", ""),
            "headers": header_dict,
            "body": body_text,
            "labelIds": data.get("labelIds", []),
            "internalDate": data.get("internalDate"),
        }

        logger.info("email_detail_fetched", message_id=message_id)
        return result

    @google_http_retry
    async def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to_message_id: str | None = None,
    ) -> str:
        """Create a draft email. Returns the draft ID.

        If reply_to_message_id is provided, the draft will be created as a reply
        to that message (preserving the thread).
        """
        self._validate_recipient(to)
        token = await self._get_access_token()

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject

        # For replies, set In-Reply-To and References headers
        thread_id: str | None = None
        if reply_to_message_id is not None:
            original = await self.get_email_detail(reply_to_message_id)
            original_msg_id_header = original["headers"].get("Message-ID", "")
            if original_msg_id_header:
                message["In-Reply-To"] = original_msg_id_header
                message["References"] = original_msg_id_header
            thread_id = original.get("threadId")

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        draft_body: dict[str, Any] = {"message": {"raw": raw}}
        if thread_id is not None:
            draft_body["message"]["threadId"] = thread_id

        response = await self._http_client.post(
            f"{GMAIL_API_BASE}/drafts",
            headers={"Authorization": f"Bearer {token}"},
            json=draft_body,
        )
        response.raise_for_status()
        draft_id = response.json()["id"]

        logger.info(
            "email_draft_created",
            draft_id=draft_id,
            recipient_count=1,
            subject_length=len(subject),
        )
        return draft_id

    @google_http_retry
    async def get_thread(self, thread_id: str) -> list[dict[str, Any]]:
        """Get all messages in an email thread, ordered chronologically.

        Each message includes id, snippet, headers (as dict), and body text.
        """
        token = await self._get_access_token()

        response = await self._http_client.get(
            f"{GMAIL_API_BASE}/threads/{thread_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"format": "full"},
        )
        response.raise_for_status()
        data = response.json()

        messages = []
        for msg in data.get("messages", []):
            header_list = msg.get("payload", {}).get("headers", [])
            header_dict = {h["name"]: h["value"] for h in header_list}
            body_text = _extract_body_text(msg.get("payload", {}))

            messages.append(
                {
                    "id": msg["id"],
                    "snippet": msg.get("snippet", ""),
                    "headers": header_dict,
                    "body": body_text,
                    "labelIds": msg.get("labelIds", []),
                    "internalDate": msg.get("internalDate"),
                }
            )

        logger.info("email_thread_fetched", thread_id=thread_id, message_count=len(messages))
        return messages

    @google_http_retry
    async def mark_as_read(self, message_id: str) -> None:
        """Mark an email as read by removing the UNREAD label."""
        token = await self._get_access_token()

        response = await self._http_client.post(
            f"{GMAIL_API_BASE}/messages/{message_id}/modify",
            headers={"Authorization": f"Bearer {token}"},
            json={"removeLabelIds": ["UNREAD"]},
        )
        response.raise_for_status()

        logger.info("email_marked_read", message_id=message_id)

    @google_http_retry
    async def add_label(self, message_id: str, label: str) -> None:
        """Add a label to an email.

        The label must be specified by its Gmail label ID. For user-created labels,
        use the label ID (not the display name). Standard labels use their name
        as the ID (e.g., 'IMPORTANT', 'STARRED').
        """
        token = await self._get_access_token()

        response = await self._http_client.post(
            f"{GMAIL_API_BASE}/messages/{message_id}/modify",
            headers={"Authorization": f"Bearer {token}"},
            json={"addLabelIds": [label]},
        )
        response.raise_for_status()

        logger.info("email_label_added", message_id=message_id, label=label)

    def _validate_recipient(self, to: str) -> None:
        """Validate recipient domain against allowed list."""
        if self.allowed_domains is None:
            return
        parts = to.strip().split("@")
        if len(parts) != 2:
            raise EmailError(f"Invalid email address: {to}")
        domain = parts[1].lower()
        allowed = [d.lower() for d in self.allowed_domains]
        if domain not in allowed:
            raise EmailError(f"Recipient domain '{domain}' not in allowed domains: {allowed}")

    @google_http_retry
    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
    ) -> str:
        """Send an email. Returns message ID."""
        self._validate_recipient(to)
        token = await self._get_access_token()

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        response = await self._http_client.post(
            f"{GMAIL_API_BASE}/messages/send",
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": raw},
        )
        response.raise_for_status()
        msg_id = response.json()["id"]

        logger.info(
            "email_sent",
            message_id=msg_id,
            recipient_count=1,
            subject_length=len(subject),
        )
        return msg_id


def _extract_body_text(payload: dict[str, Any]) -> str:
    """Extract plain text body from a Gmail message payload.

    Handles both single-part messages and multipart messages (including
    nested multipart structures). Prefers text/plain over text/html.
    """
    # Single-part message
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if mime_type == "text/plain" and body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

    # Multipart — recurse into parts, prefer text/plain
    parts = payload.get("parts", [])
    plain_text = ""
    html_text = ""

    for part in parts:
        part_mime = part.get("mimeType", "")
        part_data = part.get("body", {}).get("data")

        if part_mime == "text/plain" and part_data:
            plain_text = base64.urlsafe_b64decode(part_data).decode("utf-8", errors="replace")
        elif part_mime == "text/html" and part_data:
            html_text = base64.urlsafe_b64decode(part_data).decode("utf-8", errors="replace")
        elif part_mime.startswith("multipart/"):
            # Nested multipart — recurse
            nested = _extract_body_text(part)
            if nested:
                plain_text = plain_text or nested

    return plain_text or html_text
