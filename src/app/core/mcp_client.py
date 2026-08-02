"""Low-level MCP client manager for reviewed, operator-managed integrations.

The public release configures no MCP server. This module does not install,
download, or select one. A private deployment that calls it directly is
responsible for supplying an already-installed, version-pinned server and an
appropriate security hook.

Resilience features:
- Per-server AsyncExitStack so one server can be torn down without affecting others
- Circuit breaker per server to avoid hammering crashed/unresponsive processes
- Lazy reconnect on first connection-class failure (timeout, broken pipe, EOF, etc.)
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.app.core.exceptions import MCPError
from src.app.core.tool_contracts import build_tool_specs
from src.app.domain.models import ToolSpec

# Security hook signature: given (server_name, tool_dicts), return True to
# allow the server to come online, False to block. The hook owns its own
# side effects (trust store writes, Telegram alerts, logging).
SecurityHook = Callable[[str, list[dict[str, Any]]], Awaitable[bool]]

try:
    from mcp import ClientSession, Tool
    from mcp.client.stdio import StdioServerParameters, stdio_client

    MCP_AVAILABLE = True
except ImportError:  # pragma: no cover
    MCP_AVAILABLE = False

try:
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    STREAMABLE_HTTP_AVAILABLE = True
except ImportError:  # pragma: no cover
    STREAMABLE_HTTP_AVAILABLE = False

# Optional OAuth client injection — the manager only constructs one lazily
# when a remote server is configured. See src.app.agents.tools.mcp_oauth.
_OAuthClient = Any

logger = structlog.get_logger()

# Exception types that indicate a broken transport rather than a tool-level error.
_CONNECTION_ERRORS = (
    asyncio.TimeoutError,
    BrokenPipeError,
    EOFError,
    ConnectionError,
    OSError,
)


@dataclass
class ServerCircuitBreaker:
    """Per-server circuit breaker to avoid hammering crashed servers."""

    fail_max: int = 3
    reset_timeout_seconds: float = 60.0
    _failure_count: int = field(default=0, init=False, repr=False)
    _last_failure: float | None = field(default=None, init=False, repr=False)
    _state: str = field(default="closed", init=False, repr=False)

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure = time.monotonic()
        if self._failure_count >= self.fail_max:
            self._state = "open"

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "closed"

    @property
    def allow_request(self) -> bool:
        if self._state == "closed":
            return True
        if (
            self._state == "open"
            and self._last_failure is not None
            and time.monotonic() - self._last_failure > self.reset_timeout_seconds
        ):
            self._state = "half-open"
            return True
        return self._state == "half-open"


@dataclass
class ServerConnection:
    """Tracks the state of a single MCP server connection."""

    name: str
    # stdio servers carry StdioServerParameters; remote (streamable-http)
    # servers carry None because the transport is constructed from the raw
    # config dict at connect time.
    params: StdioServerParameters | None = None
    transport: str = "stdio"
    session: ClientSession | None = None
    tools: list[Tool] = field(default_factory=list)
    available: bool = False
    error: str | None = None


class MCPClientManager:
    """Manages connections to multiple MCP servers.

    Lifecycle:
        manager = MCPClientManager()
        await manager.connect(server_configs)
        tools = manager.get_tools_for_claude()
        result = await manager.call_tool("server-name", "tool-name", {"arg": "val"})
        await manager.disconnect()

    Thread-safe for concurrent async usage — each server has its own session
    and calls are serialised per-server via asyncio.Lock.

    Resilience:
        - Each server gets its own AsyncExitStack so a single crash doesn't
          tear down the whole manager.
        - A per-server circuit breaker prevents reconnect storms.
        - call_tool() attempts one lazy reconnect on connection-class errors.
    """

    def __init__(
        self,
        *,
        security_hook: SecurityHook | None = None,
        oauth_client: Any | None = None,
    ) -> None:
        if not MCP_AVAILABLE:
            raise MCPError(
                "The 'mcp' package is not installed. Install it with: pip install 'mcp>=1.0'"
            )
        self._servers: dict[str, ServerConnection] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._server_stacks: dict[str, AsyncExitStack] = {}
        self._server_configs: dict[str, dict[str, Any]] = {}
        self._breakers: dict[str, ServerCircuitBreaker] = {}
        self._connected = False
        # Optional security hook (registry + hash pinning). Called after tool
        # discovery, before the server is marked available. See mcp_registry
        # and mcp_isolation modules.
        self._security_hook = security_hook
        # Optional OAuth client (src.app.agents.tools.mcp_oauth.OAuthClient).
        # Required when any configured server uses transport="streamable-http".
        # Injected here so tests can mock token acquisition cleanly.
        self._oauth_client = oauth_client
        # Per-server set of tool names that are currently quarantined pending
        # user approval (P6.8). Tool calls consult this before dispatching.
        self._quarantined_tools: dict[str, set[str]] = {}

    @property
    def connected(self) -> bool:
        """Whether the manager has active connections."""
        return self._connected

    async def connect(self, server_configs: dict[str, dict[str, Any]]) -> None:
        """Connect to all configured MCP servers.

        Args:
            server_configs: Mapping of server name to config dict. Each config must
                contain 'command' and 'args', and optionally 'env' and 'cwd'.
                Example::

                    {
                        "reviewed-server": {
                            "command": "/opt/personal-execution-os/bin/reviewed-server",
                            "args": ["--locked-config", "/etc/reviewed-server.json"],
                            "env": {},
                        }
                    }

                Package runners and mutable network installs are not supported.
                Install and verify an exact server artifact before configuring
                it here.

        Servers that fail to connect are logged and marked unavailable — they do
        not prevent other servers from starting.
        """
        if self._connected:
            logger.warning("mcp_already_connected", msg="Disconnecting before reconnecting")
            await self.disconnect()

        self._server_configs = server_configs.copy()

        # Keep connection lifecycle in a single task so the anyio-backed session
        # contexts can be closed cleanly on shutdown.
        for name, config in server_configs.items():
            try:
                await self._connect_server(name, config)
            except Exception as exc:
                logger.warning(
                    "mcp_server_connect_task_failed",
                    server=name,
                    error=str(exc),
                )

        self._connected = True
        server_status = self.get_server_status()
        available = [name for name, status in server_status.items() if status["available"]]
        unavailable = [name for name, status in server_status.items() if not status["available"]]
        logger.info(
            "mcp_connect_complete",
            available=available,
            unavailable=unavailable,
            total_tools=sum(len(status["tools"]) for status in server_status.values()),
        )

        available_count = sum(1 for c in self._servers.values() if c.available)
        if self._servers and available_count == 0:
            logger.error("mcp_all_servers_failed", total=len(self._servers))

    async def _connect_server(self, name: str, config: dict[str, Any]) -> None:
        """Connect to a single MCP server. Catches all errors."""
        transport_kind = str(config.get("transport", "stdio")).lower()
        if transport_kind == "streamable-http":
            conn = ServerConnection(name=name, transport="streamable-http")
        else:
            params = StdioServerParameters(
                command=config["command"],
                args=config.get("args", []),
                env=config.get("env"),
                cwd=config.get("cwd"),
            )
            conn = ServerConnection(name=name, params=params, transport="stdio")
        self._servers[name] = conn
        self._locks.setdefault(name, asyncio.Lock())

        if name not in self._breakers:
            self._breakers[name] = ServerCircuitBreaker()
        breaker = self._breakers[name]

        stack = AsyncExitStack()
        await stack.__aenter__()

        try:
            if transport_kind == "streamable-http":
                if not STREAMABLE_HTTP_AVAILABLE:
                    raise MCPError(
                        "The installed mcp package does not support "
                        "streamable-http transport; upgrade mcp>=1.4"
                    )
                resource_uri = str(config.get("resource_uri") or config.get("url", ""))
                if not resource_uri:
                    raise MCPError(
                        f"Remote MCP server '{name}' must declare 'url' or 'resource_uri'"
                    )
                if self._oauth_client is None:
                    raise MCPError(
                        f"Remote MCP server '{name}' requires an OAuthClient "
                        "(instantiate MCPClientManager with oauth_client=...)"
                    )
                token = await self._oauth_client.acquire_token(name, resource_uri)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "MCP-Protocol-Version": "2025-11-25",
                }
                http_client = await stack.enter_async_context(
                    create_mcp_http_client(headers=headers)
                )
                transport_ctx = streamable_http_client(
                    url=str(config.get("url") or resource_uri),
                    http_client=http_client,
                )
                streams = await stack.enter_async_context(transport_ctx)
                read_stream, write_stream = streams
            else:
                if conn.params is None:
                    raise MCPError(f"MCP stdio server '{name}' is missing spawn parameters")
                transport = stdio_client(conn.params)
                read_stream, write_stream = await stack.enter_async_context(transport)

            session = await stack.enter_async_context(_session_context(read_stream, write_stream))
            await session.initialize()

            # Discover tools
            tools_result = await session.list_tools()
            discovered = list(tools_result.tools)

            # Security hook (registry verification + hash pinning). If the
            # hook refuses the server, tear down without marking available.
            if self._security_hook is not None:
                tool_dicts = [
                    {"name": t.name, "description": t.description or ""} for t in discovered
                ]
                approved = await self._security_hook(name, tool_dicts)
                if not approved:
                    conn.available = False
                    conn.error = "blocked by security hook"
                    breaker.record_failure()
                    with suppress(BaseException):
                        await stack.aclose()
                    logger.error(
                        "mcp_server_blocked_by_security_hook",
                        server=name,
                    )
                    return

            conn.session = session
            conn.tools = discovered
            conn.available = True
            self._server_stacks[name] = stack

            breaker.record_success()

            logger.info(
                "mcp_server_connected",
                server=name,
                tools=[t.name for t in conn.tools],
            )
        except Exception as exc:
            conn.available = False
            conn.error = str(exc)
            breaker.record_failure()

            # Clean up this server's stack only
            with suppress(BaseException):
                await stack.aclose()

            logger.warning(
                "mcp_server_connect_failed",
                server=name,
                error=str(exc),
            )

    async def _reconnect_server(self, name: str) -> bool:
        """Tear down a failed server and attempt reconnection. Returns True on success."""
        breaker = self._breakers.get(name)
        if breaker and not breaker.allow_request:
            logger.info("mcp_reconnect_blocked_by_breaker", server=name)
            return False

        # Tear down old stack for this server only
        old_stack = self._server_stacks.pop(name, None)
        if old_stack is not None:
            try:
                await old_stack.aclose()
            except BaseException as exc:
                logger.warning("mcp_old_stack_cleanup_failed", server=name, error=str(exc))

        config = self._server_configs.get(name)
        if config is None:
            logger.error("mcp_no_config_for_reconnect", server=name)
            return False

        await self._connect_server(name, config)
        conn = self._servers.get(name)
        return conn is not None and conn.available

    async def disconnect(self) -> None:
        """Cleanly shut down all MCP server connections."""
        for name, stack in list(self._server_stacks.items()):
            try:
                await stack.aclose()
            except BaseException as exc:
                logger.warning("mcp_disconnect_error", server=name, error=str(exc))
        self._server_stacks.clear()
        self._servers.clear()
        self._locks.clear()
        self._breakers.clear()
        self._server_configs.clear()
        self._connected = False
        logger.info("mcp_disconnected")

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools across all connected servers.

        Returns a list of dicts with server_name, tool_name, description,
        and input_schema for each tool.
        """
        all_tools: list[dict[str, Any]] = []
        for name, conn in self._servers.items():
            if not conn.available:
                continue
            for public_name, tool in self._iter_exposed_tools(name, conn):
                runtime_metadata = self._tool_runtime_metadata(name, public_name, tool.name)
                all_tools.append(
                    {
                        "server_name": name,
                        "tool_name": public_name,
                        "description": tool.description or "",
                        "input_schema": tool.input_schema,
                        "auth_required": runtime_metadata.get("auth_required", False),
                        "roots": runtime_metadata.get("roots", []),
                        "tool_metadata": runtime_metadata.get("metadata", {}),
                    }
                )
        return all_tools

    async def get_tool_specs(self) -> dict[str, ToolSpec]:
        """Return canonical tool specs for all currently exposed tools."""
        tools = await self.list_tools()
        tool_metadata = {
            f"{tool['server_name']}__{tool['tool_name']}": tool.get("tool_metadata") or {}
            for tool in tools
        }
        return build_tool_specs(tools, tool_metadata=tool_metadata)

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a tool call on a specific MCP server.

        Args:
            server_name: Name of the MCP server that owns the tool.
            tool_name: Name of the tool to call.
            arguments: Arguments to pass to the tool.

        Returns:
            Dict with 'content' (list of content blocks) and 'is_error' (bool).

        Raises:
            MCPError: If the server is unavailable or the call fails.

        Resilience:
            On connection-class errors (timeout, broken pipe, EOF, etc.) the
            manager marks the server unavailable and attempts a single lazy
            reconnect + retry before raising.
        """
        conn = self._servers.get(server_name)
        if conn is None:
            raise MCPError(f"Unknown MCP server: {server_name}")

        # Hash-pinning quarantine check (P6.8): if the tool's description
        # drifted since last approval, refuse the call until the user
        # re-approves it via Telegram.
        quarantined = self._quarantined_tools.get(server_name, set())
        if tool_name in quarantined:
            logger.error(
                "mcp_tool_blocked_pending_approval",
                server=server_name,
                tool=tool_name,
            )
            raise MCPError(
                f"Tool '{tool_name}' on server '{server_name}' is blocked "
                "pending approval — description changed since last run."
            )

        # If server is already known-unavailable, try a reconnect before giving up
        if not conn.available or conn.session is None:
            logger.info("mcp_server_unavailable_attempting_reconnect", server=server_name)
            reconnected = await self._reconnect_server(server_name)
            if not reconnected:
                conn = self._servers.get(server_name)
                raise MCPError(
                    f"MCP server '{server_name}' is not available"
                    + (f": {conn.error}" if conn and conn.error else "")
                )
            conn = self._servers[server_name]

        lock = self._locks[server_name]
        async with lock:
            session = conn.session
            if session is None:
                raise MCPError(f"MCP server '{server_name}' has no active session")
            try:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments),
                    timeout=30.0,
                )
            except _CONNECTION_ERRORS as exc:
                # Transport-level failure — mark unavailable and try one reconnect
                logger.warning(
                    "mcp_tool_call_connection_error",
                    server=server_name,
                    tool=tool_name,
                    error=str(exc),
                )
                conn.available = False
                conn.session = None
                conn.error = str(exc)

                reconnected = await self._reconnect_server(server_name)
                if not reconnected:
                    raise MCPError(
                        f"Tool call '{tool_name}' on server '{server_name}' failed "
                        f"and reconnect was unsuccessful: {exc}"
                    ) from exc

                # Retry once after successful reconnect
                conn = self._servers[server_name]
                session = conn.session
                if session is None:
                    raise MCPError(
                        f"MCP server '{server_name}' reconnected without an active session"
                    ) from exc
                try:
                    result = await asyncio.wait_for(
                        session.call_tool(tool_name, arguments),
                        timeout=30.0,
                    )
                except Exception as retry_exc:
                    logger.error(
                        "mcp_tool_call_retry_failed",
                        server=server_name,
                        tool=tool_name,
                        error=str(retry_exc),
                    )
                    raise MCPError(
                        f"Tool call '{tool_name}' on server '{server_name}' failed "
                        f"after reconnect: {retry_exc}"
                    ) from retry_exc
            except Exception as exc:
                logger.error(
                    "mcp_tool_call_failed",
                    server=server_name,
                    tool=tool_name,
                    error=str(exc),
                )
                raise MCPError(
                    f"Tool call '{tool_name}' on server '{server_name}' failed: {exc}"
                ) from exc

        # Convert MCP content blocks to plain dicts
        content_blocks = _serialise_content_blocks(result.content)
        structured_content = result.structured_content
        if not content_blocks and structured_content is not None:
            content_blocks = [
                {
                    "type": "text",
                    "text": json.dumps(structured_content, ensure_ascii=False, default=str),
                }
            ]

        logger.info(
            "mcp_tool_call_complete",
            server=server_name,
            tool=tool_name,
            is_error=result.is_error,
            content_blocks=len(content_blocks),
        )

        return {
            "content": content_blocks,
            "is_error": result.is_error,
            "structured_content": structured_content,
        }

    def get_tools_for_claude(self) -> list[dict[str, Any]]:
        """Convert all available MCP tools to Anthropic tool_use format.

        Returns a list of tool definitions compatible with the Anthropic
        messages API ``tools`` parameter. Tool names are namespaced as
        ``{server_name}__{tool_name}`` to avoid collisions across servers.

        Example output::

            [
                {
                    "name": "tavily-search__search",
                    "description": "Search the web using Tavily.",
                    "input_schema": { "type": "object", "properties": { ... } }
                }
            ]
        """
        tools: list[dict[str, Any]] = []
        for name, conn in self._servers.items():
            if not conn.available:
                continue
            for public_name, tool in self._iter_exposed_tools(name, conn):
                tools.append(
                    {
                        "name": f"{name}__{public_name}",
                        "description": tool.description or "",
                        "input_schema": tool.input_schema,
                    }
                )
        return tools

    def get_server_status(self) -> dict[str, dict[str, Any]]:
        """Return the status of all configured servers.

        Useful for health checks and debugging.
        """
        return {
            name: {
                "available": conn.available,
                "tools": [
                    public_name for public_name, _tool in self._iter_exposed_tools(name, conn)
                ],
                "error": conn.error,
            }
            for name, conn in self._servers.items()
        }

    def quarantine_tool(self, server_name: str, tool_name: str) -> None:
        """Mark ``tool_name`` on ``server_name`` as quarantined pending approval."""
        self._quarantined_tools.setdefault(server_name, set()).add(tool_name)

    def approve_quarantined_tool(self, server_name: str, tool_name: str) -> bool:
        """Remove a tool from quarantine after user approval. Returns True if
        the tool was quarantined."""
        bucket = self._quarantined_tools.get(server_name)
        if not bucket or tool_name not in bucket:
            return False
        bucket.discard(tool_name)
        return True

    def is_tool_quarantined(self, server_name: str, tool_name: str) -> bool:
        """Whether a tool is currently blocked by the hash-pinning guard."""
        return tool_name in self._quarantined_tools.get(server_name, set())

    def resolve_namespaced_tool(self, namespaced_name: str) -> tuple[str, str]:
        """Parse a namespaced tool name into (server_name, tool_name).

        Tool names from get_tools_for_claude() are formatted as
        ``{server_name}__{tool_name}``. This method splits them back.

        Args:
            namespaced_name: e.g. "tavily-search__search"

        Returns:
            Tuple of (server_name, tool_name).

        Raises:
            MCPError: If the name doesn't contain the namespace separator.
        """
        if "__" not in namespaced_name:
            raise MCPError(
                f"Tool name '{namespaced_name}' is not namespaced. "
                "Expected format: 'server-name__tool-name'."
            )
        server_name, tool_name = namespaced_name.split("__", 1)
        server_config = self._server_configs.get(server_name, {})
        exposed_tools = server_config.get("exposed_tools")
        if isinstance(exposed_tools, dict):
            real_tool_name = exposed_tools.get(tool_name)
            if isinstance(real_tool_name, str):
                return server_name, real_tool_name
        return server_name, tool_name

    def _iter_exposed_tools(
        self,
        server_name: str,
        conn: ServerConnection,
    ) -> list[tuple[str, Tool]]:
        """Return the public tool surface for a server."""
        exposed_tools = self._server_configs.get(server_name, {}).get("exposed_tools")
        if not isinstance(exposed_tools, dict):
            return [(tool.name, tool) for tool in conn.tools]

        real_tools = {tool.name: tool for tool in conn.tools}
        public_tools: list[tuple[str, Tool]] = []
        for public_name, real_name in exposed_tools.items():
            tool = real_tools.get(real_name)
            if tool is not None:
                public_tools.append((public_name, tool))
        return public_tools

    def _tool_runtime_metadata(
        self,
        server_name: str,
        public_name: str,
        real_name: str,
    ) -> dict[str, Any]:
        """Return local runtime metadata for one tool exposure."""
        server_config = self._server_configs.get(server_name, {})
        tool_metadata = server_config.get("tool_metadata", {})
        metadata = {}
        if isinstance(tool_metadata, dict):
            candidate = tool_metadata.get(public_name) or tool_metadata.get(real_name)
            if isinstance(candidate, dict):
                metadata = dict(candidate)
        return {
            "auth_required": bool(server_config.get("auth_required", False)),
            "roots": [str(root) for root in server_config.get("roots", [])],
            "metadata": metadata,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _session_context(read_stream: Any, write_stream: Any) -> AsyncIterator[ClientSession]:
    """Create and yield a ClientSession as an async context manager.

    The MCP ClientSession needs to run inside an anyio task group. This
    helper wraps that pattern so the exit stack can manage it.
    """
    session = ClientSession(read_stream, write_stream)
    # ClientSession requires an anyio task group internally. We enter it
    # via its own __aenter__ / __aexit__.
    async with session:
        yield session


def _serialise_content_blocks(blocks: list[Any]) -> list[dict[str, Any]]:
    """Convert MCP content blocks to plain dicts.

    Handles TextContent, ImageContent, AudioContent, EmbeddedResource, and
    any future types by falling back to model_dump().
    """
    result: list[dict[str, Any]] = []
    for block in blocks:
        if hasattr(block, "model_dump"):
            result.append(block.model_dump(exclude_none=True))
        elif hasattr(block, "text"):
            result.append({"type": "text", "text": block.text})
        else:
            # Unknown block type — serialise what we can
            result.append({"type": "unknown", "data": str(block)})
    return result
