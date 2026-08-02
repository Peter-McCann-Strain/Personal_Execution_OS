"""Tests for the MCP client manager."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.exceptions import MCPError
from src.app.core.mcp_client import (
    MCPClientManager,
    ServerCircuitBreaker,
    _serialise_content_blocks,
)

# ---------------------------------------------------------------------------
# MCPClientManager — construction
# ---------------------------------------------------------------------------


class TestMCPClientManagerInit:
    """Test MCPClientManager construction."""

    def test_creates_successfully(self):
        manager = MCPClientManager()
        assert manager.connected is False

    @patch("src.app.core.mcp_client.MCP_AVAILABLE", False)
    def test_raises_when_mcp_not_installed(self):
        with pytest.raises(MCPError, match=r"mcp.*not installed"):
            MCPClientManager()


class TestServerCircuitBreaker:
    """Test circuit breaker state transitions."""

    def test_closed_allows_requests(self):
        breaker = ServerCircuitBreaker()
        assert breaker.allow_request is True

    def test_opens_after_failures_and_recovers_after_timeout(self, monkeypatch: pytest.MonkeyPatch):
        breaker = ServerCircuitBreaker(fail_max=2, reset_timeout_seconds=10)
        fake_now = [100.0]

        monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])

        breaker.record_failure()
        assert breaker.allow_request is True

        breaker.record_failure()
        assert breaker.allow_request is False

        fake_now[0] += 11.0
        assert breaker.allow_request is True
        assert breaker._state == "half-open"

    def test_record_success_closes_breaker(self):
        breaker = ServerCircuitBreaker(fail_max=1)
        breaker.record_failure()
        assert breaker.allow_request is False
        breaker.record_success()
        assert breaker.allow_request is True


# ---------------------------------------------------------------------------
# MCPClientManager — resolve_namespaced_tool
# ---------------------------------------------------------------------------


class TestResolveNamespacedTool:
    """Test namespaced tool name parsing."""

    def test_valid_namespaced_name(self):
        manager = MCPClientManager()
        server, tool = manager.resolve_namespaced_tool("tavily-search__search")
        assert server == "tavily-search"
        assert tool == "search"

    def test_tool_name_with_double_underscore(self):
        manager = MCPClientManager()
        server, tool = manager.resolve_namespaced_tool("server__tool__extra")
        assert server == "server"
        assert tool == "tool__extra"

    def test_applies_exposed_tool_aliases(self):
        manager = MCPClientManager()
        manager._server_configs["tavily-search"] = {
            "exposed_tools": {
                "search": "tavily_web_search",
            }
        }

        server, tool = manager.resolve_namespaced_tool("tavily-search__search")
        assert server == "tavily-search"
        assert tool == "tavily_web_search"

    def test_no_separator_raises(self):
        manager = MCPClientManager()
        with pytest.raises(MCPError, match="not namespaced"):
            manager.resolve_namespaced_tool("plain_tool_name")

    def test_empty_string_raises(self):
        manager = MCPClientManager()
        with pytest.raises(MCPError, match="not namespaced"):
            manager.resolve_namespaced_tool("")


# ---------------------------------------------------------------------------
# MCPClientManager — get_tools_for_claude (with mocked servers)
# ---------------------------------------------------------------------------


def _make_mock_tool(name: str, description: str, schema: dict | None = None) -> MagicMock:
    """Create a mock MCP Tool object."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.input_schema = schema or {"type": "object", "properties": {}}
    return tool


class TestGetToolsForClaude:
    """Test conversion of MCP tools to Anthropic format."""

    def test_empty_when_no_servers(self):
        manager = MCPClientManager()
        assert manager.get_tools_for_claude() == []

    def test_excludes_unavailable_servers(self):
        manager = MCPClientManager()
        conn = MagicMock()
        conn.available = False
        conn.tools = [_make_mock_tool("search", "Search")]
        manager._servers["test-server"] = conn
        assert manager.get_tools_for_claude() == []

    def test_namespaces_tool_names(self):
        manager = MCPClientManager()
        conn = MagicMock()
        conn.available = True
        conn.tools = [
            _make_mock_tool("search", "Search the web"),
            _make_mock_tool("extract", "Extract content"),
        ]
        manager._servers["tavily"] = conn

        tools = manager.get_tools_for_claude()
        assert len(tools) == 2
        assert tools[0]["name"] == "tavily__search"
        assert tools[0]["description"] == "Search the web"
        assert tools[1]["name"] == "tavily__extract"

    def test_multiple_servers(self):
        manager = MCPClientManager()

        conn1 = MagicMock()
        conn1.available = True
        conn1.tools = [_make_mock_tool("search", "Web search")]
        manager._servers["tavily"] = conn1

        conn2 = MagicMock()
        conn2.available = True
        conn2.tools = [_make_mock_tool("read_file", "Read a file")]
        manager._servers["filesystem"] = conn2

        tools = manager.get_tools_for_claude()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert "tavily__search" in names
        assert "filesystem__read_file" in names

    def test_exposes_public_alias_names_when_configured(self):
        manager = MCPClientManager()
        conn = MagicMock()
        conn.available = True
        conn.tools = [_make_mock_tool("tavily_web_search", "Web search")]
        manager._servers["tavily-search"] = conn
        manager._server_configs["tavily-search"] = {
            "exposed_tools": {
                "search": "tavily_web_search",
            }
        }

        tools = manager.get_tools_for_claude()
        assert tools == [
            {
                "name": "tavily-search__search",
                "description": "Web search",
                "input_schema": {"type": "object", "properties": {}},
            }
        ]

    def test_uses_current_mcp_tool_model_fields(self):
        """Real MCP v2 Tool models expose input_schema, not the v1 alias name."""
        from mcp import Tool

        manager = MCPClientManager()
        conn = MagicMock()
        conn.available = True
        conn.tools = [
            Tool(
                name="search",
                description="Search the web",
                inputSchema={"type": "object", "properties": {"query": {"type": "string"}}},
            )
        ]
        manager._servers["current-sdk"] = conn

        assert manager.get_tools_for_claude() == [
            {
                "name": "current-sdk__search",
                "description": "Search the web",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            }
        ]


# ---------------------------------------------------------------------------
# MCPClientManager — get_server_status
# ---------------------------------------------------------------------------


class TestGetServerStatus:
    """Test server status reporting."""

    def test_reports_status_of_all_servers(self):
        manager = MCPClientManager()

        conn_ok = MagicMock()
        conn_ok.available = True
        conn_ok.tools = [_make_mock_tool("search", "Search")]
        conn_ok.error = None
        manager._servers["tavily"] = conn_ok

        conn_fail = MagicMock()
        conn_fail.available = False
        conn_fail.tools = []
        conn_fail.error = "Connection refused"
        manager._servers["gmail"] = conn_fail

        status = manager.get_server_status()
        assert status["tavily"]["available"] is True
        assert status["tavily"]["tools"] == ["search"]
        assert status["gmail"]["available"] is False
        assert status["gmail"]["error"] == "Connection refused"

    def test_reports_public_tool_names_for_aliases(self):
        manager = MCPClientManager()

        conn = MagicMock()
        conn.available = True
        conn.tools = [_make_mock_tool("list_calendar_events", "List events")]
        conn.error = None
        manager._servers["google-calendar"] = conn
        manager._server_configs["google-calendar"] = {
            "exposed_tools": {
                "list_events": "list_calendar_events",
            }
        }

        status = manager.get_server_status()
        assert status["google-calendar"]["tools"] == ["list_events"]


# ---------------------------------------------------------------------------
# MCPClientManager — call_tool
# ---------------------------------------------------------------------------


class TestCallTool:
    """Test tool call execution."""

    @pytest.mark.asyncio
    async def test_unknown_server_raises(self):
        manager = MCPClientManager()
        with pytest.raises(MCPError, match="Unknown MCP server"):
            await manager.call_tool("nonexistent", "tool", {})

    @pytest.mark.asyncio
    async def test_unavailable_server_raises(self):
        manager = MCPClientManager()
        import asyncio

        conn = MagicMock()
        conn.available = False
        conn.session = None
        conn.error = "Connection refused"
        manager._servers["broken"] = conn
        manager._locks["broken"] = asyncio.Lock()

        # Reconnect also fails
        with (
            patch.object(manager, "_reconnect_server", new_callable=AsyncMock, return_value=False),
            pytest.raises(MCPError, match=r"not available.*Connection refused"),
        ):
            await manager.call_tool("broken", "tool", {})

    @pytest.mark.asyncio
    async def test_successful_tool_call(self):
        import asyncio

        manager = MCPClientManager()

        # Mock a successful call_tool result
        mock_text_block = MagicMock()
        mock_text_block.model_dump.return_value = {"type": "text", "text": "result data"}

        mock_result = MagicMock()
        mock_result.content = [mock_text_block]
        mock_result.is_error = False
        mock_result.structured_content = None

        mock_session = AsyncMock()
        mock_session.call_tool.return_value = mock_result

        conn = MagicMock()
        conn.available = True
        conn.session = mock_session
        conn.error = None
        manager._servers["test"] = conn
        manager._locks["test"] = asyncio.Lock()

        result = await manager.call_tool("test", "my_tool", {"key": "value"})
        assert result["is_error"] is False
        assert len(result["content"]) == 1
        assert result["content"][0]["text"] == "result data"
        mock_session.call_tool.assert_called_once_with("my_tool", {"key": "value"})

    @pytest.mark.asyncio
    async def test_tool_call_falls_back_to_structured_content(self):
        import asyncio

        manager = MCPClientManager()

        mock_result = MagicMock()
        mock_result.content = []
        mock_result.structured_content = {"events": []}
        mock_result.is_error = False

        mock_session = AsyncMock()
        mock_session.call_tool.return_value = mock_result

        conn = MagicMock()
        conn.available = True
        conn.session = mock_session
        conn.error = None
        manager._servers["test"] = conn
        manager._locks["test"] = asyncio.Lock()

        result = await manager.call_tool("test", "my_tool", {"key": "value"})
        assert result["is_error"] is False
        assert result["content"] == [{"type": "text", "text": '{"events": []}'}]
        assert result["structured_content"] == {"events": []}

    @pytest.mark.asyncio
    async def test_tool_call_uses_current_mcp_result_model_fields(self):
        """Real MCP v2 results should serialize through snake-case Python fields."""
        import asyncio

        from mcp.types import CallToolResult, TextContent

        manager = MCPClientManager()
        session = AsyncMock()
        session.call_tool.return_value = CallToolResult(
            content=[TextContent(type="text", text="current result")],
            structuredContent={"version": 2},
            isError=False,
        )
        conn = MagicMock(available=True, session=session, error=None)
        manager._servers["current-sdk"] = conn
        manager._locks["current-sdk"] = asyncio.Lock()

        result = await manager.call_tool("current-sdk", "search", {})

        assert result == {
            "content": [{"type": "text", "text": "current result"}],
            "is_error": False,
            "structured_content": {"version": 2},
        }

    @pytest.mark.asyncio
    async def test_tool_call_error_wraps_in_mcp_error(self):
        import asyncio

        manager = MCPClientManager()

        mock_session = AsyncMock()
        mock_session.call_tool.side_effect = RuntimeError("Server crashed")

        conn = MagicMock()
        conn.available = True
        conn.session = mock_session
        conn.error = None
        manager._servers["test"] = conn
        manager._locks["test"] = asyncio.Lock()

        with pytest.raises(MCPError, match="Server crashed"):
            await manager.call_tool("test", "broken_tool", {})

    @pytest.mark.asyncio
    async def test_tool_call_reconnects_after_connection_error(self):
        import asyncio

        manager = MCPClientManager()

        old_session = AsyncMock()
        old_session.call_tool.side_effect = BrokenPipeError("transport broken")

        new_session = AsyncMock()
        mock_text_block = MagicMock()
        mock_text_block.model_dump.return_value = {"type": "text", "text": "recovered"}
        retry_result = MagicMock()
        retry_result.content = [mock_text_block]
        retry_result.is_error = False
        retry_result.structured_content = None
        new_session.call_tool.return_value = retry_result

        conn = MagicMock()
        conn.available = True
        conn.session = old_session
        conn.error = None
        manager._servers["test"] = conn
        manager._locks["test"] = asyncio.Lock()
        manager._server_configs["test"] = {"command": "echo", "args": []}

        async def fake_reconnect(name):
            manager._servers[name].available = True
            manager._servers[name].session = new_session
            manager._servers[name].error = None
            return True

        with patch.object(
            manager, "_reconnect_server", side_effect=fake_reconnect
        ) as mock_reconnect:
            result = await manager.call_tool("test", "my_tool", None)

        assert result["is_error"] is False
        assert result["content"][0]["text"] == "recovered"
        mock_reconnect.assert_awaited()
        old_session.call_tool.assert_awaited_once_with("my_tool", None)
        new_session.call_tool.assert_awaited_once_with("my_tool", None)

    @pytest.mark.asyncio
    async def test_tool_call_reconnects_when_server_was_marked_unavailable(self):
        import asyncio

        manager = MCPClientManager()

        new_session = AsyncMock()
        mock_text_block = MagicMock()
        mock_text_block.model_dump.return_value = {"type": "text", "text": "fresh"}
        retry_result = MagicMock()
        retry_result.content = [mock_text_block]
        retry_result.is_error = False
        retry_result.structured_content = None
        new_session.call_tool.return_value = retry_result

        conn = MagicMock()
        conn.available = False
        conn.session = None
        conn.error = "connection lost"
        manager._servers["test"] = conn
        manager._locks["test"] = asyncio.Lock()
        manager._server_configs["test"] = {"command": "echo", "args": []}

        async def fake_reconnect(name):
            manager._servers[name].available = True
            manager._servers[name].session = new_session
            manager._servers[name].error = None
            return True

        with patch.object(
            manager, "_reconnect_server", side_effect=fake_reconnect
        ) as mock_reconnect:
            result = await manager.call_tool("test", "my_tool", {})

        assert result["content"][0]["text"] == "fresh"
        mock_reconnect.assert_awaited_once_with("test")
        new_session.call_tool.assert_awaited_once_with("my_tool", {})

    @pytest.mark.asyncio
    async def test_tool_call_reconnect_retry_failure_raises(self):
        import asyncio

        manager = MCPClientManager()

        old_session = AsyncMock()
        old_session.call_tool.side_effect = EOFError("gone")

        retry_session = AsyncMock()
        retry_session.call_tool.side_effect = RuntimeError("still broken")

        conn = MagicMock()
        conn.available = True
        conn.session = old_session
        conn.error = None
        manager._servers["test"] = conn
        manager._locks["test"] = asyncio.Lock()
        manager._server_configs["test"] = {"command": "echo", "args": []}

        async def fake_reconnect(name):
            manager._servers[name].available = True
            manager._servers[name].session = retry_session
            manager._servers[name].error = None
            return True

        with (
            patch.object(manager, "_reconnect_server", side_effect=fake_reconnect),
            pytest.raises(MCPError, match="after reconnect"),
        ):
            await manager.call_tool("test", "my_tool", {})

    @pytest.mark.asyncio
    async def test_tool_call_reconnect_failure_after_connection_error_raises(self):
        import asyncio

        manager = MCPClientManager()

        old_session = AsyncMock()
        old_session.call_tool.side_effect = BrokenPipeError("transport broken")

        conn = MagicMock()
        conn.available = True
        conn.session = old_session
        conn.error = None
        manager._servers["test"] = conn
        manager._locks["test"] = asyncio.Lock()

        with (
            patch.object(manager, "_reconnect_server", return_value=False),
            pytest.raises(MCPError, match="reconnect was unsuccessful"),
        ):
            await manager.call_tool("test", "my_tool", {})


# ---------------------------------------------------------------------------
# MCPClientManager — list_tools
# ---------------------------------------------------------------------------


class TestListTools:
    """Test tool listing."""

    @pytest.mark.asyncio
    async def test_lists_tools_from_available_servers(self):
        manager = MCPClientManager()

        conn = MagicMock()
        conn.available = True
        conn.tools = [
            _make_mock_tool("search", "Search", {"type": "object", "properties": {"q": {}}}),
        ]
        manager._servers["tavily"] = conn

        tools = await manager.list_tools()
        assert len(tools) == 1
        assert tools[0]["server_name"] == "tavily"
        assert tools[0]["tool_name"] == "search"
        assert tools[0]["description"] == "Search"

    @pytest.mark.asyncio
    async def test_skips_unavailable_servers(self):
        manager = MCPClientManager()

        conn = MagicMock()
        conn.available = False
        conn.tools = [_make_mock_tool("search", "Search")]
        manager._servers["broken"] = conn

        tools = await manager.list_tools()
        assert tools == []


# ---------------------------------------------------------------------------
# MCPClientManager — disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    """Test disconnect behaviour."""

    @pytest.mark.asyncio
    async def test_disconnect_clears_state(self):
        manager = MCPClientManager()
        manager._servers["test"] = MagicMock()
        manager._locks["test"] = MagicMock()
        manager._connected = True

        await manager.disconnect()
        assert manager.connected is False
        assert len(manager._servers) == 0
        assert len(manager._locks) == 0

    @pytest.mark.asyncio
    async def test_disconnect_handles_exit_stack_error(self):
        manager = MCPClientManager()
        mock_stack = AsyncMock()
        mock_stack.aclose.side_effect = RuntimeError("cleanup error")
        manager._server_stacks["broken"] = mock_stack
        manager._connected = True

        # Should not raise
        await manager.disconnect()
        assert manager.connected is False
        assert len(manager._server_stacks) == 0


# ---------------------------------------------------------------------------
# _serialise_content_blocks
# ---------------------------------------------------------------------------


class TestSerialiseContentBlocks:
    """Test content block serialisation."""

    def test_model_dump_block(self):
        block = MagicMock()
        block.model_dump.return_value = {"type": "text", "text": "hello"}
        result = _serialise_content_blocks([block])
        assert result == [{"type": "text", "text": "hello"}]

    def test_text_attribute_fallback(self):
        block = MagicMock(spec=["text"])
        block.text = "hello"
        result = _serialise_content_blocks([block])
        assert result == [{"type": "text", "text": "hello"}]

    def test_unknown_block_type(self):
        block = "just a string"
        result = _serialise_content_blocks([block])
        assert result == [{"type": "unknown", "data": "just a string"}]

    def test_empty_list(self):
        assert _serialise_content_blocks([]) == []

    def test_multiple_blocks(self):
        block1 = MagicMock()
        block1.model_dump.return_value = {"type": "text", "text": "first"}
        block2 = MagicMock()
        block2.model_dump.return_value = {"type": "image", "data": "base64..."}
        result = _serialise_content_blocks([block1, block2])
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image"


# ---------------------------------------------------------------------------
# MCPClientManager — connect()
# ---------------------------------------------------------------------------


class TestConnect:
    """Test connect() method."""

    @pytest.mark.asyncio
    async def test_connect_already_connected_disconnects_first(self):
        """If already connected, connect() should disconnect before reconnecting."""
        manager = MCPClientManager()
        manager._connected = True

        # Mock disconnect to avoid real cleanup
        manager.disconnect = AsyncMock()

        # Mock _connect_server to avoid real subprocess
        with patch.object(manager, "_connect_server", new_callable=AsyncMock):
            await manager.connect({"test": {"command": "echo", "args": []}})

        manager.disconnect.assert_awaited_once()
        assert manager._connected is True

    @pytest.mark.asyncio
    async def test_connect_stores_configs_and_sets_connected(self):
        """connect() should store server configs and mark as connected."""
        manager = MCPClientManager()

        with patch.object(manager, "_connect_server", new_callable=AsyncMock):
            await manager.connect({"server1": {"command": "echo", "args": []}})

        assert manager._connected is True
        assert "server1" in manager._server_configs

    @pytest.mark.asyncio
    async def test_connect_logs_available_and_unavailable(self):
        """connect() should track server availability correctly."""
        manager = MCPClientManager()

        async def mock_connect_server(name, config):
            from src.app.core.mcp_client import ServerConnection

            try:
                from mcp.client.stdio import StdioServerParameters
            except ImportError:
                pytest.skip("mcp package not available")

            params = StdioServerParameters(
                command=config["command"],
                args=config.get("args", []),
            )
            conn = ServerConnection(name=name, params=params)
            if name == "good":
                conn.available = True
            else:
                conn.available = False
                conn.error = "failed"
            manager._servers[name] = conn
            manager._locks[name] = __import__("asyncio").Lock()

        with patch.object(manager, "_connect_server", side_effect=mock_connect_server):
            await manager.connect(
                {
                    "good": {"command": "echo", "args": []},
                    "bad": {"command": "false", "args": []},
                }
            )

        assert manager._connected is True
        assert manager._servers["good"].available is True
        assert manager._servers["bad"].available is False

    @pytest.mark.asyncio
    async def test_connect_handles_connect_server_exception(self):
        """connect() should handle exceptions from _connect_server via gather."""
        manager = MCPClientManager()

        async def failing_connect(name, config):
            raise RuntimeError("subprocess failed")

        with patch.object(manager, "_connect_server", side_effect=failing_connect):
            # gather(return_exceptions=True) should swallow the error
            await manager.connect({"broken": {"command": "bad", "args": []}})

        assert manager._connected is True

    @pytest.mark.asyncio
    async def test_connect_logs_all_servers_failed_when_none_available(self):
        """connect() should emit the all-failed log path if every server is unavailable."""
        manager = MCPClientManager()

        async def fake_connect_server(name, config):
            from mcp.client.stdio import StdioServerParameters

            from src.app.core.mcp_client import ServerConnection

            conn = ServerConnection(
                name=name,
                params=StdioServerParameters(
                    command=config["command"], args=config.get("args", [])
                ),
            )
            conn.available = False
            conn.error = "failed"
            manager._servers[name] = conn

        with (
            patch.object(manager, "_connect_server", side_effect=fake_connect_server),
            patch("src.app.core.mcp_client.logger.error") as mock_log_error,
        ):
            await manager.connect(
                {
                    "first": {"command": "echo", "args": []},
                    "second": {"command": "echo", "args": []},
                }
            )

        mock_log_error.assert_any_call("mcp_all_servers_failed", total=2)


# ---------------------------------------------------------------------------
# MCPClientManager — _connect_server()
# ---------------------------------------------------------------------------


class TestConnectServer:
    """Test _connect_server() method."""

    @pytest.mark.asyncio
    async def test_connect_server_success(self):
        """_connect_server should set up session and discover tools."""
        manager = MCPClientManager()
        manager._breakers["test-server"] = ServerCircuitBreaker()

        mock_tool = MagicMock()
        mock_tool.name = "search"
        mock_tool.description = "Search"
        mock_tool.input_schema = {"type": "object"}

        mock_tools_result = MagicMock()
        mock_tools_result.tools = [mock_tool]

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_tools_result)

        with (
            patch("src.app.core.mcp_client.stdio_client") as mock_stdio,
            patch("src.app.core.mcp_client._session_context") as mock_session_ctx,
        ):
            # stdio_client returns an async context manager yielding (read, write)
            mock_transport_cm = AsyncMock()
            mock_transport_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_transport_cm.__aexit__ = AsyncMock(return_value=False)
            mock_stdio.return_value = mock_transport_cm

            # _session_context returns an async context manager yielding the session
            mock_sess_cm = AsyncMock()
            mock_sess_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess_cm.__aexit__ = AsyncMock(return_value=False)
            mock_session_ctx.return_value = mock_sess_cm

            await manager._connect_server("test-server", {"command": "echo", "args": []})

        conn = manager._servers["test-server"]
        assert conn.available is True
        assert conn.session is mock_session
        assert len(conn.tools) == 1
        assert conn.tools[0].name == "search"
        assert "test-server" in manager._locks
        assert "test-server" in manager._server_stacks
        assert manager._breakers["test-server"]._failure_count == 0

        # Clean up
        await manager._server_stacks["test-server"].aclose()

    @pytest.mark.asyncio
    async def test_streamable_http_uses_v2_transport_and_authenticated_client(self):
        """Remote MCP connections must use the v2 transport name and HTTP client API."""
        oauth_client = AsyncMock()
        oauth_client.acquire_token.return_value = "access-token"
        manager = MCPClientManager(oauth_client=oauth_client)

        tools_result = MagicMock(tools=[])
        session = AsyncMock()
        session.list_tools.return_value = tools_result
        http_client = MagicMock()

        http_client_context = AsyncMock()
        http_client_context.__aenter__.return_value = http_client
        transport_context = AsyncMock()
        transport_context.__aenter__.return_value = (MagicMock(), MagicMock())
        session_context = AsyncMock()
        session_context.__aenter__.return_value = session

        with (
            patch(
                "src.app.core.mcp_client.create_mcp_http_client",
                return_value=http_client_context,
            ) as create_http_client,
            patch(
                "src.app.core.mcp_client.streamable_http_client",
                return_value=transport_context,
            ) as create_transport,
            patch(
                "src.app.core.mcp_client._session_context",
                return_value=session_context,
            ),
        ):
            await manager._connect_server(
                "remote",
                {
                    "transport": "streamable-http",
                    "url": "https://mcp.example.test/mcp",
                },
            )

        assert manager._servers["remote"].available is True
        oauth_client.acquire_token.assert_awaited_once_with(
            "remote",
            "https://mcp.example.test/mcp",
        )
        create_http_client.assert_called_once_with(
            headers={
                "Authorization": "Bearer access-token",
                "MCP-Protocol-Version": "2025-11-25",
            }
        )
        create_transport.assert_called_once_with(
            url="https://mcp.example.test/mcp",
            http_client=http_client,
        )
        session.initialize.assert_awaited_once()
        await manager._server_stacks["remote"].aclose()

    @pytest.mark.asyncio
    async def test_connect_server_failure_marks_unavailable(self):
        """_connect_server should mark connection unavailable on error."""
        manager = MCPClientManager()

        with patch("src.app.core.mcp_client.stdio_client") as mock_stdio:
            mock_stdio.side_effect = RuntimeError("cannot start subprocess")

            await manager._connect_server("broken-server", {"command": "bad", "args": []})

        conn = manager._servers["broken-server"]
        assert conn.available is False
        assert "cannot start subprocess" in conn.error
        # Failed server should not have a stack stored
        assert "broken-server" not in manager._server_stacks

    @pytest.mark.asyncio
    async def test_connect_server_records_circuit_breaker_failure(self):
        """_connect_server should record failure on the circuit breaker."""
        manager = MCPClientManager()

        with patch("src.app.core.mcp_client.stdio_client") as mock_stdio:
            mock_stdio.side_effect = RuntimeError("cannot start")

            await manager._connect_server("failing", {"command": "bad", "args": []})

        conn = manager._servers["failing"]
        assert conn.available is False
        breaker = manager._breakers["failing"]
        assert breaker._failure_count == 1


# ---------------------------------------------------------------------------
# MCPClientManager — _reconnect_server()
# ---------------------------------------------------------------------------


class TestReconnectServer:
    """Test reconnect behavior and guard rails."""

    @pytest.mark.asyncio
    async def test_reconnect_blocked_by_circuit_breaker(self):
        manager = MCPClientManager()
        breaker = ServerCircuitBreaker(fail_max=1, reset_timeout_seconds=60.0)
        breaker.record_failure()
        manager._breakers["broken"] = breaker
        manager._server_configs["broken"] = {"command": "echo", "args": []}

        with patch("src.app.core.mcp_client.logger.info") as mock_log_info:
            result = await manager._reconnect_server("broken")

        assert result is False
        mock_log_info.assert_any_call("mcp_reconnect_blocked_by_breaker", server="broken")

    @pytest.mark.asyncio
    async def test_reconnect_missing_config(self):
        manager = MCPClientManager()

        with patch("src.app.core.mcp_client.logger.error") as mock_log_error:
            result = await manager._reconnect_server("missing")

        assert result is False
        mock_log_error.assert_any_call("mcp_no_config_for_reconnect", server="missing")

    @pytest.mark.asyncio
    async def test_reconnect_cleans_up_old_stack_and_succeeds(self):
        manager = MCPClientManager()
        old_stack = AsyncMock()
        manager._server_stacks["server"] = old_stack
        manager._server_configs["server"] = {"command": "echo", "args": []}

        async def fake_connect_server(name, config):
            from mcp.client.stdio import StdioServerParameters

            from src.app.core.mcp_client import ServerConnection

            conn = ServerConnection(
                name=name,
                params=StdioServerParameters(
                    command=config["command"], args=config.get("args", [])
                ),
            )
            conn.available = True
            manager._servers[name] = conn

        with patch.object(manager, "_connect_server", side_effect=fake_connect_server):
            result = await manager._reconnect_server("server")

        assert result is True
        old_stack.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reconnect_logs_cleanup_failure_but_continues(self):
        manager = MCPClientManager()
        old_stack = AsyncMock()
        old_stack.aclose.side_effect = RuntimeError("cleanup failed")
        manager._server_stacks["server"] = old_stack
        manager._server_configs["server"] = {"command": "echo", "args": []}

        async def fake_connect_server(name, config):
            from mcp.client.stdio import StdioServerParameters

            from src.app.core.mcp_client import ServerConnection

            conn = ServerConnection(
                name=name,
                params=StdioServerParameters(
                    command=config["command"], args=config.get("args", [])
                ),
            )
            conn.available = True
            manager._servers[name] = conn

        with (
            patch.object(manager, "_connect_server", side_effect=fake_connect_server),
            patch("src.app.core.mcp_client.logger.warning") as mock_log_warning,
        ):
            result = await manager._reconnect_server("server")

        assert result is True
        mock_log_warning.assert_any_call(
            "mcp_old_stack_cleanup_failed",
            server="server",
            error="cleanup failed",
        )


# ---------------------------------------------------------------------------
# MCPClientManager — call_tool with None arguments
# ---------------------------------------------------------------------------


class TestCallToolEdgeCases:
    """Edge cases for call_tool."""

    @pytest.mark.asyncio
    async def test_call_tool_with_none_arguments(self):
        """call_tool should pass None arguments correctly."""
        import asyncio

        manager = MCPClientManager()

        mock_text_block = MagicMock()
        mock_text_block.model_dump.return_value = {"type": "text", "text": "ok"}

        mock_result = MagicMock()
        mock_result.content = [mock_text_block]
        mock_result.is_error = False
        mock_result.structured_content = None

        mock_session = AsyncMock()
        mock_session.call_tool.return_value = mock_result

        conn = MagicMock()
        conn.available = True
        conn.session = mock_session
        conn.error = None
        manager._servers["test"] = conn
        manager._locks["test"] = asyncio.Lock()

        result = await manager.call_tool("test", "my_tool", None)
        assert result["is_error"] is False
        mock_session.call_tool.assert_called_once_with("my_tool", None)

    @pytest.mark.asyncio
    async def test_unavailable_server_no_error_message(self):
        """call_tool should handle unavailable server with no error message."""
        import asyncio

        manager = MCPClientManager()

        conn = MagicMock()
        conn.available = False
        conn.session = None
        conn.error = None
        manager._servers["down"] = conn
        manager._locks["down"] = asyncio.Lock()

        # Reconnect also fails
        with (
            patch.object(manager, "_reconnect_server", new_callable=AsyncMock, return_value=False),
            pytest.raises(MCPError, match="not available"),
        ):
            await manager.call_tool("down", "tool", {})


# ---------------------------------------------------------------------------
# _session_context
# ---------------------------------------------------------------------------


class TestSessionContext:
    """Test the _session_context async context manager."""

    @pytest.mark.asyncio
    async def test_session_context_creates_and_yields_session(self):
        """_session_context should create a ClientSession, enter it, and yield it."""
        from src.app.core.mcp_client import _session_context

        mock_session_instance = AsyncMock()
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock(return_value=False)

        mock_read = MagicMock()
        mock_write = MagicMock()

        with patch("src.app.core.mcp_client.ClientSession", return_value=mock_session_instance):
            async with _session_context(mock_read, mock_write) as session:
                assert session is mock_session_instance

        mock_session_instance.__aenter__.assert_awaited_once()
        mock_session_instance.__aexit__.assert_awaited_once()
