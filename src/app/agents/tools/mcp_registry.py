"""MCP registry verification + trust pinning.

Implements three hardening layers:

1. **Registry verification** (P6.7): resolves each server against the public
   MCP registry at ``registry.modelcontextprotocol.io`` on connect. Stores the
   last-known-good publisher identity per server under ``data/mcp_trust/`` and
   refuses to start the server if the publisher has changed since the last
   successful connect (rug-pull / squatted-namespace defence).

2. **Tool-description hash pinning** (P6.8): sha256-hashes each tool's
   ``description`` field on first connect and compares on reconnect. Changed
   descriptions are quarantined pending user approval via Telegram — tool
   calls in the meantime return a synthetic "blocked" error.

3. **Approval queue**: changed descriptions live in ``pending_approvals`` until
   the user approves, rejects, or blocks the server.

Soft-fail policy:
- Registry unreachable (timeout, non-2xx, DNS error) → warn and fall back to
  cached trust entry if one exists. Never crash startup on transient network.
- Registry reachable but server not listed → warn + ``in_registry=False`` in
  cache entry. We still trust the server on first run but note the gap.

The local trust store lives at ``data/mcp_trust/<server>.json``. ``data/`` is
already gitignored so secrets (publisher identities are not secrets but keep
them out of history anyway) stay local.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Paths + constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TRUST_DIR = _PROJECT_ROOT / "data" / "mcp_trust"
REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0/servers"
REGISTRY_TIMEOUT_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Trust store dataclass
# ---------------------------------------------------------------------------


@dataclass
class TrustEntry:
    """The trust record for one MCP server, persisted to disk."""

    server_name: str
    publisher_id: str = ""
    publisher_name: str = ""
    server_version: str = ""
    in_registry: bool = False
    last_verified_utc: str = ""
    # Tool -> sha256 of description at last approved version
    tool_description_hashes: dict[str, str] = field(default_factory=dict)
    # Tool -> {"old_hash", "new_hash", "old_description", "new_description",
    # "detected_utc"} for tools quarantined pending approval
    pending_approvals: dict[str, dict[str, str]] = field(default_factory=dict)
    # If True, the user explicitly blocked the server after a drift event.
    blocked: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "publisher_id": self.publisher_id,
            "publisher_name": self.publisher_name,
            "server_version": self.server_version,
            "in_registry": self.in_registry,
            "last_verified_utc": self.last_verified_utc,
            "tool_description_hashes": dict(self.tool_description_hashes),
            "pending_approvals": dict(self.pending_approvals),
            "blocked": self.blocked,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TrustEntry:
        return cls(
            server_name=str(data.get("server_name", "")),
            publisher_id=str(data.get("publisher_id", "")),
            publisher_name=str(data.get("publisher_name", "")),
            server_version=str(data.get("server_version", "")),
            in_registry=bool(data.get("in_registry", False)),
            last_verified_utc=str(data.get("last_verified_utc", "")),
            tool_description_hashes=dict(data.get("tool_description_hashes") or {}),
            pending_approvals=dict(data.get("pending_approvals") or {}),
            blocked=bool(data.get("blocked", False)),
        )


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class PublisherChangedError(RuntimeError):
    """Raised when a server's publisher identity has silently changed."""

    def __init__(self, server_name: str, old_publisher: str, new_publisher: str) -> None:
        self.server_name = server_name
        self.old_publisher = old_publisher
        self.new_publisher = new_publisher
        super().__init__(
            f"Publisher for MCP server '{server_name}' changed from "
            f"'{old_publisher}' to '{new_publisher}' — refusing to connect."
        )


class ServerBlockedError(RuntimeError):
    """Raised when a server has been explicitly blocked after a drift event."""


# ---------------------------------------------------------------------------
# Trust store helpers
# ---------------------------------------------------------------------------


class TrustStore:
    """On-disk trust cache rooted at ``data/mcp_trust/``."""

    def __init__(self, trust_dir: Path | None = None) -> None:
        self.trust_dir = trust_dir or DEFAULT_TRUST_DIR
        self.trust_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, server_name: str) -> Path:
        # Keep filenames filesystem-safe
        safe = server_name.replace("/", "_").replace("..", "_")
        return self.trust_dir / f"{safe}.json"

    def load(self, server_name: str) -> TrustEntry | None:
        path = self._path(server_name)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "mcp_trust_load_failed",
                server=server_name,
                error=str(exc),
            )
            return None
        return TrustEntry.from_json(data)

    def save(self, entry: TrustEntry) -> None:
        path = self._path(entry.server_name)
        path.write_text(json.dumps(entry.to_json(), indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Registry client
# ---------------------------------------------------------------------------


def _registry_identity(server_json: dict[str, Any]) -> tuple[str, str, str]:
    """Extract (publisher_id, publisher_name, version) from a registry entry.

    The MCP registry ``server.json`` schema (v0) puts the publisher under a
    few possible locations depending on packaging (npm/pypi/oci). We prefer
    stable identifiers.
    """
    publisher = server_json.get("publisher") or {}
    if isinstance(publisher, dict):
        pub_id = str(
            publisher.get("id") or publisher.get("identifier") or publisher.get("name", "")
        )
        pub_name = str(publisher.get("name", pub_id))
    else:
        pub_id = str(publisher)
        pub_name = pub_id
    version = str(server_json.get("version", ""))
    return pub_id, pub_name, version


async def fetch_registry_entry(
    server_name: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any] | None:
    """Look up ``server_name`` in the public MCP registry.

    Returns the first matching ``server.json`` dict, or ``None`` on any
    network error / non-2xx response (soft-fail).
    """
    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=REGISTRY_TIMEOUT_SECONDS)
        close_client = True
    try:
        resp = await client.get(REGISTRY_URL, params={"name": server_name})
        if resp.status_code != 200:
            logger.warning(
                "mcp_registry_non_200",
                server=server_name,
                status=resp.status_code,
            )
            return None
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "mcp_registry_unreachable",
            server=server_name,
            error=str(exc),
        )
        return None
    finally:
        if close_client:
            await client.aclose()

    # Spec response shape: {"servers": [server.json, ...]} — but accept a flat
    # list as well for robustness against the v0 variance.
    entries: list[dict[str, Any]] = []
    if isinstance(body, dict):
        raw = body.get("servers")
        if isinstance(raw, list):
            entries = [e for e in raw if isinstance(e, dict)]
    elif isinstance(body, list):
        entries = [e for e in body if isinstance(e, dict)]

    if not entries:
        logger.warning("mcp_registry_no_match", server=server_name)
        return None
    # Registry returns multiple results for a name prefix search; pick exact.
    for entry in entries:
        if str(entry.get("name", "")) == server_name:
            return entry
    return entries[0]


# ---------------------------------------------------------------------------
# Verification + hash pinning
# ---------------------------------------------------------------------------


def hash_description(description: str | None) -> str:
    """sha256 of a tool description, stable for None/empty."""
    data = (description or "").encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass
class VerificationResult:
    """Outcome of :func:`verify_server_publisher`."""

    allow_connect: bool
    publisher_changed: bool = False
    first_run: bool = False
    cached_fallback: bool = False
    in_registry: bool = False
    entry: TrustEntry | None = None
    old_publisher: str = ""
    new_publisher: str = ""


async def verify_server_publisher(
    server_name: str,
    *,
    trust_store: TrustStore,
    http_client: httpx.AsyncClient | None = None,
) -> VerificationResult:
    """Verify ``server_name`` against the registry and the local trust cache.

    Returns a :class:`VerificationResult` describing whether the server should
    be allowed to start. Callers must:
    - refuse to connect when ``allow_connect`` is False
    - fire a Telegram alert when ``publisher_changed`` is True
    - persist the updated entry via :meth:`TrustStore.save` on success
    """
    cached = trust_store.load(server_name)

    if cached and cached.blocked:
        logger.error(
            "mcp_server_blocked_by_user",
            server=server_name,
        )
        return VerificationResult(
            allow_connect=False,
            entry=cached,
        )

    registry_entry = await fetch_registry_entry(server_name, client=http_client)

    if registry_entry is None:
        # Soft-fail: registry unreachable or no match.
        if cached is not None:
            logger.warning(
                "mcp_registry_soft_fail_using_cache",
                server=server_name,
                cached_publisher=cached.publisher_id,
            )
            return VerificationResult(
                allow_connect=True,
                cached_fallback=True,
                entry=cached,
            )
        logger.warning(
            "mcp_registry_soft_fail_first_run",
            server=server_name,
        )
        # First run with no registry info — bootstrap a trust entry.
        return VerificationResult(
            allow_connect=True,
            first_run=True,
            entry=TrustEntry(
                server_name=server_name,
                last_verified_utc=datetime.now(UTC).isoformat(),
            ),
        )

    pub_id, pub_name, version = _registry_identity(registry_entry)
    logger.info(
        "mcp_registry_resolved",
        server=server_name,
        publisher_id=pub_id,
        publisher_name=pub_name,
        version=version,
    )

    if cached is None:
        # Bootstrap: first time we've seen this server. Trust-on-first-use.
        entry = TrustEntry(
            server_name=server_name,
            publisher_id=pub_id,
            publisher_name=pub_name,
            server_version=version,
            in_registry=True,
            last_verified_utc=datetime.now(UTC).isoformat(),
        )
        return VerificationResult(
            allow_connect=True,
            first_run=True,
            in_registry=True,
            entry=entry,
        )

    # Existing cache — compare publisher identities.
    if cached.publisher_id and pub_id and cached.publisher_id != pub_id:
        logger.error(
            "mcp_server_publisher_changed",
            server=server_name,
            old_publisher=cached.publisher_id,
            new_publisher=pub_id,
        )
        return VerificationResult(
            allow_connect=False,
            publisher_changed=True,
            in_registry=True,
            entry=cached,
            old_publisher=cached.publisher_id,
            new_publisher=pub_id,
        )

    # Identity matches (or cache had no publisher — bootstrap case). Update
    # version + last_verified on success, keep tool hashes.
    cached.publisher_id = pub_id or cached.publisher_id
    cached.publisher_name = pub_name or cached.publisher_name
    cached.server_version = version or cached.server_version
    cached.in_registry = True
    cached.last_verified_utc = datetime.now(UTC).isoformat()
    return VerificationResult(
        allow_connect=True,
        in_registry=True,
        entry=cached,
    )


# ---------------------------------------------------------------------------
# Tool description hash pinning
# ---------------------------------------------------------------------------


@dataclass
class HashPinningResult:
    """Outcome of :func:`check_tool_description_hashes`."""

    changed_tools: dict[str, dict[str, str]] = field(default_factory=dict)
    new_tools: list[str] = field(default_factory=list)
    unchanged_tools: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.changed_tools)


def check_tool_description_hashes(
    server_name: str,
    tools: list[dict[str, Any]],
    *,
    entry: TrustEntry,
) -> HashPinningResult:
    """Compute sha256s of each tool's description and diff against the cache.

    Args:
        server_name: The server we're connecting to.
        tools: List of ``{"name": ..., "description": ...}`` dicts from the
            server. (We accept the dict form so MCP ``Tool`` pydantic objects
            and raw dicts both work; callers normalise.)
        entry: The trust entry loaded for this server. Mutated in place —
            new tools get hashed, changed tools move into ``pending_approvals``.

    Returns:
        :class:`HashPinningResult` describing which tools changed, are new, or
        are unchanged. Callers should fire a Telegram approval alert when
        ``has_changes`` is True.
    """
    result = HashPinningResult()
    detected_utc = datetime.now(UTC).isoformat()

    for tool in tools:
        name = str(tool.get("name", "")).strip()
        if not name:
            continue
        description = str(tool.get("description") or "")
        new_hash = hash_description(description)

        old_hash = entry.tool_description_hashes.get(name)
        if old_hash is None:
            # First time we see this tool — trust and pin.
            entry.tool_description_hashes[name] = new_hash
            result.new_tools.append(name)
            logger.info(
                "mcp_tool_hash_pinned",
                server=server_name,
                tool=name,
                hash=new_hash[:12],
            )
            continue

        if old_hash == new_hash:
            result.unchanged_tools.append(name)
            continue

        # Drift detected — quarantine until user approves.
        entry.pending_approvals[name] = {
            "old_hash": old_hash,
            "new_hash": new_hash,
            "new_description": description,
            "detected_utc": detected_utc,
        }
        result.changed_tools[name] = entry.pending_approvals[name]
        logger.error(
            "mcp_tool_description_changed",
            server=server_name,
            tool=name,
            old_hash=old_hash[:12],
            new_hash=new_hash[:12],
        )

    return result


# ---------------------------------------------------------------------------
# Approval lifecycle
# ---------------------------------------------------------------------------


def approve_pending_tool(entry: TrustEntry, tool_name: str) -> bool:
    """Approve a quarantined tool description — promote the new hash."""
    pending = entry.pending_approvals.pop(tool_name, None)
    if pending is None:
        return False
    entry.tool_description_hashes[tool_name] = pending["new_hash"]
    return True


def reject_pending_tool(entry: TrustEntry, tool_name: str) -> bool:
    """Reject the new description — keep the old hash, leave tool blocked
    (future calls still fail until a reject means restore old description)."""
    return entry.pending_approvals.pop(tool_name, None) is not None


def block_server(entry: TrustEntry) -> None:
    """Mark a whole server blocked — no future connects allowed."""
    entry.blocked = True


def is_tool_pending(entry: TrustEntry, tool_name: str) -> bool:
    """Whether a call to ``tool_name`` is currently quarantined."""
    return tool_name in entry.pending_approvals


# ---------------------------------------------------------------------------
# Alert text formatters
# ---------------------------------------------------------------------------


def format_publisher_changed_alert(
    server_name: str,
    old_publisher: str,
    new_publisher: str,
) -> str:
    """Human-readable Telegram body for a publisher-change event."""
    return (
        "MCP security alert\n\n"
        f"Server '{server_name}' refused to start.\n"
        f"Publisher identity changed since last run:\n"
        f"  old: {old_publisher or '<unknown>'}\n"
        f"  new: {new_publisher or '<unknown>'}\n\n"
        "This looks like a rug-pull or a squatted namespace. The server will "
        "stay blocked until you manually re-approve it in data/mcp_trust/."
    )


def format_tool_description_changed_alert(
    server_name: str,
    changed: dict[str, dict[str, str]],
    old_descriptions: dict[str, str] | None = None,
) -> str:
    """Human-readable Telegram body for a tool-description drift event."""
    old_descriptions = old_descriptions or {}
    lines: list[str] = ["MCP tool description changed"]
    for tool_name, info in changed.items():
        lines.append(f"\n  {server_name}.{tool_name}")
        old_desc = old_descriptions.get(tool_name, "<cached hash only>")
        new_desc = info.get("new_description", "")
        lines.append(f"  Old: {_truncate(old_desc, 120)}")
        lines.append(f"  New: {_truncate(new_desc, 120)}")
    lines.append("\n[Approve new] [Reject — keep old description] [Block server]")
    return "\n".join(lines)


def _truncate(text: str, limit: int) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "..."
