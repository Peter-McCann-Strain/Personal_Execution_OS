"""Diary handler — timestamped entries, mood, interstitial journaling.

After creating an episode, runs three second-brain enrichment steps
(PARA classification, GTD processing, progressive summarization).
Failures propagate so hidden enrichment drift is visible.
"""

from __future__ import annotations

import asyncio

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.specialists.diary import process_diary_entry
from src.app.domain.constants import EpisodeType
from src.app.domain.models import ChatResponse, Intent, MessageInput
from src.app.domain.services.handlers._common import (
    enqueue_commitment_extraction,
    enqueue_entity_extraction,
    enqueue_reflection_pack_refresh,
)
from src.app.persistence.repositories.episodes import create_episode, update_episode
from src.app.second_brain.gtd_processor import process_gtd
from src.app.second_brain.para_classifier import classify_para
from src.app.second_brain.progressive_summary import generate_progressive_summary

logger = structlog.get_logger()


async def handle_diary(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    _intent: Intent,
) -> ChatResponse:
    """Process a diary/capture entry and trigger background entity extraction."""
    entry = await process_diary_entry(message.content, client)

    # Store in database
    episode = await create_episode(
        session,
        content=entry.content,
        summary=entry.summary,
        episode_type=EpisodeType.DIARY,
        source=message.source,
        para_category=entry.para_category,
        mood_score=entry.mood_score,
        energy_rating=entry.energy_rating,
        tags=entry.tags,
        people_mentioned=entry.people_mentioned,
    )
    await session.commit()

    logger.info("diary_entry_saved", episode_id=str(episode.id))

    try:
        await enqueue_reflection_pack_refresh("episode_diary_saved")
    except Exception as exc:
        logger.warning(
            "diary_reflection_pack_refresh_degraded",
            episode_id=str(episode.id),
            error=str(exc),
            exc_info=True,
        )

    # Trigger background entity extraction via ARQ if available
    try:
        await enqueue_entity_extraction(
            episode_id=str(episode.id),
            text_content=entry.content,
        )
    except Exception as exc:
        logger.warning(
            "diary_entity_extraction_degraded",
            episode_id=str(episode.id),
            error=str(exc),
            exc_info=True,
        )

    # Trigger background commitment extraction via ARQ if available
    await enqueue_commitment_extraction(
        episode_id=str(episode.id),
        text_content=entry.content,
    )

    # --- Second-brain enrichment ---
    enrichment = await _run_second_brain_enrichment(
        episode=episode,
        content=entry.content,
        current_para=entry.para_category,
        client=client,
        session=session,
    )

    response_metadata: dict = {
        "episode_id": str(episode.id),
        "para_category": enrichment.get("para_category") or entry.para_category,
        "mood_score": entry.mood_score,
        "tags": entry.tags,
    }
    if enrichment.get("gtd"):
        response_metadata["gtd"] = enrichment["gtd"]
    if enrichment.get("progressive_summary"):
        response_metadata["progressive_summary"] = True

    # Prefer the specialist reply; otherwise use the stored summary.
    # Strip forbidden openers the model occasionally produces despite prompt rules
    forbidden_openers = ("captured:", "got it", "noted.", "saved.", "noted,", "logged.")
    raw_reply = entry.user_reply or ""
    if raw_reply.lower().startswith(forbidden_openers):
        colon_idx = raw_reply.find(":")
        if colon_idx != -1 and colon_idx < 20:
            raw_reply = raw_reply[colon_idx + 1 :].strip()
    reply = raw_reply or f"{entry.summary}"

    return ChatResponse(
        content=reply,
        agent="diary",
        metadata=response_metadata,
    )


async def _run_second_brain_enrichment(
    episode: object,
    content: str,
    current_para: str | None,
    client: AsyncAnthropic,
    session: AsyncSession,
) -> dict:
    """Run PARA classification, GTD processing, and progressive summarization.

    All three run concurrently. Failures propagate.

    Returns a dict with keys: para_category, gtd, progressive_summary (any may be None).
    """
    episode_id = episode.id

    para_task = _enrich_para(content, current_para, client)
    gtd_task = _enrich_gtd(content, client)
    summary_task = _enrich_progressive_summary(content, client)

    para_result, gtd_result, summary_result = await asyncio.gather(
        para_task,
        gtd_task,
        summary_task,
    )

    result: dict = {}

    # --- PARA classification ---
    if para_result is not None:
        result["para_category"] = para_result
        await update_episode(session, episode_id, para_category=para_result)
        await session.commit()
        logger.info("para_category_updated", episode_id=str(episode_id), category=para_result)

    # --- GTD processing ---
    if gtd_result is not None:
        result["gtd"] = gtd_result

    # --- Progressive summarization ---
    if summary_result is not None:
        result["progressive_summary"] = True
        existing = episode.metadata_ or {}
        existing["progressive_summary"] = {
            "layer_2_passages": summary_result.layer_2_passages,
            "layer_3_highlights": summary_result.layer_3_highlights,
            "layer_4_summary": summary_result.layer_4_summary,
        }
        await update_episode(session, episode_id, metadata=existing)
        await session.commit()
        logger.info("progressive_summary_stored", episode_id=str(episode_id))

    return result


async def _enrich_para(
    content: str,
    current_para: str | None,
    client: AsyncAnthropic,
) -> str | None:
    """Classify PARA category if the diary specialist didn't assign one."""
    if current_para is not None:
        return None  # Already classified by specialist
    return await classify_para(content, client)


async def _enrich_gtd(content: str, client: AsyncAnthropic):
    """Run GTD processing on diary content."""
    return await process_gtd(content, client)


async def _enrich_progressive_summary(content: str, client: AsyncAnthropic):
    """Generate progressive summary layers for the diary content."""
    return await generate_progressive_summary(content, client)
