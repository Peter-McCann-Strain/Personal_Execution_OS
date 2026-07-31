"""PII redaction for structured logs and traces.

Strips personally identifiable information from log payloads *before*
they leave the process. The goal is defence-in-depth: even if a
`logger.info()` somewhere includes a raw diary entry or an email body,
the structured log line written to stdout (and ingested by hosting logs
/ Sentry / Grafana) contains redacted placeholders, not the raw text.

Design notes:

* **Regex-only, zero ML.** PII detection is notoriously lossy with
  regex, but the alternatives (Presidio, GCP DLP) add a hard dependency
  and a per-request latency budget we can't afford in a logging hot
  path. We err on the side of over-redaction.
* **Keys are never redacted.** ``user_id``, ``trace_id``, ``request_id``,
  timing fields etc. are needed to correlate support tickets; silently
  redacting them breaks ops triage.
* **Allowlist is a hard list.** Anything not on the allowlist goes
  through the scrubber by default. This is intentional — a new field
  someone adds tomorrow shouldn't leak raw content by accident.
* **Recursive.** Dict values, list items and nested dicts are all
  walked. Non-string leaf values (ints, bools, floats, None) pass
  through untouched.
* **Structlog processor form.** ``pii_redact_processor`` conforms to
  the ``(logger, method_name, event_dict)`` signature so it can be
  inserted directly in the structlog processor chain.

Regexes:

* emails: RFC-ish, tolerant of subdomains and plus-tags.
* UK phone numbers: mobile / landline with or without country code,
  spaces/hyphens tolerated.
* UK postcodes: full / outward-code only, case-insensitive.
* credit-card-shaped: 13-19 digit groups with optional separators,
  Luhn is *not* verified — this is defensive, not forensic.
* override patterns: caller-supplied regex strings (e.g. the user's
  home address tokens or a specific name) loaded from settings.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Replacement tokens — kept as stable strings so downstream grep works.
# ---------------------------------------------------------------------------

_EMAIL_TOKEN = "[redacted-email]"
_PHONE_TOKEN = "[redacted-phone]"
_POSTCODE_TOKEN = "[redacted-postcode]"
_CARD_TOKEN = "[redacted-card]"
_OVERRIDE_TOKEN = "[redacted]"

# ---------------------------------------------------------------------------
# Core regexes. Ordering is load-bearing: cards first, then emails, then
# phone-shaped numbers, then postcodes. Phone patterns would otherwise
# nibble at card digits before cards get a chance.
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)

# UK phone numbers — covers:
#   +44 7700 900001 / +447700900001 / 07700 900001 / 07700-900001
#   020 7946 0958 / 0207 946 0958 / +44 20 7946 0958
# Minimum 10 digits excluding the country prefix, max 11.
_PHONE_RE = re.compile(
    r"""
    (?:
        (?<!\w)                              # left word-boundary
        (?:\+?44\s?|0)                       # country code or leading 0
        (?:\d[\s\-]?){9,10}\d                # 10-11 digits with optional spaces
        (?!\w)                               # right word-boundary
    )
    """,
    re.VERBOSE,
)

# North American numbers with visible separators, for example
# ``202-555-0101`` or ``+1 (202) 555-0101``. Requiring separators avoids
# treating arbitrary ten-digit identifiers as phone numbers.
_NANP_PHONE_RE = re.compile(r"(?<![\w\d])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")

# UK postcodes, permissive but anchored — matches "SW1A 1AA", "sw1a1aa",
# "EC1A 1BB", "W1 1AA", and outward-code-only "SW1A ". Case-insensitive.
_POSTCODE_RE = re.compile(
    r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b",
    re.IGNORECASE,
)

# 13-19 digit credit-card shapes with optional spaces or hyphens.
# No Luhn check: we accept false positives over false negatives here.
# The trailing ``\d`` anchor prevents the final space/hyphen of a
# "grouped" card from being swallowed into the match.
_CARD_RE = re.compile(
    r"\b(?:\d[ -]?){12,18}\d\b",
)

# ---------------------------------------------------------------------------
# Default allowlist — keys whose *values* we never touch even when string.
# The list below is intentionally conservative. If you add a key here,
# reason about whether that field could ever carry user content.
# ---------------------------------------------------------------------------

DEFAULT_ALLOWLIST_KEYS: frozenset[str] = frozenset(
    {
        # identity / correlation
        "user_id",
        "owner_user_id",
        "request_id",
        "trace_id",
        "parent_span_id",
        "span_id",
        "workflow_id",
        "response_id",
        "session_id",
        "conversation_id",
        "chat_id",
        # routing / status
        "status",
        "status_code",
        "error_class",
        "event",
        "method",
        "path",
        "channel",
        "agent",
        "agent_name",
        "specialist",
        "intent_type",
        # models / tokens / timing (never user content)
        "model",
        "model_used",
        "tokens_in",
        "tokens_out",
        "duration_ms",
        "latency_ms",
        "cost_usd",
        "cost_gbp",
        "cache_hit",
        # structlog internal bookkeeping
        "level",
        "logger",
        "timestamp",
        "filename",
        "func_name",
        "lineno",
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def redact(
    value: str,
    *,
    override_patterns: list[re.Pattern[str]] | None = None,
) -> str:
    """Return ``value`` with known PII patterns replaced with tokens.

    Non-string input is returned unchanged — callers with mixed types
    should use :func:`redact_dict`.
    """
    if not isinstance(value, str):
        return value  # type: ignore[return-value]
    if not value:
        return value

    out = value
    out = _CARD_RE.sub(_CARD_TOKEN, out)
    out = _EMAIL_RE.sub(_EMAIL_TOKEN, out)
    out = _PHONE_RE.sub(_PHONE_TOKEN, out)
    out = _NANP_PHONE_RE.sub(_PHONE_TOKEN, out)
    out = _POSTCODE_RE.sub(_POSTCODE_TOKEN, out)

    if override_patterns:
        for pattern in override_patterns:
            out = pattern.sub(_OVERRIDE_TOKEN, out)

    return out


def redact_dict(
    value: Any,
    *,
    allowlist_keys: frozenset[str] | None = None,
    override_patterns: list[re.Pattern[str]] | None = None,
) -> Any:
    """Recursively redact string values in a mapping / list structure.

    * Dict keys are never modified.
    * Values for keys in ``allowlist_keys`` pass through unchanged
      (still recursively walked if they're structures).
    * Strings are run through :func:`redact`.
    * Lists / tuples are recursed.
    * Everything else is returned as-is.
    """
    allow = allowlist_keys if allowlist_keys is not None else DEFAULT_ALLOWLIST_KEYS

    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, raw in value.items():
            if isinstance(key, str) and key in allow:
                redacted[key] = raw
                continue
            redacted[key] = redact_dict(
                raw,
                allowlist_keys=allow,
                override_patterns=override_patterns,
            )
        return redacted

    if isinstance(value, list):
        return [
            redact_dict(
                item,
                allowlist_keys=allow,
                override_patterns=override_patterns,
            )
            for item in value
        ]

    if isinstance(value, tuple):
        return tuple(
            redact_dict(
                item,
                allowlist_keys=allow,
                override_patterns=override_patterns,
            )
            for item in value
        )

    if isinstance(value, str):
        return redact(value, override_patterns=override_patterns)

    return value


# ---------------------------------------------------------------------------
# Settings-driven factories
# ---------------------------------------------------------------------------


def compile_override_patterns(raw: list[str] | str | None) -> list[re.Pattern[str]]:
    """Compile a list or comma-separated string of regexes into Pattern objects.

    Invalid regexes are silently dropped — we'd rather keep redaction
    working than crash an app startup because someone fat-fingered a
    regex in ``pii_override_patterns``.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        # Comma separator is the pydantic-settings default for list-ish inputs.
        parts = [chunk.strip() for chunk in raw.split(",")]
    else:
        parts = [str(chunk).strip() for chunk in raw]

    compiled: list[re.Pattern[str]] = []
    for part in parts:
        if not part:
            continue
        try:
            compiled.append(re.compile(part))
        except re.error:
            continue
    return compiled


def parse_allowlist_keys(raw: list[str] | str | None) -> frozenset[str]:
    """Merge an override list with :data:`DEFAULT_ALLOWLIST_KEYS`."""
    if raw is None:
        return DEFAULT_ALLOWLIST_KEYS
    if isinstance(raw, str):
        parts = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    else:
        parts = [str(chunk).strip() for chunk in raw if str(chunk).strip()]
    if not parts:
        return DEFAULT_ALLOWLIST_KEYS
    return frozenset(set(DEFAULT_ALLOWLIST_KEYS) | set(parts))


# ---------------------------------------------------------------------------
# structlog processor
# ---------------------------------------------------------------------------


def build_pii_redact_processor(
    *,
    enabled: bool = True,
    override_patterns: list[re.Pattern[str]] | None = None,
    allowlist_keys: frozenset[str] | None = None,
):
    """Return a structlog processor that redacts PII from the event dict.

    The factory shape lets :mod:`src.app.core.logging` bind the
    settings-driven configuration once at startup instead of reaching
    back into :func:`get_settings` on every log line.
    """

    override_patterns = override_patterns or []
    allow = allowlist_keys if allowlist_keys is not None else DEFAULT_ALLOWLIST_KEYS

    def processor(logger, method_name, event_dict):
        # ``logger`` / ``method_name`` are part of the structlog processor contract
        # — they're unused here but must be accepted.
        del logger, method_name
        if not enabled:
            return event_dict
        return redact_dict(
            event_dict,
            allowlist_keys=allow,
            override_patterns=override_patterns,
        )

    return processor


__all__ = [
    "DEFAULT_ALLOWLIST_KEYS",
    "build_pii_redact_processor",
    "compile_override_patterns",
    "parse_allowlist_keys",
    "redact",
    "redact_dict",
]
