"""Tests for GmailService — Gmail API integration."""

import base64
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.app.agents.tools.email import (
    EmailError,
    GmailService,
    _extract_body_text,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


@pytest.fixture
def gmail_service():
    from datetime import UTC, datetime, timedelta

    svc = GmailService(
        client_id="fake-id",
        client_secret="fake-secret",
        refresh_token="fake-refresh",
        allowed_domains=["example.com"],
    )
    svc._http_client = AsyncMock(spec=httpx.AsyncClient)
    svc._cached_token = "valid-token"
    svc._token_expiry = datetime.now(UTC) + timedelta(hours=1)
    return svc


@pytest.fixture
def gmail_service_no_domain_filter():
    from datetime import UTC, datetime, timedelta

    svc = GmailService(
        client_id="fake-id",
        client_secret="fake-secret",
        refresh_token="fake-refresh",
        allowed_domains=None,
    )
    svc._http_client = AsyncMock(spec=httpx.AsyncClient)
    svc._cached_token = "valid-token"
    svc._token_expiry = datetime.now(UTC) + timedelta(hours=1)
    return svc


# ---------------------------------------------------------------------------
# _extract_body_text
# ---------------------------------------------------------------------------


def test_extract_body_text_plain():
    payload = {
        "mimeType": "text/plain",
        "body": {"data": _b64("Hello, World!")},
    }
    assert _extract_body_text(payload) == "Hello, World!"


def test_extract_body_text_multipart():
    payload = {
        "mimeType": "multipart/alternative",
        "body": {},
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("Plain text")}},
            {"mimeType": "text/html", "body": {"data": _b64("<p>HTML</p>")}},
        ],
    }
    # Should prefer text/plain
    assert _extract_body_text(payload) == "Plain text"


def test_extract_body_text_html_fallback():
    payload = {
        "mimeType": "multipart/alternative",
        "body": {},
        "parts": [
            {"mimeType": "text/html", "body": {"data": _b64("<b>Bold</b>")}},
        ],
    }
    assert _extract_body_text(payload) == "<b>Bold</b>"


def test_extract_body_text_empty():
    payload = {"mimeType": "application/octet-stream", "body": {}}
    assert _extract_body_text(payload) == ""


def test_extract_body_text_nested_multipart():
    payload = {
        "mimeType": "multipart/mixed",
        "body": {},
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "body": {},
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _b64("Nested plain")}},
                ],
            },
        ],
    }
    assert _extract_body_text(payload) == "Nested plain"


def test_extract_body_text_nested_multipart_without_text():
    payload = {
        "mimeType": "multipart/mixed",
        "body": {},
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "body": {},
                "parts": [
                    {"mimeType": "application/octet-stream", "body": {}},
                ],
            },
        ],
    }
    assert _extract_body_text(payload) == ""


# ---------------------------------------------------------------------------
# GmailService.search_emails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_emails(gmail_service: GmailService):
    list_resp = _mock_response({"messages": [{"id": "msg1"}, {"id": "msg2"}]})
    detail_resp = _mock_response({"id": "msg1", "payload": {"headers": []}})
    gmail_service._http_client.get.side_effect = [list_resp, detail_resp, detail_resp]

    results = await gmail_service.search_emails("from:alice")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_emails_empty(gmail_service: GmailService):
    gmail_service._http_client.get.return_value = _mock_response({"messages": []})
    results = await gmail_service.search_emails("nonexistent query")
    assert results == []


@pytest.mark.asyncio
async def test_get_unread_emails_empty(gmail_service: GmailService):
    gmail_service._http_client.get.return_value = _mock_response({"messages": []})

    results = await gmail_service.get_unread_emails(max_results=5)

    assert results == []


@pytest.mark.asyncio
async def test_get_unread_emails_with_messages(gmail_service: GmailService):
    list_resp = _mock_response({"messages": [{"id": "msg1"}]})
    detail_resp = _mock_response({"id": "msg1", "payload": {"headers": []}})
    gmail_service._http_client.get.side_effect = [list_resp, detail_resp]

    results = await gmail_service.get_unread_emails(max_results=5)

    assert len(results) == 1
    assert results[0]["id"] == "msg1"


# ---------------------------------------------------------------------------
# GmailService.get_email_detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_email_detail(gmail_service: GmailService):
    raw = {
        "id": "msg42",
        "threadId": "thread1",
        "snippet": "Hello...",
        "labelIds": ["INBOX"],
        "internalDate": "1741564800000",
        "payload": {
            "headers": [
                {"name": "From", "value": "alice@example.com"},
                {"name": "Subject", "value": "Test"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64("Full body content")},
        },
    }
    gmail_service._http_client.get.return_value = _mock_response(raw)

    detail = await gmail_service.get_email_detail("msg42")
    assert detail["id"] == "msg42"
    assert detail["headers"]["From"] == "alice@example.com"
    assert detail["body"] == "Full body content"


# ---------------------------------------------------------------------------
# GmailService.send_email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_email(gmail_service: GmailService):
    gmail_service._http_client.post.return_value = _mock_response({"id": "sent1"})
    msg_id = await gmail_service.send_email(
        to="bob@example.com",
        subject="Hello",
        body="Test body",
    )
    assert msg_id == "sent1"


@pytest.mark.asyncio
async def test_send_email_blocked_domain(gmail_service: GmailService):
    with pytest.raises(EmailError, match="not in allowed domains"):
        await gmail_service.send_email(
            to="untrusted@blocked.invalid",
            subject="Nope",
            body="Blocked",
        )


@pytest.mark.asyncio
async def test_send_email_no_domain_filter(gmail_service_no_domain_filter: GmailService):
    gmail_service_no_domain_filter._http_client.post.return_value = _mock_response({"id": "sent2"})
    msg_id = await gmail_service_no_domain_filter.send_email(
        to="recipient@example.com",
        subject="Hi",
        body="No filter",
    )
    assert msg_id == "sent2"


# ---------------------------------------------------------------------------
# GmailService.create_draft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_draft(gmail_service: GmailService):
    gmail_service._http_client.post.return_value = _mock_response({"id": "draft1"})
    draft_id = await gmail_service.create_draft(
        to="bob@example.com",
        subject="Draft Subject",
        body="Draft body",
    )
    assert draft_id == "draft1"


@pytest.mark.asyncio
async def test_create_draft_blocked_domain(gmail_service: GmailService):
    with pytest.raises(EmailError, match="not in allowed domains"):
        await gmail_service.create_draft(
            to="untrusted@blocked.invalid",
            subject="Nope",
            body="Blocked",
        )


# ---------------------------------------------------------------------------
# GmailService.mark_as_read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_as_read(gmail_service: GmailService):
    gmail_service._http_client.post.return_value = _mock_response({})
    await gmail_service.mark_as_read("msg42")
    gmail_service._http_client.post.assert_called_once()
    call_kwargs = gmail_service._http_client.post.call_args
    assert "modify" in call_kwargs.args[0]


# ---------------------------------------------------------------------------
# GmailService.add_label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_label(gmail_service: GmailService):
    gmail_service._http_client.post.return_value = _mock_response({})
    await gmail_service.add_label("msg42", "IMPORTANT")
    gmail_service._http_client.post.assert_called_once()


# ---------------------------------------------------------------------------
# GmailService.get_thread
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_thread(gmail_service: GmailService):
    thread_data = {
        "messages": [
            {
                "id": "m1",
                "snippet": "First",
                "labelIds": ["INBOX"],
                "internalDate": "1000",
                "payload": {
                    "headers": [{"name": "Subject", "value": "Thread"}],
                    "mimeType": "text/plain",
                    "body": {"data": _b64("msg 1")},
                },
            },
            {
                "id": "m2",
                "snippet": "Second",
                "labelIds": ["INBOX"],
                "internalDate": "2000",
                "payload": {
                    "headers": [{"name": "Subject", "value": "Re: Thread"}],
                    "mimeType": "text/plain",
                    "body": {"data": _b64("msg 2")},
                },
            },
        ]
    }
    gmail_service._http_client.get.return_value = _mock_response(thread_data)
    messages = await gmail_service.get_thread("thread1")
    assert len(messages) == 2
    assert messages[0]["body"] == "msg 1"
    assert messages[1]["body"] == "msg 2"


# ---------------------------------------------------------------------------
# Validate recipient
# ---------------------------------------------------------------------------


def test_validate_recipient_invalid_email(gmail_service: GmailService):
    with pytest.raises(EmailError, match="Invalid email address"):
        gmail_service._validate_recipient("not-an-email")


# ---------------------------------------------------------------------------
# GmailService.create_draft — reply_to_message_id path (lines 170-171)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_draft_reply_sets_headers(gmail_service: GmailService):
    """Cover lines 170-171: create_draft with reply_to_message_id sets
    In-Reply-To and References headers from the original message's Message-ID.
    """
    original_message_id_header = "<original-123@example.com>"

    # Mock the GET call used by get_email_detail for the original message.
    gmail_service._http_client.get.return_value = _mock_response(
        {
            "id": "orig-msg-1",
            "threadId": "thread-42",
            "snippet": "Original message",
            "labelIds": ["INBOX"],
            "internalDate": "1741564800000",
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Subject", "value": "Original Subject"},
                    {"name": "Message-ID", "value": original_message_id_header},
                ],
                "mimeType": "text/plain",
                "body": {"data": _b64("Original body")},
            },
        }
    )

    # The POST creates the draft
    gmail_service._http_client.post.return_value = _mock_response({"id": "draft-reply-1"})

    draft_id = await gmail_service.create_draft(
        to="sender@example.com",
        subject="Re: Original Subject",
        body="This is a reply",
        reply_to_message_id="orig-msg-1",
    )

    assert draft_id == "draft-reply-1"

    # Verify the draft POST was called with the correct raw message
    post_call = gmail_service._http_client.post.call_args
    draft_body = post_call.kwargs.get("json") or post_call[1].get("json")
    assert draft_body is not None

    # The message should include the threadId
    assert draft_body["message"]["threadId"] == "thread-42"

    # Decode the raw MIME message and check In-Reply-To / References headers
    raw_b64 = draft_body["message"]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    raw_text = raw_bytes.decode("utf-8")

    assert f"In-Reply-To: {original_message_id_header}" in raw_text
    assert f"References: {original_message_id_header}" in raw_text


@pytest.mark.asyncio
async def test_create_draft_reply_without_message_id_header(gmail_service: GmailService):
    """Reply drafts should still thread even if the source message lacks Message-ID."""
    gmail_service._http_client.get.return_value = _mock_response(
        {
            "id": "orig-msg-2",
            "threadId": "thread-43",
            "snippet": "Original message",
            "labelIds": ["INBOX"],
            "internalDate": "1741564800000",
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Subject", "value": "Original Subject"},
                ],
                "mimeType": "text/plain",
                "body": {"data": _b64("Original body")},
            },
        }
    )
    gmail_service._http_client.post.return_value = _mock_response({"id": "draft-reply-2"})

    draft_id = await gmail_service.create_draft(
        to="sender@example.com",
        subject="Re: Original Subject",
        body="This is a reply",
        reply_to_message_id="orig-msg-2",
    )

    assert draft_id == "draft-reply-2"

    post_call = gmail_service._http_client.post.call_args
    draft_body = post_call.kwargs.get("json") or post_call[1].get("json")
    raw_b64 = draft_body["message"]["raw"]
    raw_text = base64.urlsafe_b64decode(raw_b64).decode("utf-8")

    assert "In-Reply-To:" not in raw_text
    assert "References:" not in raw_text
    assert draft_body["message"]["threadId"] == "thread-43"
