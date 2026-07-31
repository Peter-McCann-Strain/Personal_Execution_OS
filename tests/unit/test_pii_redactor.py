"""Tests for PII redactor (P3.7)."""

from __future__ import annotations

import io
import json
import logging

import structlog

from src.app.core.pii_redactor import (
    DEFAULT_ALLOWLIST_KEYS,
    build_pii_redact_processor,
    compile_override_patterns,
    parse_allowlist_keys,
    redact,
    redact_dict,
)

# ---------------------------------------------------------------------------
# String-level behaviour
# ---------------------------------------------------------------------------


def test_email_redacted() -> None:
    assert redact("contact user@example.com") == "contact [redacted-email]"


def test_email_subdomain_and_plus_tag_redacted() -> None:
    assert redact("owner+work@example.com please") == "[redacted-email] please"


def test_phone_e164_redacted() -> None:
    assert redact("call +44 7700 900001 now") == "call [redacted-phone] now"


def test_phone_domestic_redacted() -> None:
    assert redact("07539 882256 mobile") == "[redacted-phone] mobile"


def test_phone_landline_with_hyphens_redacted() -> None:
    assert redact("020-7946-0958") == "[redacted-phone]"


def test_postcode_redacted() -> None:
    assert redact("I live at SW1A 1AA") == "I live at [redacted-postcode]"


def test_postcode_lowercase_redacted() -> None:
    assert redact("ec1a 1bb") == "[redacted-postcode]"


def test_card_number_redacted() -> None:
    # 16-digit VISA shape
    assert redact("pay 4111 1111 1111 1111 ok") == "pay [redacted-card] ok"


def test_card_number_no_separators_redacted() -> None:
    assert redact("4111111111111111") == "[redacted-card]"


def test_short_number_not_redacted() -> None:
    # 12 digits should NOT be treated as a card
    assert redact("id 123456789012") == "id 123456789012"


def test_empty_string_passes_through() -> None:
    assert redact("") == ""


def test_non_string_passes_through() -> None:
    # redact() tolerates non-strings (defensive for mixed logs).
    assert redact(None) is None  # type: ignore[arg-type]
    assert redact(42) == 42  # type: ignore[arg-type]


def test_multiple_categories_in_one_string() -> None:
    source = (
        "User user@example.com at SW1A 1AA called +44 7700 900001 with card 4111 1111 1111 1111."
    )
    out = redact(source)
    assert "@" not in out
    # Card is redacted first, so no 16-digit groups remain.
    assert "4111" not in out
    assert "[redacted-email]" in out
    assert "[redacted-phone]" in out
    assert "[redacted-postcode]" in out
    assert "[redacted-card]" in out


# ---------------------------------------------------------------------------
# Override patterns
# ---------------------------------------------------------------------------


def test_override_patterns_applied() -> None:
    patterns = compile_override_patterns(["Alex Example"])
    out = redact("Author: Alex Example wrote this", override_patterns=patterns)
    assert "Alex Example" not in out
    assert "[redacted]" in out


def test_override_pattern_invalid_regex_ignored() -> None:
    # Unbalanced paren would blow up re.compile — must be silently dropped.
    patterns = compile_override_patterns(["(unclosed"])
    assert patterns == []


def test_override_pattern_string_input() -> None:
    # pydantic-settings hands us comma-separated strings.
    patterns = compile_override_patterns("Alpha, Beta")
    out = redact("Alpha and Beta and Gamma", override_patterns=patterns)
    assert "Alpha" not in out
    assert "Beta" not in out
    assert "Gamma" in out


# ---------------------------------------------------------------------------
# Nested dict redaction
# ---------------------------------------------------------------------------


def test_nested_dicts_redact_at_all_depths() -> None:
    payload = {
        "top": "ping me at user@example.com",
        "nested": {
            "deeper": "post to SW1A 1AA",
            "list": [
                "or +44 7700 900001",
                {"card": "4111 1111 1111 1111"},
            ],
        },
    }
    out = redact_dict(payload)
    assert out["top"] == "ping me at [redacted-email]"
    assert out["nested"]["deeper"] == "post to [redacted-postcode]"
    assert out["nested"]["list"][0] == "or [redacted-phone]"
    assert out["nested"]["list"][1]["card"] == "[redacted-card]"


def test_allowlist_keys_never_redacted() -> None:
    payload = {
        "user_id": "alex@example.com",  # would normally be redacted
        "trace_id": "trace-deadbeef",
        "model": "claude-sonnet-4-6",
        "tokens_in": 123,
        "tokens_out": 456,
        "status": "success",
        "note": "email me at user@example.com",
    }
    out = redact_dict(payload)
    # Allowlist keys pass through literally.
    assert out["user_id"] == "alex@example.com"
    assert out["trace_id"] == "trace-deadbeef"
    assert out["model"] == "claude-sonnet-4-6"
    assert out["tokens_in"] == 123
    # Non-allowlisted string still redacted.
    assert out["note"] == "email me at [redacted-email]"


def test_custom_allowlist_merged_with_defaults() -> None:
    merged = parse_allowlist_keys(["custom_safe_key"])
    assert "custom_safe_key" in merged
    assert "user_id" in merged  # default retained


def test_parse_allowlist_keys_string_input() -> None:
    merged = parse_allowlist_keys("key_a, key_b")
    assert "key_a" in merged
    assert "key_b" in merged


def test_default_allowlist_has_core_correlation_keys() -> None:
    required = {"user_id", "request_id", "trace_id", "status", "model", "tokens_in", "tokens_out"}
    assert required <= DEFAULT_ALLOWLIST_KEYS


def test_override_patterns_applied_in_dict() -> None:
    patterns = compile_override_patterns(["secret-token-\\d+"])
    payload = {"body": "use secret-token-42 for access"}
    out = redact_dict(payload, override_patterns=patterns)
    assert "secret-token-42" not in out["body"]


def test_non_string_leaves_unchanged() -> None:
    payload = {"count": 3, "ok": True, "ratio": 1.5, "maybe": None}
    out = redact_dict(payload)
    assert out == payload


# ---------------------------------------------------------------------------
# structlog processor integration
# ---------------------------------------------------------------------------


def test_pii_processor_returns_event_dict_unchanged_when_disabled() -> None:
    processor = build_pii_redact_processor(enabled=False)
    event = {"msg": "user@example.com"}
    out = processor(None, "info", event)
    assert out["msg"] == "user@example.com"


def test_pii_processor_redacts_in_flight_event_dict() -> None:
    processor = build_pii_redact_processor()
    event = {
        "event": "diary_entry_saved",
        "user_id": "user-1",  # allowlisted
        "content": "Had coffee with user@example.com at SW1A 1AA today.",
    }
    out = processor(None, "info", event)
    assert out["user_id"] == "user-1"
    assert "user@example.com" not in out["content"]
    assert "SW1A 1AA" not in out["content"]
    assert "[redacted-email]" in out["content"]
    assert "[redacted-postcode]" in out["content"]


def test_end_to_end_structlog_json_has_no_raw_pii() -> None:
    """Emit a log line with diary content and verify the rendered JSON is clean."""
    processor = build_pii_redact_processor()

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            processor,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler.setFormatter(formatter)

    test_logger_name = "pii_redactor_test"
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    logger_ = logging.getLogger(test_logger_name)
    logger_.handlers = [handler]
    logger_.setLevel(logging.INFO)
    logger_.propagate = False

    structlog.get_logger(test_logger_name).info(
        "diary_entry_saved",
        user_id="user-1",
        content=("Spoke to owner@example.com about the project, their number is +1 202 555 0102."),
    )

    line = stream.getvalue().strip()
    assert line, "expected a rendered log line"
    payload = json.loads(line)
    # Allowlisted field preserved, content scrubbed.
    assert payload["user_id"] == "user-1"
    assert "owner@example.com" not in line
    assert "+44 7700 900001" not in line
    assert "[redacted-email]" in payload["content"]
    assert "[redacted-phone]" in payload["content"]
