"""Integration tests — HITL approval gate inline in the tools handler.

These tests exercise the full orchestrator tool-call node with a fake
Telegram callback producing the resume value (approve / cancel / edit).
No real LangGraph runtime, no real MCP server, no real Telegram.

Coverage:
- approve: user taps Approve -> tool executes with original args.
- cancel: user taps Cancel  -> SyntheticCancelledResult returned, no exec.
- edit: user taps Edit and sends new JSON args -> tool executes with
  the edited args.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.app.core.hitl import SyntheticCancelledResult
from src.app.domain.constants import ToolMutationClass
from src.app.domain.models import ToolInvocationPlan
from src.app.domain.services import approval_callbacks as cb_module
from src.app.domain.services.handlers import tools as tools_handler


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset the process-local approval registry between tests."""
    cb_module.get_registry().clear()
    yield
    cb_module.get_registry().clear()


@pytest.fixture
def mutating_plan() -> ToolInvocationPlan:
    return ToolInvocationPlan(
        tool_id="tool_approval:abc",
        server_name="gmail",
        tool_name="send_email",
        public_name="gmail__send_email",
        arguments={
            "to": "stranger@example.org",
            "subject": "Hi",
            "body": "Hello!",
        },
        input_schema={"type": "object"},
        argument_hash="deadbeef",
        idempotency_key="idem-1",
        trust_context="user",
        requires_confirmation=True,
        mutation_class=str(ToolMutationClass.MUTATING),
        allowed_parallelism="sequential",
        audit_metadata={},
        workflow_id="wf-1",
    )


def _mock_settings(*, timeout_seconds: int = 300) -> MagicMock:
    s = MagicMock()
    s.hitl_enabled = True
    s.hitl_timeout_seconds = timeout_seconds
    s.hitl_auto_approve_destinations = []
    return s


@pytest.mark.asyncio
async def test_approve_path_executes_tool(mutating_plan: ToolInvocationPlan) -> None:
    """User taps Approve -> the plan passes to the MCP bridge with original args."""
    with (
        patch(
            "src.app.config.get_settings",
            return_value=_mock_settings(),
        ),
        patch(
            "src.app.core.hitl.get_settings",
            return_value=_mock_settings(),
        ),
        patch(
            "src.app.domain.services.approval_callbacks.get_settings",
            return_value=_mock_settings(),
        ),
    ):
        gate_task = asyncio.create_task(
            tools_handler._route_plan_through_hitl_gate(
                None,
                plan=mutating_plan,
                trace_id=None,
            )
        )
        # Fake Telegram callback: tap Approve.
        await _tap_until_registered(mutating_plan.tool_id)
        await cb_module.get_registry().resolve(mutating_plan.tool_id, "approve")
        result = await asyncio.wait_for(gate_task, timeout=2)

    assert isinstance(result, ToolInvocationPlan)
    assert result.arguments == mutating_plan.arguments
    assert result.audit_metadata.get("hitl_decision") == "approve"
    assert result.audit_metadata.get("hitl_interrupt_id") == mutating_plan.tool_id


@pytest.mark.asyncio
async def test_cancel_path_returns_synthetic_cancelled(
    mutating_plan: ToolInvocationPlan,
) -> None:
    """User taps Cancel -> gate returns SyntheticCancelledResult, no exec."""
    with (
        patch(
            "src.app.config.get_settings",
            return_value=_mock_settings(),
        ),
        patch(
            "src.app.core.hitl.get_settings",
            return_value=_mock_settings(),
        ),
        patch(
            "src.app.domain.services.approval_callbacks.get_settings",
            return_value=_mock_settings(),
        ),
    ):
        gate_task = asyncio.create_task(
            tools_handler._route_plan_through_hitl_gate(
                None,
                plan=mutating_plan,
                trace_id=None,
            )
        )
        await _tap_until_registered(mutating_plan.tool_id)
        await cb_module.get_registry().resolve(mutating_plan.tool_id, "cancel")
        result = await asyncio.wait_for(gate_task, timeout=2)

    assert isinstance(result, SyntheticCancelledResult)
    assert result.tool_name == "gmail__send_email"
    assert result.interrupt_id == mutating_plan.tool_id
    tool_result = result.to_tool_result()
    assert tool_result["cancelled"] is True
    assert tool_result["is_error"] is False


@pytest.mark.asyncio
async def test_edit_path_updates_args_before_execution(
    mutating_plan: ToolInvocationPlan,
) -> None:
    """User taps Edit and sends new JSON -> plan executes with edited args."""
    with (
        patch(
            "src.app.config.get_settings",
            return_value=_mock_settings(),
        ),
        patch(
            "src.app.core.hitl.get_settings",
            return_value=_mock_settings(),
        ),
        patch(
            "src.app.domain.services.approval_callbacks.get_settings",
            return_value=_mock_settings(),
        ),
    ):
        gate_task = asyncio.create_task(
            tools_handler._route_plan_through_hitl_gate(
                None,
                plan=mutating_plan,
                trace_id=None,
            )
        )
        await _tap_until_registered(mutating_plan.tool_id)
        # User edits with JSON containing new args.
        edit_payload = {
            "edit": {
                "to": "friend@example.com",
                "subject": "Hi (edited)",
                "body": "Hello friend!",
            }
        }
        await cb_module.get_registry().resolve(mutating_plan.tool_id, edit_payload)
        result = await asyncio.wait_for(gate_task, timeout=2)

    assert isinstance(result, ToolInvocationPlan)
    assert result.arguments["to"] == "friend@example.com"
    assert result.arguments["subject"] == "Hi (edited)"
    assert result.audit_metadata.get("hitl_edited") is True
    assert result.audit_metadata.get("hitl_interrupt_id") == mutating_plan.tool_id


async def _tap_until_registered(interrupt_id: str, *, attempts: int = 20) -> None:
    """Poll the registry until the gate has registered its future."""
    registry = cb_module.get_registry()
    for _ in range(attempts):
        if interrupt_id in registry._pending:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"gate did not register interrupt_id {interrupt_id}")
