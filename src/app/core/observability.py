"""Observability — LLM call logging to agent_actions table.

Logs every LLM call with model, tokens, cost, latency. No silent calls.
"""

import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.persistence.models import AgentAction

logger = structlog.get_logger()

# Claude 4.5 pricing per million tokens (March 2026)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0},
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Calculate USD cost for an LLM call. Returns None for unknown models."""
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        logger.warning("unknown_model_pricing", model=model)
        return None
    input_cost = input_tokens * pricing["input"] / 1_000_000
    output_cost = output_tokens * pricing["output"] / 1_000_000
    return input_cost + output_cost


@asynccontextmanager
async def track_llm_call(
    session: AsyncSession,
    agent_name: str,
    action_type: str,
) -> AsyncGenerator[dict]:
    """Context manager to track an LLM call's duration and log it.

    Usage:
        async with track_llm_call(session, "diary", "process_entry") as tracker:
            response = await client.messages.create(...)
            tracker["model"] = model
            tracker["input_tokens"] = response.usage.input_tokens
            tracker["output_tokens"] = response.usage.output_tokens
    """
    tracker: dict = {}
    start = time.monotonic()
    error: BaseException | None = None

    try:
        yield tracker
    except BaseException as exc:
        error = exc
        raise
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        status = "failed" if error is not None else "success"

        if error is not None:
            logger.error(
                "llm_call_failed",
                agent=agent_name,
                action=action_type,
                error=str(error),
                duration_ms=duration_ms,
            )
            # Don't persist a record for failed calls — data is incomplete
        else:
            if "model" not in tracker:
                raise ValueError("tracker missing required field: 'model'")
            if "input_tokens" not in tracker:
                raise ValueError("tracker missing required field: 'input_tokens'")
            if "output_tokens" not in tracker:
                raise ValueError("tracker missing required field: 'output_tokens'")

            model = tracker["model"]
            input_tokens = tracker["input_tokens"]
            output_tokens = tracker["output_tokens"]
            cost = calculate_cost(model, input_tokens, output_tokens)

            action = AgentAction(
                id=uuid.uuid4(),
                agent_name=agent_name,
                action_type=action_type,
                model_used=model,
                tokens_in=input_tokens,
                tokens_out=output_tokens,
                cost_usd=cost,
                duration_ms=duration_ms,
                input_summary=tracker.get("input_summary"),
                output_summary=tracker.get("output_summary"),
                trace_id=tracker.get("trace_id"),
            )
            session.add(action)

            logger.info(
                "llm_call_tracked",
                agent=agent_name,
                action=action_type,
                model=model,
                tokens_in=input_tokens,
                tokens_out=output_tokens,
                cost_usd=round(cost, 6) if cost is not None else None,
                duration_ms=duration_ms,
                status=status,
            )
