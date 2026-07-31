"""Human-in-the-loop (HITL) approval gate for side-effecting tool calls.

Phase 5.8 — every mutating tool call (create/update/delete/send) must be
explicitly approved by the user before it runs. This module centralises the
gate so every specialist that orchestrates MCP tools uses the same flow.

Canonical LangGraph pattern (1.x):
    result = interrupt({
        "kind": "tool_approval",
        "tool": tool_name,
        "args": masked_args,
        "preview": human_readable_text,
        "interrupt_id": uuid,
    })
    # user replies via Telegram button → graph resumes with
    #   Command(resume={interrupt_id: "approve" | "cancel" | {"edit": <args>}})

Invariants (enforced by tests in tests/unit/test_hitl_approval.py):
- `interrupt()` is NEVER wrapped in try/except (the GraphInterrupt exception
  MUST bubble out; swallowing it defeats the pause).
- Code above `interrupt()` is side-effect-free and replay-safe. On resume,
  the node is re-executed from the top, so any DB writes or external calls
  would run twice.
- Secrets are stripped from preview payloads before they leave the process.
- All preview payload values are JSON-safe.

The module is transport-agnostic: formatting yields a plain dict which the
Telegram service converts into an inline-keyboard message. Tests mock both
the interrupt and the Telegram dispatch.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from langgraph.types import interrupt

from src.app.config import Settings, get_settings

logger = structlog.get_logger()

# Mutation classes that require HITL. `read_only` passes through.
_GATED_MUTATION_CLASSES: frozenset[str] = frozenset(
    {"create", "update", "delete", "send", "mutating"}
)

# Sensitive keys that must be masked before we format a preview.
_SECRET_KEY_FRAGMENTS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "auth",
    "bearer",
    "credential",
    "refresh_token",
    "access_token",
    "private_key",
)

# How many characters of a string value we show before truncating.
_STR_PREVIEW_LIMIT = 200
# Max list items inlined before truncating with a count suffix.
_LIST_PREVIEW_LIMIT = 5


class ApprovalResult:
    """Outcome of an approval_gate call (JSON-safe, replay-safe)."""

    __slots__ = ("args", "decision", "interrupt_id", "reason")

    APPROVE = "approve"
    EDIT = "edit"
    CANCEL = "cancel"
    TIMEOUT = "timeout"
    AUTO_APPROVE = "auto_approve"

    def __init__(
        self,
        *,
        decision: str,
        args: dict[str, Any],
        interrupt_id: str,
        reason: str | None = None,
    ) -> None:
        self.decision = decision
        self.args = args
        self.interrupt_id = interrupt_id
        self.reason = reason

    @property
    def should_run(self) -> bool:
        """Return True iff the tool should actually be executed."""
        return self.decision in (self.APPROVE, self.EDIT, self.AUTO_APPROVE)

    @property
    def cancelled(self) -> bool:
        return self.decision in (self.CANCEL, self.TIMEOUT)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "args": self.args,
            "interrupt_id": self.interrupt_id,
            "reason": self.reason,
        }


class SyntheticCancelledResult:
    """Marker result returned to a specialist when the user cancels.

    The specialist treats this as a successful-but-noop tool result so it can
    continue the conversation gracefully ("I've cancelled that.") instead of
    raising and losing the thread.
    """

    __slots__ = ("interrupt_id", "reason", "tool_name")

    def __init__(self, *, tool_name: str, reason: str, interrupt_id: str) -> None:
        self.tool_name = tool_name
        self.reason = reason
        self.interrupt_id = interrupt_id

    def to_tool_result(self) -> dict[str, Any]:
        """Render as an Anthropic-compatible tool_result block."""
        return {
            "type": "tool_result",
            "tool_use_id": self.interrupt_id,
            "content": f"Cancelled by user: {self.reason}",
            "is_error": False,
            "cancelled": True,
        }


# ---------------------------------------------------------------------------
# Pure helpers — fully deterministic, safe to call from a replayed node.
# ---------------------------------------------------------------------------


def requires_approval(
    *,
    mutation_class: str | None,
    requires_confirmation: bool,
    settings: Settings | None = None,
) -> bool:
    """Return True iff this tool call must pass through the HITL gate.

    A tool is gated when:
    - HITL is enabled globally, AND
    - its mutation_class is in {create, update, delete, send, mutating}, OR
    - its metadata explicitly sets requires_confirmation=True.
    """
    settings = settings or get_settings()
    if not settings.hitl_enabled:
        return False
    if requires_confirmation:
        return True
    if mutation_class is None:
        return False
    return mutation_class.lower() in _GATED_MUTATION_CLASSES


def mask_secrets(args: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of args with secret-looking keys masked.

    Applied recursively to nested dicts and lists.
    """
    masked: dict[str, Any] = {}
    for key, value in args.items():
        if _key_is_sensitive(key):
            masked[key] = "***"
        else:
            masked[key] = _mask_value(value)
    return masked


def _key_is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS)


def _mask_value(value: Any) -> Any:
    if isinstance(value, dict):
        return mask_secrets(value)
    if isinstance(value, list):
        return [_mask_value(item) for item in value]
    return value


def format_preview(tool_name: str, args: dict[str, Any]) -> str:
    """Render a plain-English preview for a Telegram approval prompt.

    Keeps the wording short, human-readable, and action-focused.
    Specific tools get a bespoke template; everything else falls back to
    a generic "Run {tool} with these args?" block.
    """
    masked = mask_secrets(args)

    if tool_name.endswith(("__send_message", "__send_email")):
        return _format_email_send(masked)
    if tool_name.endswith("__create_draft"):
        return _format_email_draft(masked)
    if tool_name.endswith(("__create_event", "__update_event")):
        return _format_calendar_event(tool_name, masked)
    if tool_name.endswith("__delete_event"):
        return _format_calendar_delete(masked)
    if tool_name.endswith("__create_issue"):
        return _format_github_issue(masked)

    return _format_generic(tool_name, masked)


def _format_email_send(args: dict[str, Any]) -> str:
    to = _as_str(args.get("to"))
    subject = _truncate(_as_str(args.get("subject")), 80)
    body = _truncate(_as_str(args.get("body") or args.get("text")), _STR_PREVIEW_LIMIT)
    return (
        "Send this email?\n\n"
        f"  To: {to}\n"
        f"  Subject: {subject}\n"
        f"  Body (first {_STR_PREVIEW_LIMIT} chars): {body}"
    )


def _format_email_draft(args: dict[str, Any]) -> str:
    to = _as_str(args.get("to"))
    subject = _truncate(_as_str(args.get("subject")), 80)
    body = _truncate(_as_str(args.get("body") or args.get("text")), _STR_PREVIEW_LIMIT)
    return (
        "Save this draft?\n\n"
        f"  To: {to}\n"
        f"  Subject: {subject}\n"
        f"  Body (first {_STR_PREVIEW_LIMIT} chars): {body}"
    )


def _format_calendar_event(tool_name: str, args: dict[str, Any]) -> str:
    verb = "Update" if tool_name.endswith("update_event") else "Create"
    title = _truncate(_as_str(args.get("summary") or args.get("title")), 80)
    start = _as_str(args.get("start") or args.get("start_time"))
    end = _as_str(args.get("end") or args.get("end_time"))
    attendees = args.get("attendees") or []
    attendees_preview = _format_list_preview(attendees)
    lines = [
        f"{verb} this calendar event?",
        "",
        f"  Title: {title}",
        f"  Start: {start}",
        f"  End:   {end}",
    ]
    if attendees_preview:
        lines.append(f"  Attendees: {attendees_preview}")
    return "\n".join(lines)


def _format_calendar_delete(args: dict[str, Any]) -> str:
    event_id = _as_str(args.get("event_id") or args.get("id"))
    return f"Delete this calendar event?\n\n  Event: {event_id}"


def _format_github_issue(args: dict[str, Any]) -> str:
    repo = _as_str(args.get("repo") or args.get("repository"))
    title = _truncate(_as_str(args.get("title")), 100)
    body = _truncate(_as_str(args.get("body")), _STR_PREVIEW_LIMIT)
    return (
        "Create this GitHub issue?\n\n"
        f"  Repo: {repo}\n"
        f"  Title: {title}\n"
        f"  Body (first {_STR_PREVIEW_LIMIT} chars): {body}"
    )


def _format_generic(tool_name: str, args: dict[str, Any]) -> str:
    lines = [f"Run tool `{tool_name}` with these args?", ""]
    for key, value in args.items():
        rendered = _render_value(value)
        lines.append(f"  {key}: {rendered}")
    return "\n".join(lines)


def _format_list_preview(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    if len(value) <= _LIST_PREVIEW_LIMIT:
        return ", ".join(_as_str(item) for item in value)
    shown = ", ".join(_as_str(item) for item in value[:_LIST_PREVIEW_LIMIT])
    return f"{shown}, +{len(value) - _LIST_PREVIEW_LIMIT} more"


def _render_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return _truncate(_as_str(value), _STR_PREVIEW_LIMIT)
    return _truncate(_as_str(value), _STR_PREVIEW_LIMIT)


def _as_str(value: Any) -> str:
    if value is None:
        return "(empty)"
    if isinstance(value, str):
        return value
    return str(value)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Destination extraction for auto-approve.
# ---------------------------------------------------------------------------


def extract_destinations(tool_name: str, args: dict[str, Any]) -> list[str]:
    """Return the list of destinations (email addresses, event attendees, etc.)
    that will be touched by this tool call.

    Used by ``is_auto_approved`` to decide whether the call is wholly within
    a trusted circle.
    """
    destinations: list[str] = []
    for key in ("to", "cc", "bcc", "recipient", "recipients"):
        value = args.get(key)
        if isinstance(value, str):
            destinations.extend(_split_addresses(value))
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, str):
                    destinations.extend(_split_addresses(entry))
    attendees = args.get("attendees")
    if isinstance(attendees, list):
        for entry in attendees:
            if isinstance(entry, str):
                destinations.extend(_split_addresses(entry))
            elif isinstance(entry, dict):
                email = entry.get("email")
                if isinstance(email, str):
                    destinations.extend(_split_addresses(email))
    return [d.strip().lower() for d in destinations if d and d.strip()]


def _split_addresses(value: str) -> list[str]:
    return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]


def is_auto_approved(
    *,
    tool_name: str,
    args: dict[str, Any],
    settings: Settings | None = None,
) -> bool:
    """Return True iff every destination is in the trusted allow-list.

    An empty trusted list = never auto-approve. A tool with zero destinations
    (e.g. a GitHub issue) is never auto-approved — the allow-list is
    destination-scoped.
    """
    settings = settings or get_settings()
    trusted = {d.strip().lower() for d in settings.hitl_auto_approve_destinations if d.strip()}
    if not trusted:
        return False
    destinations = extract_destinations(tool_name, args)
    if not destinations:
        return False
    return all(dest in trusted for dest in destinations)


# ---------------------------------------------------------------------------
# Resume-value parsing.
# ---------------------------------------------------------------------------


def parse_resume_value(
    resume_value: Any,
    *,
    original_args: dict[str, Any],
) -> tuple[str, dict[str, Any], str | None]:
    """Normalise a user's resume payload into (decision, args, reason).

    Accepted forms:
      - "approve" / "yes" / "ok"           → APPROVE, original_args
      - "cancel" / "no" / "abort"          → CANCEL, original_args
      - "timeout"                          → TIMEOUT, original_args
      - {"edit": {...new args...}}         → EDIT, new args
      - {"decision": "approve"|"cancel"|"edit", "args": {...}, "reason": ...}
    """
    if resume_value is None:
        return ApprovalResult.CANCEL, original_args, "no_reply"

    if isinstance(resume_value, str):
        normalised = resume_value.strip().lower()
        if normalised in {"approve", "approved", "yes", "ok", "confirm"}:
            return ApprovalResult.APPROVE, original_args, None
        if normalised in {"cancel", "cancelled", "no", "abort", "stop"}:
            return ApprovalResult.CANCEL, original_args, None
        if normalised == "timeout":
            return ApprovalResult.TIMEOUT, original_args, "timeout"
        return ApprovalResult.CANCEL, original_args, f"unrecognised_reply:{normalised[:40]}"

    if isinstance(resume_value, dict):
        if "edit" in resume_value and isinstance(resume_value["edit"], dict):
            return ApprovalResult.EDIT, dict(resume_value["edit"]), None
        decision = str(resume_value.get("decision", "")).lower()
        reason = resume_value.get("reason")
        if decision == "edit":
            args = resume_value.get("args")
            if isinstance(args, dict):
                return ApprovalResult.EDIT, dict(args), str(reason) if reason else None
            return ApprovalResult.CANCEL, original_args, "edit_without_args"
        if decision == "approve":
            return ApprovalResult.APPROVE, original_args, str(reason) if reason else None
        if decision == "cancel":
            return ApprovalResult.CANCEL, original_args, str(reason) if reason else None
        if decision == "timeout":
            return ApprovalResult.TIMEOUT, original_args, "timeout"

    return ApprovalResult.CANCEL, original_args, "malformed_resume_value"


# ---------------------------------------------------------------------------
# The gate itself. This is the ONLY function that calls `interrupt()`.
# ---------------------------------------------------------------------------


def build_interrupt_payload(
    *,
    tool_name: str,
    args: dict[str, Any],
    interrupt_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Return the JSON-safe payload the client (Telegram) receives.

    Isolated so tests can assert its shape without invoking the interrupt.
    """
    masked_args = mask_secrets(args)
    return {
        "kind": "tool_approval",
        "interrupt_id": interrupt_id,
        "tool": tool_name,
        "args": masked_args,
        "preview": format_preview(tool_name, args),
        "timeout_seconds": timeout_seconds,
        "buttons": [
            {"label": "Approve", "value": "approve"},
            {"label": "Edit", "value": "edit"},
            {"label": "Cancel", "value": "cancel"},
        ],
    }


def approval_gate(
    *,
    tool_name: str,
    args: dict[str, Any],
    mutation_class: str | None,
    requires_confirmation: bool = False,
    settings: Settings | None = None,
    interrupt_fn: Any = None,
    interrupt_id: str | None = None,
) -> ApprovalResult:
    """Route a tool call through HITL and return the approval outcome.

    Behaviour:
      1. If the tool does not require approval → pass through (APPROVE).
      2. If all destinations are in the trusted allow-list → AUTO_APPROVE.
      3. Otherwise, call ``interrupt()`` with a JSON-safe preview payload and
         translate the user's reply into APPROVE / EDIT / CANCEL / TIMEOUT.

    The ``interrupt_fn`` hook lets tests substitute a synchronous stand-in
    for LangGraph's real ``interrupt()``. Production code passes ``None``
    and we use the canonical import from ``langgraph.types``.

    IMPORTANT:
        This function MUST NOT be wrapped in try/except by callers — the
        underlying GraphInterrupt must bubble. Inside this function we also
        avoid catching the interrupt; any ``Exception`` handling here would
        swallow it.
    """
    settings = settings or get_settings()
    effective_interrupt = interrupt_fn if interrupt_fn is not None else interrupt
    interrupt_id = interrupt_id or f"tool_approval:{uuid.uuid4()}"

    if not requires_approval(
        mutation_class=mutation_class,
        requires_confirmation=requires_confirmation,
        settings=settings,
    ):
        return ApprovalResult(
            decision=ApprovalResult.APPROVE,
            args=args,
            interrupt_id=interrupt_id,
            reason="not_gated",
        )

    if is_auto_approved(tool_name=tool_name, args=args, settings=settings):
        logger.info(
            "hitl_auto_approved",
            tool=tool_name,
            destinations=extract_destinations(tool_name, args),
        )
        return ApprovalResult(
            decision=ApprovalResult.AUTO_APPROVE,
            args=args,
            interrupt_id=interrupt_id,
            reason="trusted_destination",
        )

    payload = build_interrupt_payload(
        tool_name=tool_name,
        args=args,
        interrupt_id=interrupt_id,
        timeout_seconds=settings.hitl_timeout_seconds,
    )

    # DELIBERATELY not wrapped in try/except — GraphInterrupt MUST bubble.
    resume_value = effective_interrupt(payload)

    decision, resolved_args, reason = parse_resume_value(
        resume_value,
        original_args=args,
    )
    logger.info(
        "hitl_resume",
        tool=tool_name,
        decision=decision,
        interrupt_id=interrupt_id,
        reason=reason,
    )
    return ApprovalResult(
        decision=decision,
        args=resolved_args,
        interrupt_id=interrupt_id,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Trace span emission — records approval outcomes to agent_trace_spans.
# ---------------------------------------------------------------------------


def build_approval_span(
    *,
    result: ApprovalResult,
    tool_name: str,
    trace_id: str,
    parent_span_id: str | None = None,
    channel: str = "telegram",
    specialist: str | None = None,
    original_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a trace-span dict (span_kind='approval') for the approval record.

    Callers persist this via ``create_trace_spans`` so reviews can audit
    what was gated, auto-approved, edited, or cancelled. No secrets are
    stored — we use the masked args.
    """
    masked = mask_secrets(original_args or result.args)
    status_map = {
        ApprovalResult.APPROVE: "ok",
        ApprovalResult.AUTO_APPROVE: "ok",
        ApprovalResult.EDIT: "ok",
        ApprovalResult.CANCEL: "cancelled",
        ApprovalResult.TIMEOUT: "timeout",
    }
    return {
        "id": str(uuid.uuid4()),
        "trace_id": trace_id,
        "parent_span_id": parent_span_id,
        "name": f"hitl.{result.decision}",
        "span_kind": "approval",
        "channel": channel,
        "specialist": specialist,
        "status": status_map.get(result.decision, "unknown"),
        "tool_name": tool_name,
        "details": {
            "decision": result.decision,
            "interrupt_id": result.interrupt_id,
            "reason": result.reason,
            "args_preview": masked,
            "args_edited": result.decision == ApprovalResult.EDIT,
        },
    }
