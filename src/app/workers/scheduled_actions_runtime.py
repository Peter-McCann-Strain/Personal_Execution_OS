"""Worker entrypoints for scheduled actions."""

from __future__ import annotations

import structlog

from src.app.domain.services.scheduled_actions_runtime import execute_scheduled_action
from src.app.persistence.repositories.scheduled_actions import list_due_scheduled_actions

logger = structlog.get_logger()


async def run_due_scheduled_actions(ctx: dict) -> dict[str, int]:
    """Execute due scheduled actions using the existing chat runtime."""
    provider = ctx.get("llm_provider") or ctx.get("anthropic_client")
    if provider is None or not bool(getattr(provider, "configured", True)):
        logger.info("scheduled_actions_skipped_model_provider_disabled")
        return {"executed": 0, "failures": 0}

    session_factory = ctx["session_factory"]
    client = provider

    executed = 0
    failures = 0

    async with session_factory() as session:
        actions = await list_due_scheduled_actions(session, limit=25)
        for action in actions:
            try:
                await execute_scheduled_action(session, client=client, action=action)
                executed += 1
            except Exception:
                failures += 1
                logger.exception(
                    "scheduled_action_execution_failed",
                    action_id=str(action.id),
                )

    logger.info("scheduled_actions_runtime_completed", executed=executed, failures=failures)
    return {"executed": executed, "failures": failures}
