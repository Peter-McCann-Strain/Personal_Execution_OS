"""Response construction for completed MCP tool executions."""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from src.app.agents.specialists.tools import ToolResult
from src.app.domain.models import ChatResponse, MessageInput, ToolInvocationPlan


async def summarise_executed_tools(
    *,
    message: MessageInput,
    client: AsyncAnthropic,
    tool_use_blocks: list[ToolInvocationPlan],
    tool_results: list[dict[str, Any]],
    resumed_from_confirmation: bool,
) -> ChatResponse:
    """Summarize results and retain execution evidence in response metadata."""
    from src.app.domain.services.handlers import tools as facade

    result_objects: list[ToolResult] = []
    tool_events: list[dict[str, Any]] = []
    for block, result in zip(tool_use_blocks, tool_results, strict=True):
        content = result.get("content", "")
        is_error = bool(result.get("is_error", False))
        result_objects.append(
            ToolResult(
                tool=block.public_name,
                action="execute",
                success=not is_error,
                data={"result": content if isinstance(content, str) else str(content)},
                error=content if is_error else None,
            )
        )
        tool_events.append(
            {
                "name": block.public_name,
                "status": "failed" if is_error else "executed",
                "details": {
                    "idempotency_key": block.idempotency_key,
                    "argument_hash": block.argument_hash,
                    "resumed_from_confirmation": resumed_from_confirmation,
                    "result_preview": (
                        str(content)[:300] if not is_error and content is not None else None
                    ),
                    "error": str(content) if is_error else None,
                },
            }
        )

    summary = await facade.summarise_tool_results(message.content, result_objects, client)
    tool_call_status = "confirmed" if resumed_from_confirmation else "executed"

    return ChatResponse(
        content=summary,
        agent="tools",
        metadata={
            "tool_count": len(tool_use_blocks),
            "mcp_execution": True,
            "tools_executed": [block.public_name for block in tool_use_blocks],
            "tool_calls": [
                {
                    "name": block.public_name,
                    "status": tool_call_status,
                    "idempotency_key": block.idempotency_key,
                    "argument_hash": block.argument_hash,
                    "audit": block.audit_metadata,
                }
                for block in tool_use_blocks
            ],
            "errors": sum(1 for result in tool_results if result.get("is_error")),
            "tool_events": tool_events,
            "pending_tool_plan_cleared": resumed_from_confirmation,
            "confirmation_resumed": resumed_from_confirmation,
        },
    )
