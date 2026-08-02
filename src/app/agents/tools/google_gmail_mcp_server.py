"""Native Gmail MCP server backed by the in-repo Gmail client."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from src.app.agents.tools.email import GmailService
from src.app.agents.tools.google_mcp_env import load_google_mcp_env
from src.app.agents.tools.mcp_subprocess_logging import configure_mcp_subprocess_logging

configure_mcp_subprocess_logging()


def _service_from_env() -> GmailService:
    creds = load_google_mcp_env()
    return GmailService(
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        refresh_token=creds.refresh_token,
    )


@dataclass
class GmailContext:
    service: GmailService


@asynccontextmanager
async def gmail_lifespan(_server: MCPServer[GmailContext]) -> AsyncIterator[GmailContext]:
    service = _service_from_env()
    try:
        yield GmailContext(service=service)
    finally:
        await service.close()


mcp: MCPServer[GmailContext] = MCPServer("Gmail", lifespan=gmail_lifespan)


def _get_service(ctx: Context[GmailContext]) -> GmailService:
    return ctx.request_context.lifespan_context.service


@mcp.tool()
async def list_messages(
    ctx: Context[GmailContext],
    query: str | None = None,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """List recent mailbox messages, optionally filtered by a Gmail query."""
    service = _get_service(ctx)
    if query:
        return await service.search_emails(query=query, max_results=max_results)
    return await service.get_unread_emails(max_results=max_results)


@mcp.tool()
async def search_messages(
    ctx: Context[GmailContext],
    query: str,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Search messages using Gmail query syntax."""
    return await _get_service(ctx).search_emails(query=query, max_results=max_results)


@mcp.tool()
async def read_message(ctx: Context[GmailContext], message_id: str) -> dict[str, Any]:
    """Read a single message including decoded body text."""
    return await _get_service(ctx).get_email_detail(message_id)


async def create_draft(
    ctx: Context[GmailContext],
    to: str,
    subject: str,
    body: str,
    reply_to_message_id: str | None = None,
) -> dict[str, str]:
    """Create a draft email."""
    draft_id = await _get_service(ctx).create_draft(
        to=to,
        subject=subject,
        body=body,
        reply_to_message_id=reply_to_message_id,
    )
    return {"draft_id": draft_id}


async def send_message(
    ctx: Context[GmailContext],
    to: str,
    subject: str,
    body: str,
) -> dict[str, str]:
    """Send an email message immediately."""
    message_id = await _get_service(ctx).send_email(
        to=to,
        subject=subject,
        body=body,
    )
    return {"message_id": message_id}


@mcp.tool()
async def get_thread(ctx: Context[GmailContext], thread_id: str) -> list[dict[str, Any]]:
    """Fetch all messages in a Gmail thread."""
    return await _get_service(ctx).get_thread(thread_id)


async def mark_as_read(ctx: Context[GmailContext], message_id: str) -> dict[str, bool]:
    """Remove the UNREAD label from a message."""
    await _get_service(ctx).mark_as_read(message_id)
    return {"success": True}


async def add_label(
    ctx: Context[GmailContext],
    message_id: str,
    label: str,
) -> dict[str, bool]:
    """Add a Gmail label to a message."""
    await _get_service(ctx).add_label(message_id, label)
    return {"success": True}


if __name__ == "__main__":
    mcp.run(transport="stdio")
