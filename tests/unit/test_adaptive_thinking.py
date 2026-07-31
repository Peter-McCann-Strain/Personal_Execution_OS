"""Tests for adaptive-thinking kwarg plumbing in llm_helpers.

These tests verify the April 2026 extended-thinking API contract:

* ``effort`` kwarg is translated to ``thinking={"type":"adaptive"}`` +
  ``output_config={"effort":<level>}``.
* The deprecated ``budget_tokens`` field NEVER appears in any request.
* ``output_config`` passed by the caller is merged on top of the derived
  defaults.
* Absence of ``effort`` / ``thinking_mode`` emits neither field (the
  SDK default applies).
"""

from __future__ import annotations

import json

import pytest

from src.app.core.llm_helpers import (
    _build_thinking_kwargs,
    call_and_extract_text,
    call_and_parse,
    call_llm,
)
from tests.conftest import make_anthropic_response

# ---------------------------------------------------------------------------
# Pure helper — _build_thinking_kwargs
# ---------------------------------------------------------------------------


def test_build_thinking_kwargs_effort_only_defaults_to_adaptive() -> None:
    out = _build_thinking_kwargs(effort="high", thinking_mode=None, output_config=None)
    assert out == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }
    assert "budget_tokens" not in json.dumps(out)


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_build_thinking_kwargs_all_effort_levels_valid(effort: str) -> None:
    out = _build_thinking_kwargs(effort=effort, thinking_mode=None, output_config=None)
    assert out["thinking"] == {"type": "adaptive"}
    assert out["output_config"]["effort"] == effort


def test_build_thinking_kwargs_explicit_disabled_is_honoured() -> None:
    out = _build_thinking_kwargs(effort="medium", thinking_mode="disabled", output_config=None)
    assert out["thinking"] == {"type": "disabled"}
    assert out["output_config"] == {"effort": "medium"}


def test_build_thinking_kwargs_caller_output_config_merges() -> None:
    out = _build_thinking_kwargs(
        effort="high",
        thinking_mode=None,
        output_config={"format": {"type": "json_schema", "schema": {"a": 1}}},
    )
    assert out["output_config"]["effort"] == "high"
    assert out["output_config"]["format"] == {
        "type": "json_schema",
        "schema": {"a": 1},
    }


def test_build_thinking_kwargs_caller_can_override_effort() -> None:
    """Caller-supplied output_config keys must win over the derived defaults."""
    out = _build_thinking_kwargs(
        effort="low",
        thinking_mode=None,
        output_config={"effort": "max"},
    )
    assert out["output_config"]["effort"] == "max"


def test_build_thinking_kwargs_none_emits_nothing() -> None:
    out = _build_thinking_kwargs(effort=None, thinking_mode=None, output_config=None)
    assert out == {}


def test_build_thinking_kwargs_never_emits_budget_tokens() -> None:
    for effort in ("low", "medium", "high", "xhigh", "max", None):
        for mode in ("adaptive", "disabled", None):
            out = _build_thinking_kwargs(
                effort=effort,  # type: ignore[arg-type]
                thinking_mode=mode,  # type: ignore[arg-type]
                output_config=None,
            )
            assert "budget_tokens" not in json.dumps(out), (
                f"budget_tokens leaked for effort={effort} mode={mode}: {out}"
            )


# ---------------------------------------------------------------------------
# call_llm integration — asserts the SDK receives the adaptive shape
# ---------------------------------------------------------------------------


async def test_call_llm_passes_adaptive_thinking_to_anthropic(mock_anthropic_client) -> None:
    """call_llm(effort='high') must send thinking + output_config to the SDK."""
    mock_anthropic_client.messages.create.return_value = make_anthropic_response("ok")

    await call_llm(
        mock_anthropic_client,
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system="test",
        messages=[{"role": "user", "content": "hi"}],
        inject_personality=False,
        inject_datetime=False,
        cache_system=False,
        effort="high",
    )

    kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "high"}
    assert "budget_tokens" not in kwargs
    # Ensure no deprecated field leaked anywhere in the serialised payload.
    assert "budget_tokens" not in json.dumps(kwargs, default=str)


async def test_call_llm_no_thinking_by_default(mock_anthropic_client) -> None:
    """Omitting effort/thinking_mode must not add thinking fields to the call."""
    mock_anthropic_client.messages.create.return_value = make_anthropic_response("ok")

    await call_llm(
        mock_anthropic_client,
        model="claude-haiku-4-5",
        max_tokens=512,
        system="test",
        messages=[{"role": "user", "content": "hi"}],
        inject_personality=False,
        inject_datetime=False,
        cache_system=False,
    )

    kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    assert "thinking" not in kwargs
    assert "output_config" not in kwargs
    assert "budget_tokens" not in kwargs


async def test_call_and_parse_accepts_output_config(mock_anthropic_client) -> None:
    """call_and_parse must not barf when callers pass output_config."""
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool

    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps({"ok": True})
    )

    result = await call_and_parse(
        mock_anthropic_client,
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system="test",
        messages=[{"role": "user", "content": "hi"}],
        response_model=_Out,
        error_context="adaptive test",
        inject_personality=False,
        effort="medium",
        output_config={"format": {"type": "json_schema", "schema": _Out.model_json_schema()}},
    )

    assert result.ok is True
    kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"]["effort"] == "medium"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "budget_tokens" not in json.dumps(kwargs, default=str)


async def test_call_and_extract_text_forwards_effort(mock_anthropic_client) -> None:
    mock_anthropic_client.messages.create.return_value = make_anthropic_response("hello")

    await call_and_extract_text(
        mock_anthropic_client,
        model="claude-opus-4-7",
        max_tokens=4096,
        system="test",
        messages=[{"role": "user", "content": "hi"}],
        error_context="adaptive-text",
        inject_personality=False,
        effort="max",
    )

    kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "max"}
    assert "budget_tokens" not in json.dumps(kwargs, default=str)
