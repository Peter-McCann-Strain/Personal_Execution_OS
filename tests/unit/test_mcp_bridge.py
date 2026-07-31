"""Tests for the MCP bridge — Claude tool_use to MCP tool execution."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.core.exceptions import MCPError
from src.app.core.mcp_bridge import (
    _format_content_for_claude,
    execute_tool_calls,
    format_mcp_tools_for_anthropic,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(
    resolve_result: tuple[str, str] | MCPError = ("server", "tool"),
    call_result: dict[str, Any] | MCPError | None = None,
) -> MagicMock:
    """Create a mock MCPClientManager.

    resolve_namespaced_tool is a sync method, so we use MagicMock for the
    manager and only make call_tool async via AsyncMock.
    """
    manager = MagicMock()

    # resolve_namespaced_tool is synchronous
    if isinstance(resolve_result, MCPError):
        manager.resolve_namespaced_tool.side_effect = resolve_result
    else:
        manager.resolve_namespaced_tool.return_value = resolve_result

    if call_result is None:
        call_result = {
            "content": [{"type": "text", "text": "result"}],
            "is_error": False,
        }

    # call_tool is async
    mock_call = AsyncMock()
    if isinstance(call_result, MCPError):
        mock_call.side_effect = call_result
    else:
        mock_call.return_value = call_result
    manager.call_tool = mock_call

    return manager


# ---------------------------------------------------------------------------
# execute_tool_calls
# ---------------------------------------------------------------------------


class TestExecuteToolCalls:
    """Test the main execute_tool_calls function."""

    @pytest.mark.asyncio
    async def test_empty_blocks_returns_empty(self):
        manager = _make_manager()
        result = await execute_tool_calls(manager, [])
        assert result == []

    @pytest.mark.asyncio
    async def test_single_successful_call(self):
        manager = _make_manager(
            resolve_result=("tavily", "search"),
            call_result={
                "content": [{"type": "text", "text": "Found 5 results"}],
                "is_error": False,
            },
        )

        blocks = [
            {"id": "toolu_1", "name": "tavily__search", "input": {"query": "python"}},
        ]
        results = await execute_tool_calls(manager, blocks)

        assert len(results) == 1
        assert results[0]["type"] == "tool_result"
        assert results[0]["tool_use_id"] == "toolu_1"
        # Content now flows through the untrusted-external envelope (P6.9)
        assert "Found 5 results" in results[0]["content"]
        assert "<mcp_tool_result>" in results[0]["content"]
        assert "trust=untrusted_external" in results[0]["content"]
        assert "untrusted_external_input" in results[0]["safety_flags"]
        assert results[0]["is_error"] is False

    @pytest.mark.asyncio
    async def test_multiple_calls_executed_concurrently(self):
        call_count = 0

        async def mock_call_tool(server, tool, args):
            nonlocal call_count
            call_count += 1
            return {
                "content": [{"type": "text", "text": f"result_{call_count}"}],
                "is_error": False,
            }

        manager = MagicMock()
        manager.resolve_namespaced_tool.side_effect = [
            ("tavily", "search"),
            ("fs", "read_file"),
        ]
        manager.call_tool = mock_call_tool

        blocks = [
            {"id": "toolu_1", "name": "tavily__search", "input": {"q": "test"}},
            {"id": "toolu_2", "name": "fs__read_file", "input": {"path": "/tmp/test"}},
        ]
        results = await execute_tool_calls(manager, blocks)

        assert len(results) == 2
        assert all(r["type"] == "tool_result" for r in results)
        assert results[0]["tool_use_id"] == "toolu_1"
        assert results[1]["tool_use_id"] == "toolu_2"

    @pytest.mark.asyncio
    async def test_unnamespaced_tool_returns_error(self):
        manager = _make_manager(
            resolve_result=MCPError("not namespaced"),
        )

        blocks = [
            {"id": "toolu_1", "name": "bad_tool_name", "input": {}},
        ]
        results = await execute_tool_calls(manager, blocks)

        assert len(results) == 1
        assert results[0]["is_error"] is True
        assert (
            "not namespaced" in results[0]["content"].lower()
            or "Unknown tool" in results[0]["content"]
        )

    @pytest.mark.asyncio
    async def test_server_error_returns_error_result(self):
        manager = _make_manager(
            resolve_result=("broken", "tool"),
            call_result=MCPError("Server crashed"),
        )

        blocks = [
            {"id": "toolu_1", "name": "broken__tool", "input": {}},
        ]
        results = await execute_tool_calls(manager, blocks)

        assert len(results) == 1
        assert results[0]["is_error"] is True
        assert "Server crashed" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_error(self):
        manager = MagicMock()
        manager.resolve_namespaced_tool.side_effect = RuntimeError("boom")

        blocks = [
            {"id": "toolu_1", "name": "server__tool", "input": {}},
        ]
        results = await execute_tool_calls(manager, blocks)

        assert len(results) == 1
        assert results[0]["is_error"] is True
        assert "boom" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_missing_id_defaults_to_unknown(self):
        manager = _make_manager(resolve_result=("s", "t"))

        blocks = [
            {"name": "s__t", "input": {}},  # no "id" key
        ]
        results = await execute_tool_calls(manager, blocks)
        assert results[0]["tool_use_id"] == "unknown"


# ---------------------------------------------------------------------------
# format_mcp_tools_for_anthropic
# ---------------------------------------------------------------------------


class TestFormatMCPToolsForAnthropic:
    """Test MCP-to-Anthropic tool format conversion."""

    def test_empty_list(self):
        assert format_mcp_tools_for_anthropic([]) == []

    def test_basic_conversion(self):
        mcp_tools = [
            {
                "server_name": "tavily",
                "tool_name": "search",
                "description": "Search the web",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ]

        result = format_mcp_tools_for_anthropic(mcp_tools)

        assert len(result) == 1
        assert result[0]["name"] == "tavily__search"
        assert result[0]["description"] == "Search the web"
        assert result[0]["input_schema"]["type"] == "object"
        assert "query" in result[0]["input_schema"]["properties"]

    def test_adds_type_if_missing(self):
        mcp_tools = [
            {
                "server_name": "fs",
                "tool_name": "read",
                "description": "Read file",
                "input_schema": {"properties": {"path": {"type": "string"}}},
            }
        ]

        result = format_mcp_tools_for_anthropic(mcp_tools)
        assert result[0]["input_schema"]["type"] == "object"

    def test_multiple_servers(self):
        mcp_tools = [
            {
                "server_name": "a",
                "tool_name": "t1",
                "description": "Tool 1",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "server_name": "b",
                "tool_name": "t2",
                "description": "Tool 2",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]

        result = format_mcp_tools_for_anthropic(mcp_tools)
        assert result[0]["name"] == "a__t1"
        assert result[1]["name"] == "b__t2"

    def test_missing_schema_gets_default(self):
        mcp_tools = [
            {
                "server_name": "s",
                "tool_name": "t",
                "description": "No schema",
            }
        ]

        result = format_mcp_tools_for_anthropic(mcp_tools)
        assert result[0]["input_schema"]["type"] == "object"


# ---------------------------------------------------------------------------
# _format_content_for_claude
# ---------------------------------------------------------------------------


class TestFormatContentForClaude:
    """Test content formatting for Claude tool_result blocks."""

    def test_empty_content_returns_message(self):
        result = _format_content_for_claude([])
        assert result == "Tool returned no content."

    def test_single_text_block(self):
        blocks = [{"type": "text", "text": "Hello world"}]
        result = _format_content_for_claude(blocks)
        assert result == "Hello world"

    def test_multiple_text_blocks_joined(self):
        blocks = [
            {"type": "text", "text": "Line 1"},
            {"type": "text", "text": "Line 2"},
        ]
        result = _format_content_for_claude(blocks)
        assert result == "Line 1\nLine 2"

    def test_mixed_content_returns_list(self):
        blocks = [
            {"type": "text", "text": "Description"},
            {"type": "image", "data": "base64data", "mimeType": "image/png"},
        ]
        result = _format_content_for_claude(blocks)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image"
        assert result[1]["source"]["type"] == "base64"
        assert result[1]["source"]["data"] == "base64data"

    def test_unknown_block_type_rendered_as_text(self):
        blocks = [
            {"type": "text", "text": "Normal"},
            {"type": "audio", "data": "audiodata"},
        ]
        result = _format_content_for_claude(blocks)
        assert isinstance(result, list)
        assert len(result) == 2
        assert "[audio content:" in result[1]["text"].lower()

    def test_image_default_mime_type(self):
        blocks = [
            {"type": "image", "data": "abc"},
        ]
        result = _format_content_for_claude(blocks)
        assert isinstance(result, list)
        assert result[0]["source"]["media_type"] == "image/png"
