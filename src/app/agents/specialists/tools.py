"""Tools agent — orchestrates external tool calls (calendar, email, web search).

Determines which tools to invoke and executes them. No fallback.
"""

import json

import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from src.app.agents.prompts.tools import TOOL_PLANNING_PROMPT, TOOL_RESULT_SUMMARY_PROMPT
from src.app.config import get_settings
from src.app.core.llm_helpers import call_and_extract_text, call_and_parse

logger = structlog.get_logger()


class ToolCall(BaseModel):
    name: str
    action: str
    params: dict = Field(default_factory=dict)
    step: int | None = None
    depends_on: list[int] = Field(default_factory=list)
    purpose: str | None = None
    on_failure: str | None = None


class ToolPlan(BaseModel):
    tools: list[ToolCall] = Field(default_factory=list)
    reasoning: str = ""
    execution_mode: str | None = None
    requires_confirmation: bool = False
    confirmation_message: str | None = None


class ToolResult(BaseModel):
    tool: str
    action: str
    success: bool
    data: dict = Field(default_factory=dict)
    error: str | None = None


async def plan_tool_calls(
    user_request: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> ToolPlan:
    """Determine which tools to call for a user request."""
    settings = get_settings()
    model = model or settings.tools_model
    max_tokens = max_tokens or settings.tools_plan_max_tokens

    return await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system=TOOL_PLANNING_PROMPT,
        messages=[{"role": "user", "content": user_request}],
        response_model=ToolPlan,
        error_context="Tool planning",
    )


async def summarise_tool_results(
    original_request: str,
    results: list[ToolResult],
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Summarise tool execution results for the user."""
    settings = get_settings()
    model = model or settings.tools_model
    max_tokens = max_tokens or settings.tools_summary_max_tokens

    results_text = "\n".join(
        f"- {r.tool}.{r.action}: "
        f"{'SUCCESS' if r.success else f'FAILED: {r.error}'}\n"
        f"  Data: {json.dumps(r.data)}"
        for r in results
    )

    return await call_and_extract_text(
        client,
        model=model,
        max_tokens=max_tokens,
        system=TOOL_RESULT_SUMMARY_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Original request: {original_request}\n\nTool results:\n{results_text}"
                ),
            }
        ],
        error_context="Tool result summary",
    )
