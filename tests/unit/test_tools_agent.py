"""Tests for tools agent — tool planning and result summarisation."""

import json
import re

import anthropic
import pytest

from src.app.agents.prompts.tools import TOOL_PLANNING_PROMPT
from src.app.agents.specialists.tools import (
    ToolPlan,
    ToolResult,
    plan_tool_calls,
    summarise_tool_results,
)
from src.app.core.exceptions import LLMError
from tests.conftest import make_anthropic_response


@pytest.mark.asyncio
async def test_plan_tool_calls(mock_anthropic_client):
    response_data = {
        "tools": [
            {
                "name": "calendar",
                "action": "list_events",
                "params": {
                    "start_date": "2026-08-01T09:00:00Z",
                    "end_date": "2026-08-01T17:00:00Z",
                },
            }
        ],
        "reasoning": "User wants to read their calendar",
    }
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    plan = await plan_tool_calls("Show my calendar tomorrow", mock_anthropic_client)
    assert isinstance(plan, ToolPlan)
    assert len(plan.tools) == 1
    assert plan.tools[0].name == "calendar"


@pytest.mark.asyncio
async def test_plan_no_tools_needed(mock_anthropic_client):
    response_data = {"tools": [], "reasoning": "No tool needed for this request"}
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        json.dumps(response_data)
    )
    plan = await plan_tool_calls("What's the meaning of life?", mock_anthropic_client)
    assert len(plan.tools) == 0


@pytest.mark.asyncio
async def test_plan_api_failure(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
    with pytest.raises(LLMError, match="Tool planning failed"):
        await plan_tool_calls("test", mock_anthropic_client)


@pytest.mark.asyncio
async def test_summarise_tool_results(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        "Your calendar has one event tomorrow at 2pm."
    )
    results = [
        ToolResult(
            tool="calendar",
            action="list_events",
            success=True,
            data={"event_id": "123", "title": "Meeting"},
        )
    ]
    summary = await summarise_tool_results("show my calendar", results, mock_anthropic_client)
    assert "calendar" in summary or "meeting" in summary.lower()


@pytest.mark.asyncio
async def test_summarise_with_failed_tool(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = make_anthropic_response(
        "The email search failed due to authentication issues."
    )
    results = [
        ToolResult(
            tool="email",
            action="search",
            success=False,
            error="Authentication failed",
        )
    ]
    summary = await summarise_tool_results("find an email", results, mock_anthropic_client)
    assert isinstance(summary, str)


@pytest.mark.asyncio
async def test_summarise_api_failure(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
    with pytest.raises(LLMError, match="Tool result summary failed"):
        await summarise_tool_results("test", [], mock_anthropic_client)


def test_documented_tool_plan_examples_match_runtime_schema() -> None:
    examples = re.findall(r"<output>\n(.*?)\n</output>", TOOL_PLANNING_PROMPT, flags=re.DOTALL)

    assert examples
    for example in examples:
        ToolPlan.model_validate_json(example)
