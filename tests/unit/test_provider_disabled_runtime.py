"""Zero-provider runtime behavior across worker execution paths."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.llm import DisabledLLMProvider
from src.app.workers.agent_tasks import (
    _run_commitment_extraction,
    _run_entity_extraction,
    process_agent_task,
)
from src.app.workers.scheduled_actions_runtime import run_due_scheduled_actions


@pytest.mark.asyncio
async def test_model_agent_task_skips_without_retry_or_dlq() -> None:
    ctx = {"job_try": 3, "llm_provider": DisabledLLMProvider()}

    with (
        patch(
            "src.app.workers.agent_tasks._run_entity_extraction",
            new_callable=AsyncMock,
        ) as handler,
        patch(
            "src.app.workers.agent_tasks.write_dlq_row",
            new_callable=AsyncMock,
        ) as write_dlq,
    ):
        result = await process_agent_task(
            ctx,
            "entity_extraction",
            {"text": "private journal content"},
        )

    assert result == {
        "status": "skipped",
        "reason": "model provider disabled",
        "task_type": "entity_extraction",
    }
    handler.assert_not_awaited()
    write_dlq.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduled_actions_skip_before_database_access_when_disabled() -> None:
    result = await run_due_scheduled_actions({"llm_provider": DisabledLLMProvider()})

    assert result == {"executed": 0, "failures": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler",
    [_run_entity_extraction, _run_commitment_extraction],
)
async def test_extraction_handlers_reject_missing_model_client(handler) -> None:
    """Direct worker dispatch must not pass a missing client into model code."""
    result = await handler(
        {
            "settings": object(),
            "session_factory": object(),
        },
        {"episode_id": "episode-1", "text": "I will call Alice tomorrow."},
    )

    assert result == {
        "status": "error",
        "message": "no model client in context",
    }
