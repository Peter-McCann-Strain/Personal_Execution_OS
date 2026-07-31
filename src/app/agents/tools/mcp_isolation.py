"""Content isolation and destination allowlist for MCP tool results.

Implements P6.9 + P6.10:

- **Content isolation** (P6.9): wraps every tool result before it enters an
  LLM prompt with :func:`build_untrusted_external_prompt` so injection
  attempts in scraped content cannot be mistaken for instructions. Also
  surfaces ``safety_flags`` (e.g. ``instruction_like_content``) for logging.

- **Destination allowlist** (P6.10): for fetching tools (search, navigate,
  etc.) the caller supplies a per-tool list of allowed destination hosts.
  Calls with a host not on the list short-circuit with a synthetic error.

The allowlist is deliberately dumb — suffix + wildcard matching only. We
treat ``*`` as "any host", ``*.example.com`` as "example.com and subdomains",
and bare hostnames as exact matches. The goal is reducing blast radius, not
being a WAF.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any

import structlog

from src.app.core.security import (
    UntrustedExternalItem,
    UntrustedExternalPrompt,
    build_untrusted_external_prompt,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Content isolation
# ---------------------------------------------------------------------------


def wrap_tool_result_for_llm(
    server_name: str,
    tool_name: str,
    content: str | list[dict[str, Any]],
    *,
    source_id: str | None = None,
    url: str | None = None,
) -> UntrustedExternalPrompt:
    """Wrap a tool result in the untrusted-external envelope.

    Callers should use the resulting ``rendered_text`` in place of the raw
    content when building the next LLM message, and surface
    ``safety_flags`` in structured logs.

    String content is wrapped as a single item. List-of-blocks content is
    flattened to text blocks only — image/resource blocks are surfaced as a
    note because we don't apply injection heuristics to binary data.
    """
    items: list[UntrustedExternalItem] = []

    if isinstance(content, str):
        items.append(
            UntrustedExternalItem(
                text=content,
                source_type=f"mcp_tool:{server_name}__{tool_name}",
                source_id=source_id,
                url=url,
            )
        )
    else:
        for block in content:
            block_type = str(block.get("type", "text"))
            if block_type == "text":
                items.append(
                    UntrustedExternalItem(
                        text=str(block.get("text", "")),
                        source_type=f"mcp_tool:{server_name}__{tool_name}",
                        source_id=source_id,
                        url=url,
                    )
                )
            else:
                # Non-text block — include as an opaque note so the LLM knows
                # something was returned but cannot be tricked by injected
                # text inside e.g. a base64 image payload.
                items.append(
                    UntrustedExternalItem(
                        text=f"<non-text content: type={block_type}>",
                        source_type=f"mcp_tool:{server_name}__{tool_name}:{block_type}",
                        source_id=source_id,
                        url=url,
                    )
                )

    return build_untrusted_external_prompt(
        items,
        container_tag="mcp_tool_result",
    )


# ---------------------------------------------------------------------------
# Destination allowlist
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class AllowlistDecision:
    """Result of an allowlist check — ``allowed`` is the only authoritative bit."""

    allowed: bool
    reason: str = ""
    host: str = ""
    matched_pattern: str = ""


def _extract_host(destination: str) -> str:
    """Return the hostname component of ``destination``.

    Accepts bare hostnames (``example.com``) and full URLs
    (``https://example.com/path``). Lowercased, no port.
    """
    candidate = destination.strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = "https://" + candidate
    try:
        parsed = urllib.parse.urlparse(candidate)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    return host


def _pattern_matches(host: str, pattern: str) -> bool:
    """True if ``host`` satisfies ``pattern``.

    Supported patterns:
      - ``*``              → matches any host
      - ``*.example.com``  → matches ``example.com`` and any subdomain
      - ``example.com``    → exact match only
    """
    pattern = pattern.strip().lower()
    if not pattern:
        return False
    if pattern == "*":
        return True
    if pattern.startswith("*."):
        suffix = pattern[2:]
        return host == suffix or host.endswith("." + suffix)
    return host == pattern


def check_destination_allowlist(
    tool_name: str,
    destination: str,
    allowlist: dict[str, list[str]] | None,
) -> AllowlistDecision:
    """Check whether ``tool_name`` is permitted to hit ``destination``.

    Args:
        tool_name: The namespaced or bare tool name (caller may pass either).
        destination: URL or hostname the tool intends to reach.
        allowlist: Mapping of tool name to list of allowed host patterns.
            If the tool name is absent from the mapping, the check passes
            (an opt-in allowlist — only fetching tools need to be listed).
            If the tool is present but the destination matches nothing, the
            check fails.

    Returns:
        :class:`AllowlistDecision`.
    """
    if not allowlist:
        return AllowlistDecision(allowed=True, reason="no_allowlist_configured")

    patterns = allowlist.get(tool_name)
    if patterns is None:
        # Tool not fetching — no allowlist required.
        return AllowlistDecision(allowed=True, reason="tool_not_fetching")

    host = _extract_host(destination)
    if not host:
        return AllowlistDecision(
            allowed=False,
            reason="unparseable_destination",
            host="",
        )

    for pattern in patterns:
        if _pattern_matches(host, pattern):
            return AllowlistDecision(
                allowed=True,
                reason="matched",
                host=host,
                matched_pattern=pattern,
            )

    logger.warning(
        "mcp_destination_blocked",
        tool=tool_name,
        host=host,
        patterns=patterns,
    )
    return AllowlistDecision(
        allowed=False,
        reason="destination_not_on_allowlist",
        host=host,
    )


def extract_destination_from_arguments(
    tool_name: str,
    arguments: dict[str, Any] | None,
) -> str:
    """Best-effort extract the URL/host from a fetching tool's arguments.

    Different MCP fetching tools use different argument names. We look for
    the common ones in priority order: ``url``, ``uri``, ``target``,
    ``destination``, ``site``, ``domain``.

    Tavily-style search tools don't pass a URL; they pass a query and fan
    out to many domains. Those should be allowlisted as ``"*"`` — this
    helper returns an empty string for them.
    """
    if not arguments:
        return ""

    for key in ("url", "uri", "target", "destination", "site", "domain"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def build_blocked_tool_result(
    tool_use_id: str,
    reason: str,
    *,
    idempotency_key: str | None = None,
    argument_hash: str | None = None,
) -> dict[str, Any]:
    """Synthetic tool_result dict for a call blocked by our guards."""
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": f"Tool call blocked: {reason}",
        "is_error": True,
        "idempotency_key": idempotency_key or "",
        "argument_hash": argument_hash or "",
    }
