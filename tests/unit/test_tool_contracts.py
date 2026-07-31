"""Unit tests for deterministic tool contract validation."""

from __future__ import annotations

from src.app.core.tool_contracts import validate_tool_arguments
from src.app.domain.models import ToolSpec


def _spec(*, server_name: str = "filesystem") -> ToolSpec:
    return ToolSpec(
        tool_id=f"{server_name}__tool",
        server_name=server_name,
        tool_name="tool",
        input_schema={"type": "object"},
        roots=["workspace/"],
    )


def test_validate_tool_arguments_rejects_reversed_date_window() -> None:
    spec = _spec(server_name="tavily-search")

    errors = validate_tool_arguments(
        spec,
        {
            "date_from": "2026-04-12",
            "date_to": "2026-04-01",
        },
    )

    assert any("date_to: must be on or after date_from" in error for error in errors)


def test_validate_tool_arguments_rejects_excessive_date_window() -> None:
    spec = _spec(server_name="tavily-search")

    errors = validate_tool_arguments(
        spec,
        {
            "start_date": "2026-01-01",
            "end_date": "2028-01-10",
        },
    )

    assert any("date window must be 366 days or less" in error for error in errors)


def test_validate_tool_arguments_rejects_multiline_email_recipients() -> None:
    spec = _spec(server_name="google-gmail")

    errors = validate_tool_arguments(
        spec,
        {
            "to": "alice@example.com\nbcc:mallory@example.com",
        },
    )

    assert "to: recipient must be a single-line address or list entry" in errors


def test_validate_tool_arguments_rejects_unsafe_file_path_lists() -> None:
    spec = _spec(server_name="filesystem")

    errors = validate_tool_arguments(
        spec,
        {
            "file_paths": ["../secrets.txt", "workspace/notes.txt"],
        },
    )

    assert any(
        "file_paths[0]: path must stay relative to the configured roots" in error
        for error in errors
    )


def test_validate_tool_arguments_rejects_large_output_limits() -> None:
    spec = _spec(server_name="filesystem")

    errors = validate_tool_arguments(
        spec,
        {
            "max_chars": 20_000,
            "max_tokens": 9_000,
            "output_size": 12_000,
        },
    )

    assert "max_chars: value must be 10000 or less" in errors
    assert "max_tokens: value must be 8000 or less" in errors
    assert "output_size: value must be 10000 or less" in errors


def test_validate_tool_arguments_accepts_valid_business_rule_inputs() -> None:
    spec = _spec(server_name="google-gmail")

    errors = validate_tool_arguments(
        spec,
        {
            "to": ["alice@example.com", "bob@example.com"],
            "date_from": "2026-04-01",
            "date_to": "2026-04-12",
            "max_tokens": 2_000,
            "limit": 10,
            "path": "workspace/notes.txt",
        },
    )

    assert errors == []
