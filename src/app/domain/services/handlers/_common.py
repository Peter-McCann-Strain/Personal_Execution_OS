"""Shared utilities for handler modules."""

from __future__ import annotations

from datetime import timedelta

import structlog

from src.app.config import get_settings
from src.app.core.exceptions import DatabaseError

logger = structlog.get_logger()


def _attach_request_id(payload: dict) -> dict:
    """Copy the current structlog request_id onto the ARQ payload.

    ARQ jobs run in a separate event loop where structlog contextvars are
    empty, so we can't rely on contextvar inheritance the way we do inside
    a single asyncio task. Stash the ID in the payload and have the worker
    re-bind it on task start (see workers.agent_tasks.process_agent_task).
    """
    if "request_id" in payload:
        return payload
    ctx = structlog.contextvars.get_contextvars()
    bound = ctx.get("request_id")
    if isinstance(bound, str) and bound:
        return {**payload, "request_id": bound}
    return payload


async def enqueue_agent_task(
    task_type: str,
    payload: dict,
    *,
    error_label: str,
    defer_by_seconds: int | float | None = None,
) -> None:
    """Enqueue one ARQ-backed background task.

    Raises when queue infrastructure is unavailable or misconfigured.
    """
    try:
        from arq.connections import ArqRedis, RedisSettings, create_pool

        settings = get_settings()
        redis_settings = RedisSettings.from_dsn(settings.redis_url.get_secret_value())
        pool: ArqRedis = await create_pool(redis_settings)

        enqueue_kwargs = {}
        if defer_by_seconds is not None:
            enqueue_kwargs["_defer_by"] = timedelta(seconds=defer_by_seconds)

        enriched_payload = _attach_request_id(payload)

        await pool.enqueue_job(
            "process_agent_task",
            task_type,
            enriched_payload,
            **enqueue_kwargs,
        )
        await pool.aclose()
    except Exception as exc:
        logger.error(
            "agent_task_enqueue_failed",
            task_type=task_type,
            exc_info=True,
        )
        raise DatabaseError(
            f"{error_label} enqueue failed with {type(exc).__name__}: {exc}",
        ) from exc


async def enqueue_entity_extraction(episode_id: str, text_content: str) -> None:
    """Enqueue entity extraction as a background task via ARQ."""
    await enqueue_agent_task(
        "entity_extraction",
        {"episode_id": episode_id, "text": text_content},
        error_label="Entity extraction",
    )
    logger.info("entity_extraction_enqueued", episode_id=episode_id)


async def enqueue_commitment_extraction(episode_id: str, text_content: str) -> None:
    """Enqueue commitment extraction as a background task via ARQ.

    Raises when queue infrastructure is unavailable or misconfigured.
    """
    await enqueue_agent_task(
        "commitment_extraction",
        {"episode_id": episode_id, "text": text_content},
        error_label="Commitment extraction",
    )
    logger.info("commitment_extraction_enqueued", episode_id=episode_id)


async def enqueue_reflection_pack_refresh(
    refresh_reason: str,
    *,
    flush_evening_notifications: bool = False,
    force: bool = False,
    defer_by_seconds: int | float | None = None,
) -> bool:
    """Compatibility no-op after removal of the phone-reflection runtime."""
    del refresh_reason, flush_evening_notifications, force, defer_by_seconds
    return False
