"""Integration tests for email endpoints through the full FastAPI app."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


def _build_service(*, inbox: list[dict] | None = None, detail: dict | None = None) -> AsyncMock:
    service = AsyncMock()
    service.search_emails = AsyncMock(return_value=inbox or [])
    service.get_email_detail = AsyncMock(return_value=detail or {})
    service.close = AsyncMock()
    return service


def _build_gmail_email(
    *,
    message_id: str = "msg_001",
    thread_id: str = "thread_001",
    snippet: str = "Hello from the inbox.",
) -> dict:
    return {
        "id": message_id,
        "threadId": thread_id,
        "snippet": snippet,
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Test Subject"},
                {"name": "From", "value": "alice@example.com"},
            ]
        },
        "labelIds": ["INBOX", "UNREAD"],
        "internalDate": "1710600000000",
    }


class TestEmailContracts:
    """Verify email response contracts through the real app router."""

    async def test_get_inbox_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        mock_service = _build_service(
            inbox=[
                _build_gmail_email(message_id="msg_a"),
                _build_gmail_email(message_id="msg_b", snippet="Second message."),
            ]
        )

        with (
            patch("src.app.api.routes.email._check_google_configured"),
            patch("src.app.api.routes.email._make_gmail_service", return_value=mock_service),
        ):
            response = await client.get("/api/email/inbox", params={"limit": 2, "offset": 0})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["limit"] == 2
        assert data["offset"] == 0
        assert len(data["items"]) == 2
        assert data["items"][0]["id"] == "msg_a"
        assert data["items"][0]["headers"]["Subject"] == "Test Subject"
        mock_service.search_emails.assert_awaited_once_with(query="in:inbox", max_results=2)
        mock_service.close.assert_awaited_once()

    async def test_get_inbox_supports_combined_query_filters_and_offset(
        self,
        integration_client,
    ):
        client, _mock_session, _mock_anthropic = integration_client
        mock_service = _build_service(
            inbox=[
                _build_gmail_email(message_id="msg_0"),
                _build_gmail_email(message_id="msg_1"),
                _build_gmail_email(message_id="msg_2"),
            ]
        )

        with (
            patch("src.app.api.routes.email._check_google_configured"),
            patch("src.app.api.routes.email._make_gmail_service", return_value=mock_service),
        ):
            response = await client.get(
                "/api/email/inbox",
                params={
                    "search": "project update",
                    "triage": "important",
                    "unread_only": True,
                    "limit": 1,
                    "offset": 1,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["limit"] == 1
        assert data["offset"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "msg_1"
        mock_service.search_emails.assert_awaited_once_with(
            query="project update is:unread label:important",
            max_results=2,
        )
        mock_service.close.assert_awaited_once()

    async def test_get_email_contract(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        mock_service = _build_service(
            detail={
                "id": "msg_detail",
                "threadId": "thread_detail",
                "snippet": "A detailed message.",
                "headers": {"Subject": "Detail Subject", "From": "bob@example.com"},
                "body": "Full body text here.",
                "labelIds": ["INBOX"],
                "internalDate": "1710600000000",
            }
        )

        with (
            patch("src.app.api.routes.email._check_google_configured"),
            patch("src.app.api.routes.email._make_gmail_service", return_value=mock_service),
        ):
            response = await client.get("/api/email/msg_detail")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "msg_detail"
        assert data["body"] == "Full body text here."
        assert data["headers"]["Subject"] == "Detail Subject"
        mock_service.get_email_detail.assert_awaited_once_with("msg_detail")
        mock_service.close.assert_awaited_once()

    async def test_email_write_routes_are_not_exposed(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client

        responses = [
            await client.post("/api/email/send", json={}),
            await client.post("/api/email/drafts", json={}),
            await client.post("/api/email/msg_123/read"),
        ]

        assert all(response.status_code in {404, 405} for response in responses)

    async def test_email_routes_return_503_when_google_is_not_configured(self, integration_client):
        client, _mock_session, _mock_anthropic = integration_client
        mock_settings = MagicMock()
        mock_settings.google_configured = False

        with patch("src.app.api.routes.email.get_settings", return_value=mock_settings):
            response = await client.get("/api/email/inbox")

        assert response.status_code == 503
