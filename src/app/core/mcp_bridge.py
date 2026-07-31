"""Bridge between Claude's tool_use responses and MCP tool execution.

When Claude returns a tool_use block, this module:
1. Parses the tool name to identify the MCP server (namespaced as server__tool)
2. Executes the tool call via MCPClientManager
3. Returns the result formatted for Claude's tool_result content blocks

This is the glue between the Anthropic messages API and MCP servers — agents
don't need to know about MCP internals, they just receive tool definitions
and get results back.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Any

import structlog

from src.app.agents.tools.mcp_isolation import (
    build_blocked_tool_result,
    check_destination_allowlist,
    extract_destination_from_arguments,
    wrap_tool_result_for_llm,
)
from src.app.core.exceptions import MCPError
from src.app.core.mcp_client import MCPClientManager
from src.app.core.otel import bind_request_id, get_tracer
from src.app.core.tool_contracts import can_execute_in_parallel
from src.app.domain.models import ToolInvocationPlan

logger = structlog.get_logger()

# MCP protocol version we target. The April 2026 semconv spec landed
# ``mcp.protocol.version`` as a required attribute for MCP spans; this
# string is the version the mcp client library speaks.
_MCP_PROTOCOL_VERSION = "2024-11-05"


def _mcp_current_request_id() -> str | None:
    """Pull ``request_id`` out of structlog contextvars for span correlation."""
    try:
        ctx = structlog.contextvars.get_contextvars()
    except Exception:
        return None
    value = ctx.get("request_id")
    return value if isinstance(value, str) and value else None


async def execute_tool_calls(
    client_manager: MCPClientManager,
    tool_use_blocks: list[dict[str, Any]] | list[ToolInvocationPlan],
    *,
    destination_allowlist: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Execute Claude tool_use blocks through MCP and return tool_result blocks.

    Takes the tool_use content blocks from a Claude response, routes each one
    to the correct MCP server, and returns properly formatted tool_result
    blocks that can be sent back to Claude in the next turn.

    Args:
        client_manager: Connected MCPClientManager instance.
        tool_use_blocks: List of Claude tool_use dicts, each with:
            - id: str (tool use ID from Claude)
            - name: str (namespaced as "server-name__tool-name")
            - input: dict (arguments for the tool)

    Returns:
        List of tool_result dicts ready for Claude messages API::

            [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_...",
                    "content": "Search returned 5 results...",
                    "is_error": False,
                }
            ]
    """
    if not tool_use_blocks:
        return []

    plans = [_coerce_execution_plan(block) for block in tool_use_blocks]
    if can_execute_in_parallel(plans):
        tasks = [
            _execute_single_tool(client_manager, plan, destination_allowlist=destination_allowlist)
            for plan in plans
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    else:
        results = []
        for plan in plans:
            try:
                results.append(
                    await _execute_single_tool(
                        client_manager,
                        plan,
                        destination_allowlist=destination_allowlist,
                    )
                )
            except Exception as exc:  # pragma: no cover - preserved in result formatting below
                results.append(exc)

    tool_results: list[dict[str, Any]] = []
    for plan, result in zip(plans, results, strict=True):
        tool_use_id = plan.tool_id

        if isinstance(result, Exception):
            logger.error(
                "mcp_tool_execution_error",
                tool_use_id=tool_use_id,
                tool_name=plan.public_name,
                error=str(result),
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": f"Tool execution failed: {result}",
                    "is_error": True,
                    "idempotency_key": plan.idempotency_key,
                    "argument_hash": plan.argument_hash,
                }
            )
        else:
            tool_results.append(result)

    return tool_results


async def _execute_single_tool(
    client_manager: MCPClientManager,
    plan: ToolInvocationPlan,
    *,
    destination_allowlist: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Execute a single tool_use block and return a tool_result dict."""
    tool_use_id = plan.tool_id
    namespaced_name = plan.public_name
    arguments = plan.arguments

    # OTel MCP span — April 2026 semconv uses the mcp.* namespace.
    # `mcp.session.id` is synthesised per-call when the MCP client
    # doesn't surface a real session ID; the tool_use_id is a stable
    # per-call identifier so we use it directly where possible.
    tracer = get_tracer()
    session_id = getattr(client_manager, "session_id", None) or tool_use_id or uuid.uuid4().hex
    start_monotonic = time.monotonic()
    with tracer.start_as_current_span("mcp.tool.call") as span:
        bind_request_id(span, _mcp_current_request_id())
        try:
            span.set_attribute("mcp.method.name", "tools/call")
            span.set_attribute("mcp.tool.name", namespaced_name)
            span.set_attribute("mcp.protocol.version", _MCP_PROTOCOL_VERSION)
            span.set_attribute("mcp.session.id", str(session_id))
            span.set_attribute("mcp.tool.use_id", str(tool_use_id))
        except Exception:
            logger.debug("otel_mcp_set_request_attrs_failed", exc_info=True)

        try:
            server_name, tool_name = client_manager.resolve_namespaced_tool(namespaced_name)
        except MCPError:
            with contextlib.suppress(Exception):
                span.set_attribute("mcp.server.name", "unknown")
                span.set_attribute("mcp.tool.status", "unknown_tool")
                from opentelemetry.trace import Status, StatusCode

                span.set_status(Status(StatusCode.ERROR, "unknown tool"))
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": (
                    f"Unknown tool '{namespaced_name}'. Tool names must be namespaced "
                    "as 'server-name__tool-name'."
                ),
                "is_error": True,
            }

        with contextlib.suppress(Exception):
            span.set_attribute("mcp.server.name", server_name)
            span.set_attribute("mcp.tool.short_name", tool_name)

        # Destination allowlist (P6.10) — block before the call leaves the process.
        destination = extract_destination_from_arguments(tool_name, arguments)
        if destination:
            decision = check_destination_allowlist(tool_name, destination, destination_allowlist)
            if not decision.allowed:
                logger.error(
                    "mcp_tool_destination_blocked",
                    server=server_name,
                    tool=tool_name,
                    host=decision.host,
                    reason=decision.reason,
                )
                with contextlib.suppress(Exception):
                    span.set_attribute("mcp.tool.status", "destination_blocked")
                    span.set_attribute("mcp.tool.blocked_host", str(decision.host))
                    from opentelemetry.trace import Status, StatusCode

                    span.set_status(Status(StatusCode.ERROR, "destination blocked"))
                span.set_attribute(
                    "mcp.tool.latency_ms",
                    int((time.monotonic() - start_monotonic) * 1000),
                )
                return build_blocked_tool_result(
                    tool_use_id,
                    f"destination '{decision.host}' not on allowlist for {tool_name}",
                    idempotency_key=plan.idempotency_key,
                    argument_hash=plan.argument_hash,
                )

        try:
            result = await client_manager.call_tool(server_name, tool_name, arguments)
        except MCPError as exc:
            with contextlib.suppress(Exception):
                span.record_exception(exc)
                span.set_attribute("mcp.tool.status", "error")
                from opentelemetry.trace import Status, StatusCode

                span.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
            span.set_attribute(
                "mcp.tool.latency_ms",
                int((time.monotonic() - start_monotonic) * 1000),
            )
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": str(exc),
                "is_error": True,
            }

        # Format content for Claude
        content = _format_content_for_claude(result.get("content", []))

        # Content isolation (P6.9): wrap the tool result before it enters the
        # next LLM prompt. Only text-only results get wrapped as a single
        # string; mixed-content lists retain their original structure (images,
        # etc. don't benefit from the envelope and would break binary payloads).
        if isinstance(content, str):
            wrapped = wrap_tool_result_for_llm(
                server_name,
                tool_name,
                content,
            )
            final_content: str | list[dict[str, Any]] = wrapped.rendered_text
            safety_flags = wrapped.safety_flags
        else:
            final_content = content
            safety_flags = ["untrusted_external_input", "mixed_content"]

        span.set_attribute(
            "mcp.tool.latency_ms",
            int((time.monotonic() - start_monotonic) * 1000),
        )
        span.set_attribute(
            "mcp.tool.status",
            "error" if result.get("is_error", False) else "ok",
        )

        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": final_content,
            "is_error": result.get("is_error", False),
            "idempotency_key": plan.idempotency_key,
            "argument_hash": plan.argument_hash,
            "safety_flags": safety_flags,
        }


def _coerce_execution_plan(block: dict[str, Any] | ToolInvocationPlan) -> ToolInvocationPlan:
    """Accept legacy tool blocks while preferring canonical invocation plans."""
    if isinstance(block, ToolInvocationPlan):
        return block

    public_name = str(block.get("name", ""))
    raw_id = block.get("id")
    tool_use_id = str(raw_id) if raw_id else "unknown"
    return ToolInvocationPlan(
        tool_id=tool_use_id,
        server_name=public_name.split("__", 1)[0] if "__" in public_name else "",
        tool_name=public_name.split("__", 1)[-1] if "__" in public_name else public_name,
        public_name=public_name,
        arguments=dict(block.get("input", {})),
        input_schema={},
        argument_hash="",
        idempotency_key=str(block.get("idempotency_key", "")),
        trust_context=str((block.get("audit") or {}).get("trust_label", "")),
        requires_confirmation=bool((block.get("audit") or {}).get("confirmation_required", False)),
        mutation_class=(
            "mutating"
            if (block.get("audit") or {}).get("confirmation_required", False)
            else "read_only"
        ),
        allowed_parallelism="parallel_read_only",
        audit_metadata=dict(block.get("audit", {})),
        workflow_id=None,
    )


def format_mcp_tools_for_anthropic(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert MCP tool definitions to Anthropic's tool format.

    Takes the raw tool list from MCPClientManager.list_tools() and converts
    each entry into the format expected by the Anthropic messages API ``tools``
    parameter.

    Args:
        mcp_tools: List of dicts from MCPClientManager.list_tools(), each with:
            - server_name: str
            - tool_name: str
            - description: str
            - input_schema: dict

    Returns:
        List of Anthropic-compatible tool definitions::

            [
                {
                    "name": "tavily-search__search",
                    "description": "Search the web.",
                    "input_schema": { "type": "object", ... }
                }
            ]
    """
    anthropic_tools: list[dict[str, Any]] = []
    for tool in mcp_tools:
        name = f"{tool['server_name']}__{tool['tool_name']}"
        input_schema = tool.get("input_schema", {"type": "object", "properties": {}})

        # Ensure the schema always has a top-level type
        if "type" not in input_schema:
            input_schema["type"] = "object"

        anthropic_tools.append(
            {
                "name": name,
                "description": tool.get("description", ""),
                "input_schema": input_schema,
            }
        )
    return anthropic_tools


def _format_content_for_claude(content_blocks: list[dict[str, Any]]) -> str | list[dict[str, Any]]:
    """Format MCP content blocks for Claude's tool_result.

    If all blocks are text, concatenates them into a single string (Claude
    handles plain text tool results best). If there are mixed types (images,
    resources), returns the structured list.

    Args:
        content_blocks: List of serialised MCP content block dicts.

    Returns:
        Either a plain string or a list of content block dicts.
    """
    if not content_blocks:
        return "Tool returned no content."

    # Check if all blocks are text
    all_text = all(block.get("type") == "text" for block in content_blocks)

    if all_text:
        texts = [block.get("text", "") for block in content_blocks]
        return "\n".join(texts)

    # Mixed content — return structured blocks for Claude
    formatted: list[dict[str, Any]] = []
    for block in content_blocks:
        block_type = block.get("type", "text")
        if block_type == "text":
            formatted.append(
                {
                    "type": "text",
                    "text": block.get("text", ""),
                }
            )
        elif block_type == "image":
            formatted.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": block.get("mimeType", "image/png"),
                        "data": block.get("data", ""),
                    },
                }
            )
        else:
            # Other types (audio, resource, etc.) — render as text summary
            formatted.append(
                {
                    "type": "text",
                    "text": f"[{block_type} content: "
                    f"{block.get('data', block.get('text', 'N/A'))}]",
                }
            )

    return formatted
