"""Background agent task execution."""

import base64
import contextlib
import traceback as tb_module
from datetime import datetime, time
from typing import Any
from uuid import UUID

import structlog
from aiogram import Bot
from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.app.agents.specialists.notification import (
    FatigueManager,
    Notification,
    Priority,
)
from src.app.config import get_settings
from src.app.core.otel import bind_request_id, get_tracer
from src.app.persistence.repositories.entities import (
    add_mention,
    add_relationship,
    upsert_entity,
)
from src.app.second_brain.entity_extractor import extract_entities
from src.app.second_brain.link_discoverer import discover_links_by_entities
from src.app.workers.curation import run_curation

logger = structlog.get_logger()

_MODEL_TASK_TYPES = frozenset(
    {
        "entity_extraction",
        "commitment_extraction",
    }
)


def _model_provider_available(ctx: dict) -> bool:
    """Return whether the worker context contains an enabled model provider."""
    provider = ctx.get("llm_provider") or ctx.get("anthropic_client")
    return provider is not None and bool(getattr(provider, "configured", True))


async def write_dlq_row(
    ctx: dict,
    *,
    function: str,
    exception: BaseException,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    job_id: str | None = None,
    retry_count: int = 0,
    enqueued_at: datetime | None = None,
    traceback_text: str | None = None,
) -> None:
    """Best-effort insert into the DLQ.

    Swallows DB errors — we prefer losing a DLQ row to killing the worker.
    """
    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    if session_factory is None:
        logger.error(
            "dlq_write_missing_session_factory",
            function=function,
            exception_class=type(exception).__name__,
        )
        return

    from src.app.persistence.repositories.dlq_jobs import create_dlq_job

    tb_text = traceback_text or "".join(
        tb_module.format_exception(type(exception), exception, exception.__traceback__)
    )

    try:
        async with session_factory() as session:
            await create_dlq_job(
                session,
                function=function,
                exception_class=type(exception).__name__,
                exception_message=str(exception)[:4000] if str(exception) else None,
                traceback_text=tb_text,
                args=args,
                kwargs=kwargs,
                job_id=job_id,
                retry_count=retry_count,
                enqueued_at=enqueued_at,
            )
            await session.commit()
        logger.info(
            "dlq_row_written",
            function=function,
            exception_class=type(exception).__name__,
            job_id=job_id,
            retry_count=retry_count,
        )
    except Exception:
        # DLQ write is best-effort. Log loudly but do NOT re-raise —
        # re-raising here would turn every terminal job failure into a
        # worker crash (cascading outage when the DB is down).
        logger.error(
            "dlq_write_failed",
            function=function,
            exception_class=type(exception).__name__,
            exc_info=True,
        )


async def capture_poison_pill(
    ctx: dict,
    *,
    raw_payload: bytes | str | None,
    exception: BaseException,
    job_id: str | None = None,
) -> None:
    """Capture a deserialization failure (poison pill) into the DLQ.

    The original function is unknown because the payload never made it past
    deserialization. We stash the raw bytes as base64 so an operator can
    inspect what came in.
    """
    raw_b64: str | None = None
    if raw_payload is not None:
        if isinstance(raw_payload, str):
            raw_payload = raw_payload.encode("utf-8", errors="replace")
        raw_b64 = base64.b64encode(raw_payload).decode("ascii")

    await write_dlq_row(
        ctx,
        function="<unknown>",
        exception=exception,
        kwargs={"raw_payload_b64": raw_b64} if raw_b64 is not None else {"raw_payload_b64": None},
        job_id=job_id,
    )


def _dnd_times() -> tuple[time, time]:
    """Read DND hours from settings."""
    settings = get_settings()
    return (
        time(settings.notification_dnd_start_hour, 0),
        time(settings.notification_dnd_end_hour, 0),
    )


# Module-level FatigueManager — initialised lazily on first access.
# `init_fatigue_manager()` is called at worker startup to attach Redis.
_fatigue_manager: FatigueManager | None = None


def _get_default_fatigue_manager() -> FatigueManager:
    """Get or create the default (no-Redis) FatigueManager."""
    global _fatigue_manager
    if _fatigue_manager is None:
        dnd_start, dnd_end = _dnd_times()
        _fatigue_manager = FatigueManager(dnd_start=dnd_start, dnd_end=dnd_end)
    return _fatigue_manager


def init_fatigue_manager(redis_url: str) -> FatigueManager:
    """Re-initialise the module-level FatigueManager with Redis persistence."""
    global _fatigue_manager
    import redis.asyncio as aioredis

    dnd_start, dnd_end = _dnd_times()
    pool = aioredis.from_url(redis_url, decode_responses=False)
    _fatigue_manager = FatigueManager(
        dnd_start=dnd_start,
        dnd_end=dnd_end,
        redis=pool,
    )
    return _fatigue_manager


def get_fatigue_manager() -> FatigueManager:
    """Return the module-level FatigueManager for use by scheduled tasks."""
    return _get_default_fatigue_manager()


async def process_agent_task(ctx: dict, task_type: str, payload: dict) -> dict:
    """Execute a background agent task with retry support.

    Task types: entity_extraction, notification, curation, and review.
    Uses ARQ's Retry mechanism with exponential backoff (30s, 60s, 90s).
    """
    job_try = ctx.get("job_try", 1)
    max_retries = 3

    # Re-bind the correlation ID that produced this job so every log line
    # emitted during task execution (including llm_call_success from
    # llm_helpers) carries the same request_id as the originating HTTP turn.
    # ARQ runs jobs in a fresh asyncio task, so contextvars do NOT carry
    # across from the enqueueing coroutine — we stashed it in the payload in
    # enqueue_agent_task._attach_request_id and re-hydrate here.
    structlog.contextvars.clear_contextvars()
    request_id = payload.get("request_id") if isinstance(payload, dict) else None
    if isinstance(request_id, str) and request_id:
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            worker_task_type=task_type,
            worker_job_try=job_try,
        )
    else:
        structlog.contextvars.bind_contextvars(
            worker_task_type=task_type,
            worker_job_try=job_try,
        )

    logger.info("agent_task_started", task_type=task_type, attempt=job_try)

    handlers = {
        "entity_extraction": _run_entity_extraction,
        "commitment_extraction": _run_commitment_extraction,
        "notification": _run_notification,
        "curation": _run_curation_task,
        "review": _run_review_task,
    }

    handler = handlers.get(task_type)
    if handler is None:
        logger.error("unknown_task_type", task_type=task_type)
        return {"status": "error", "message": f"Unknown task type: {task_type}"}

    if task_type in _MODEL_TASK_TYPES and not _model_provider_available(ctx):
        logger.info(
            "agent_task_skipped_model_provider_disabled",
            task_type=task_type,
        )
        return {
            "status": "skipped",
            "reason": "model provider disabled",
            "task_type": task_type,
        }

    # OTel worker span — wraps the handler so child spans (LLM calls,
    # MCP tool calls) nest under it. ``request_id`` is re-bound to the
    # structlog contextvars above and mirrored onto the span so external
    # collectors can correlate with the originating HTTP turn.
    tracer = get_tracer()
    with tracer.start_as_current_span("worker.agent_task") as span:
        try:
            span.set_attribute("worker.task_type", task_type)
            span.set_attribute("worker.job_try", int(job_try))
            job_id = ctx.get("job_id")
            if job_id:
                span.set_attribute("worker.job_id", str(job_id))
        except Exception:
            logger.debug("otel_worker_set_attrs_failed", exc_info=True)
        bind_request_id(span, request_id if isinstance(request_id, str) else None)

        try:
            result = await handler(ctx, payload)
            logger.info("agent_task_completed", task_type=task_type, attempt=job_try)
            with contextlib.suppress(Exception):
                span.set_attribute("worker.task_status", "ok")
            return result
        except Exception as exc:
            with contextlib.suppress(Exception):
                span.record_exception(exc)
                from opentelemetry.trace import Status, StatusCode

                span.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
            if job_try < max_retries:
                logger.warning(
                    "agent_task_retry",
                    task_type=task_type,
                    attempt=job_try,
                    max_retries=max_retries,
                )
                with contextlib.suppress(Exception):
                    span.set_attribute("worker.task_status", "retry")
                raise Retry(defer=job_try * 30) from exc  # 30s, 60s, 90s
            logger.exception(
                "agent_task_failed_permanently",
                task_type=task_type,
                attempts=job_try,
            )
            with contextlib.suppress(Exception):
                span.set_attribute("worker.task_status", "failed_permanently")
            # Terminal failure — write to DLQ so the payload survives for replay.
            await write_dlq_row(
                ctx,
                function=f"process_agent_task:{task_type}",
                exception=exc,
                args=[task_type],
                kwargs={"payload": payload},
                job_id=ctx.get("job_id"),
                retry_count=job_try,
                enqueued_at=ctx.get("enqueue_time"),
            )
            return {
                "status": "error",
                "message": f"Task failed after {job_try} attempts",
            }


async def _run_entity_extraction(ctx: dict, payload: dict) -> dict:
    """Extract entities from an episode in the background."""
    episode_id = payload.get("episode_id")
    text_content = payload.get("text")

    if not text_content:
        logger.warning("entity_extraction_no_text", episode_id=episode_id)
        return {"status": "skipped", "reason": "no text provided"}

    logger.info("entity_extraction_task", episode_id=episode_id)

    settings = ctx.get("settings")
    if not settings:
        logger.error("entity_extraction_no_settings")
        return {"status": "error", "message": "no settings in context"}

    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    if not session_factory:
        logger.error("entity_extraction_no_session_factory")
        return {"status": "error", "message": "no session_factory in context"}

    client = ctx.get("llm_provider") or ctx.get("anthropic_client")
    extraction = await extract_entities(text_content, client)

    # Persist entities and relationships
    async with session_factory() as session:
        entity_id_map: dict[str, UUID] = {}

        for entity in extraction.entities:
            entity_id = await upsert_entity(
                session,
                name=entity.name,
                entity_type=entity.entity_type,
            )
            entity_id_map[entity.name] = entity_id

            # Link entity mention to episode if episode_id provided
            if episode_id:
                await add_mention(
                    session,
                    entity_id=entity_id,
                    episode_id=UUID(episode_id) if isinstance(episode_id, str) else episode_id,
                    context_snippet=entity.context,
                )

        for rel in extraction.relationships:
            source_id = entity_id_map.get(rel.source)
            target_id = entity_id_map.get(rel.target)
            if source_id and target_id:
                await add_relationship(
                    session,
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    relationship_type=rel.relationship_type,
                )

        await session.commit()

        # --- Link discovery (best-effort) ---
        discovered_links: list[dict] = []
        if episode_id and extraction.entities:
            try:
                ep_uuid = UUID(episode_id) if isinstance(episode_id, str) else episode_id
                discovered_links = await discover_links_by_entities(
                    session,
                    ep_uuid,
                    limit=5,
                )
                logger.info(
                    "link_discovery_complete",
                    episode_id=episode_id,
                    links_found=len(discovered_links),
                )
            except Exception:
                logger.warning(
                    "link_discovery_failed",
                    episode_id=episode_id,
                    exc_info=True,
                )

    logger.info(
        "entity_extraction_complete",
        episode_id=episode_id,
        entities_count=len(extraction.entities),
        relationships_count=len(extraction.relationships),
    )
    return {
        "status": "ok",
        "episode_id": episode_id,
        "entities_count": len(extraction.entities),
        "relationships_count": len(extraction.relationships),
        "links_discovered": len(discovered_links),
    }


async def _run_commitment_extraction(ctx: dict, payload: dict) -> dict:
    """Extract commitments from an episode in the background."""
    episode_id = payload.get("episode_id")
    text_content = payload.get("text")

    if not text_content:
        logger.warning("commitment_extraction_no_text", episode_id=episode_id)
        return {"status": "skipped", "reason": "no text provided"}

    logger.info("commitment_extraction_task", episode_id=episode_id)

    settings = ctx.get("settings")
    if not settings:
        logger.error("commitment_extraction_no_settings")
        return {"status": "error", "message": "no settings in context"}

    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    if not session_factory:
        logger.error("commitment_extraction_no_session_factory")
        return {"status": "error", "message": "no session_factory in context"}

    from src.app.domain.services.commitments import extract_commitments
    from src.app.persistence.repositories.commitments import create_commitment

    client = ctx.get("llm_provider") or ctx.get("anthropic_client")
    commitments = await extract_commitments(text_content, client)

    # Persist commitments
    async with session_factory() as session:
        for c in commitments:
            await create_commitment(
                session,
                verbatim_text=c.verbatim_text,
                normalized_action=c.normalized_action,
                who_committed=c.who_committed,
                who_to=c.who_to,
                temporal_expression=c.temporal_expression,
                confidence_score=c.confidence,
            )
        await session.commit()

    logger.info(
        "commitment_extraction_complete",
        episode_id=episode_id,
        commitments_count=len(commitments),
    )
    return {
        "status": "ok",
        "episode_id": episode_id,
        "commitments_count": len(commitments),
    }


async def _run_notification(ctx: dict, payload: dict) -> dict:
    """Evaluate and potentially send a notification via Telegram."""
    message = payload.get("message", "")
    priority_str = payload.get("priority", "P2")
    category = payload.get("category", "system")

    notification = Notification(
        message=message,
        priority=Priority(priority_str),
        category=category,
    )

    if _fatigue_manager is None:
        logger.error("fatigue_manager_not_initialized")
        raise RuntimeError("Fatigue manager is not initialized.")

    should_send = await _fatigue_manager.evaluate(notification)

    logger.info(
        "notification_evaluated",
        priority=priority_str,
        category=category,
        should_deliver=should_send,
        pending_count=_fatigue_manager.pending_count if _fatigue_manager else 0,
        message_length=len(message),
    )

    if should_send:
        bot: Bot | None = ctx.get("bot")
        if bot:
            settings = ctx.get("settings")
            if settings:
                for uid in settings.allowed_user_ids:
                    try:
                        await bot.send_message(uid, message)
                    except Exception:
                        logger.exception("notification_send_failed", user_id=uid)
        logger.info("notification_sent", priority=priority_str, category=category)
    else:
        logger.info("notification_batched", priority=priority_str, category=category)

    return {"status": "ok", "delivered": should_send, "priority": priority_str}


async def _run_curation_task(ctx: dict, payload: dict) -> dict:
    """Run content curation pipeline as a background task."""
    await run_curation(ctx)
    return {"status": "ok", "task": "curation"}


async def _maybe_send_day_plan_closeout_prompt(ctx: dict) -> dict | None:
    """Prompt for end-of-day plan resolution when unfinished planned work remains."""
    settings = ctx.get("settings")
    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    if not settings or not session_factory:
        return None

    from src.app.core.conversation import ConversationContext
    from src.app.domain.services.day_plans import (
        build_evening_closeout_message,
        build_evening_review_session,
        day_plan_completion_status,
        load_latest_day_plan,
        planning_owner_user_id,
        planning_session_is_active,
        planning_source_date,
    )
    from src.app.workers.scheduled import _send_to_users

    owner_user_id = planning_owner_user_id(settings)
    source_date = planning_source_date(settings)
    async with session_factory() as session:
        latest_plan = await load_latest_day_plan(
            session,
            user_id=owner_user_id,
            source_date=source_date,
        )

    if latest_plan is None or latest_plan.plan.status == "reviewed":
        return None

    _completed, unresolved = day_plan_completion_status(latest_plan.plan)
    if not unresolved:
        return None

    try:
        conv_ctx = ConversationContext(redis_url=settings.redis_url.get_secret_value())
        existing_session = await conv_ctx.get_pending_planning_session(owner_user_id)
        if (
            existing_session is not None
            and existing_session.session_type == "evening_review"
            and planning_session_is_active(existing_session, settings=settings)
        ):
            return {"status": "skipped", "reason": "closeout session already active"}
        await conv_ctx.set_pending_planning_session(
            owner_user_id,
            build_evening_review_session(
                settings=settings,
                plan_artifact_id=latest_plan.artifact_id,
                unresolved_tasks=unresolved,
            ),
        )
        await _send_to_users(ctx, build_evening_closeout_message(latest_plan.plan))
    except Exception:
        logger.warning("day_plan_closeout_prompt_failed", exc_info=True)
        return {"status": "error", "reason": "closeout prompt failed"}

    return {"status": "ok", "unresolved_count": len(unresolved)}


async def _run_review_task(ctx: dict, payload: dict) -> dict:
    """Run a review (weekly/quarterly) as a background task."""
    review_type = payload.get("review_type", "weekly")
    logger.info("review_task_not_implemented", review_type=review_type)
    return {"status": "not_implemented", "review_type": review_type}
