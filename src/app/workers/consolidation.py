"""Background memory consolidation — transforms episodic streams into reusable knowledge.

Runs daily via ARQ cron. Performs:
1. Topic clustering: Groups recent episodes by topic/entity overlap
2. Summary note creation: Creates higher-level summary notes from clusters
3. Link discovery: Finds connections between notes that weren't previously linked
4. Entity relationship updates: Updates entity graph based on new patterns
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.app.core.llm_helpers import call_and_parse_with_retry
from src.app.persistence.models import Note
from src.app.persistence.repositories.notes import create_note, create_note_link

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.app.config import Settings

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Pydantic models for LLM responses
# ---------------------------------------------------------------------------


class EpisodeCluster(BaseModel):
    """A cluster of related episodes grouped by topic."""

    topic_label: str = Field(description="Short label for the topic cluster")
    episode_indices: list[int] = Field(
        description="0-based indices of episodes belonging to this cluster"
    )
    summary: str = Field(description="Brief summary of what this cluster covers")


class ClusteringResult(BaseModel):
    """Result of LLM-based episode clustering."""

    clusters: list[EpisodeCluster] = Field(default_factory=list)


class ConsolidationSummary(BaseModel):
    """Summary note content generated from a cluster of episodes."""

    title: str = Field(description="Concise title for the summary note")
    content: str = Field(description="Consolidated summary of the episodes")
    tags: list[str] = Field(default_factory=list, description="Relevant tags")
    key_insight: str = Field(description="The single most important takeaway")


# ---------------------------------------------------------------------------
# Internal dataclass for passing clusters around
# ---------------------------------------------------------------------------


class _ResolvedCluster:
    """A cluster with resolved episode references."""

    def __init__(
        self,
        topic_label: str,
        summary: str,
        episodes: list[dict],
    ) -> None:
        self.topic_label = topic_label
        self.summary = summary
        self.episodes = episodes


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------


_CLUSTERING_SYSTEM_PROMPT = """\
You are a knowledge organiser for a personal assistant second brain.
You receive a list of recent diary episodes and must group them into
2-5 topic clusters based on thematic similarity.

<rules>
- Each episode should appear in exactly one cluster
- Clusters should be meaningful — not just "miscellaneous"
- If all episodes cover the same topic, return a single cluster
- Use clear, descriptive topic labels
- Do not create clusters with fewer than 1 episode
</rules>

<output_format>
Respond with valid JSON:
{
  "clusters": [
    {
      "topic_label": "Short topic label",
      "episode_indices": [0, 2, 4],
      "summary": "Brief description of what these episodes cover"
    }
  ]
}
</output_format>"""


_SUMMARY_SYSTEM_PROMPT = """\
You are a knowledge synthesiser for a personal assistant second brain.
Given a cluster of related episodes, create a consolidated summary note
that captures the key insights and patterns.

<rules>
- Write in a clear, concise style
- Focus on insights and patterns, not just restating facts
- The title should be specific and descriptive
- Tags should be 2-5 relevant keywords
- The key_insight should be one actionable or notable takeaway
</rules>

<output_format>
Respond with valid JSON:
{
  "title": "Concise descriptive title",
  "content": "Consolidated summary with key insights and patterns",
  "tags": ["tag1", "tag2"],
  "key_insight": "The single most important takeaway"
}
</output_format>"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_consolidation(ctx: dict) -> dict:
    """Daily consolidation job. Called by ARQ scheduler."""
    logger.info("consolidation_started")

    session_factory = ctx.get("session_factory")
    settings = ctx.get("settings")

    if not session_factory:
        msg = "consolidation_missing_session_factory"
        raise RuntimeError(msg)

    if not settings:
        msg = "consolidation_missing_settings"
        raise RuntimeError(msg)

    if not settings.consolidation_enabled:
        logger.info("consolidation_disabled")
        return {"status": "disabled"}

    async with session_factory() as session:
        # 1. Get recent episodes
        recent = await _get_recent_episodes(session, hours=settings.consolidation_lookback_hours)
        if len(recent) < 3:
            logger.info("consolidation_skipped_few_episodes", count=len(recent))
            return {"status": "skipped", "reason": "too_few_episodes", "episode_count": len(recent)}

        # 2. Cluster by topic
        clusters = await _cluster_episodes(recent, settings)

        # 3. Create summary notes for significant clusters
        notes_created = 0
        for cluster in clusters:
            if len(cluster.episodes) >= settings.consolidation_min_cluster_size:
                await _create_summary_note(session, cluster, settings)
                notes_created += 1

        # 4. Discover new links between existing notes
        links_created = await _discover_links(session, settings)

        await session.commit()

        result = {
            "status": "completed",
            "episodes_processed": len(recent),
            "clusters_found": len(clusters),
            "notes_created": notes_created,
            "links_discovered": links_created,
        }
        logger.info("consolidation_completed", **result)
        return result


# ---------------------------------------------------------------------------
# Step 1: Fetch recent episodes
# ---------------------------------------------------------------------------


async def _get_recent_episodes(
    session: AsyncSession,
    hours: int = 24,
) -> list[dict]:
    """Query episodes from the last N hours, returning dicts with content and metadata."""
    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(hours=hours)

    result = await session.execute(
        text("""
            SELECT id, content, summary, episode_type, para_category,
                   mood_score, energy_rating, tags, people_mentioned,
                   created_at
            FROM episodes
            WHERE created_at >= :cutoff AND created_at <= :now
            ORDER BY created_at ASC
        """),
        {"cutoff": cutoff, "now": now},
    )
    return [dict(row) for row in result.mappings().all()]


# ---------------------------------------------------------------------------
# Step 2: Cluster episodes by topic using LLM
# ---------------------------------------------------------------------------


def _format_episodes_for_clustering(episodes: list[dict]) -> str:
    """Format episode data for the clustering LLM call."""
    lines = [f"Recent episodes ({len(episodes)} total):\n"]

    for i, ep in enumerate(episodes):
        date_str = (
            ep["created_at"].strftime("%Y-%m-%d %H:%M") if ep.get("created_at") else "unknown"
        )
        summary = ep.get("summary") or ep.get("content", "")[:200]
        tags_str = ", ".join(ep["tags"]) if ep.get("tags") else "none"
        people = ", ".join(ep["people_mentioned"]) if ep.get("people_mentioned") else "none"

        lines.append(f"[{i}] ({date_str}) tags=[{tags_str}] people=[{people}]")
        lines.append(f"    {summary}")
        lines.append("")

    return "\n".join(lines)


async def _cluster_episodes(
    episodes: list[dict],
    settings: Settings,
) -> list[_ResolvedCluster]:
    """Use LLM (Haiku) to cluster episodes by topic."""
    client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
    episode_text = _format_episodes_for_clustering(episodes)

    try:
        result = await call_and_parse_with_retry(
            client,
            model=settings.classifier_model,
            max_tokens=settings.classifier_max_tokens,
            system=_CLUSTERING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": episode_text}],
            response_model=ClusteringResult,
            error_context="consolidation_clustering",
            inject_personality=False,
        )
    except Exception:
        logger.exception("consolidation_clustering_failed")
        raise

    # Resolve indices to actual episode dicts
    resolved: list[_ResolvedCluster] = []
    for cluster in result.clusters:
        cluster_episodes = []
        for idx in cluster.episode_indices:
            if 0 <= idx < len(episodes):
                cluster_episodes.append(episodes[idx])
        if cluster_episodes:
            resolved.append(
                _ResolvedCluster(
                    topic_label=cluster.topic_label,
                    summary=cluster.summary,
                    episodes=cluster_episodes,
                )
            )

    logger.info(
        "consolidation_clustering_done",
        total_clusters=len(resolved),
        episode_count=len(episodes),
    )
    return resolved


# ---------------------------------------------------------------------------
# Step 3: Create summary notes
# ---------------------------------------------------------------------------


async def _create_summary_note(
    session: AsyncSession,
    cluster: _ResolvedCluster,
    settings: Settings,
) -> Note:
    """Create a consolidated summary note from a cluster of episodes."""
    client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())

    # Build context from cluster episodes
    lines = [f"Topic: {cluster.topic_label}\n"]
    for ep in cluster.episodes:
        date_str = (
            ep["created_at"].strftime("%Y-%m-%d %H:%M") if ep.get("created_at") else "unknown"
        )
        content = ep.get("summary") or ep.get("content", "")[:300]
        lines.append(f"[{date_str}] {content}")
    episode_text = "\n".join(lines)

    try:
        summary_result = await call_and_parse_with_retry(
            client,
            model=settings.classifier_model,
            max_tokens=settings.summary_max_tokens,
            system=_SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": episode_text}],
            response_model=ConsolidationSummary,
            error_context="consolidation_summary",
            inject_personality=False,
        )
    except Exception:
        logger.exception(
            "consolidation_summary_failed",
            topic=cluster.topic_label,
        )
        raise

    # Build metadata linking back to source episodes
    source_episode_ids = [str(ep["id"]) for ep in cluster.episodes if ep.get("id")]

    # Build full content with key insight
    full_content = (
        f"{summary_result.content}\n\n"
        f"**Key Insight:** {summary_result.key_insight}\n\n"
        f"_Consolidated from {len(cluster.episodes)} episodes "
        f"on {datetime.now(tz=UTC).strftime('%Y-%m-%d')}_"
    )

    note = await create_note(
        session,
        title=summary_result.title,
        content=full_content,
        note_type="consolidation",
        tags=summary_result.tags,
    )

    logger.info(
        "consolidation_note_created",
        note_id=str(note.id),
        source_episodes=len(source_episode_ids),
    )
    return note


# ---------------------------------------------------------------------------
# Step 4: Discover links between recent notes
# ---------------------------------------------------------------------------


async def _discover_links(
    session: AsyncSession,
    settings: Settings,
) -> int:
    """Find and create links between recent notes using embedding similarity.

    Looks at notes created in the last 7 days and links them to other notes
    when embedding similarity is high enough.
    """
    now = datetime.now(tz=UTC)
    week_ago = now - timedelta(days=7)

    # Get recent notes with embeddings
    result = await session.execute(
        text("""
            SELECT id, title, embedding
            FROM notes
            WHERE created_at >= :week_ago
              AND embedding IS NOT NULL
        """),
        {"week_ago": week_ago},
    )
    recent_notes = [dict(row) for row in result.mappings().all()]

    if not recent_notes:
        logger.info("consolidation_no_recent_notes_for_linking")
        return 0

    links_created = 0

    for note_row in recent_notes:
        note_id = note_row["id"]

        # Find similar notes by embedding (excluding self)
        similar_result = await session.execute(
            text("""
                SELECT n2.id, n2.title,
                       1 - (n1.embedding <=> n2.embedding) AS similarity
                FROM notes n1
                JOIN notes n2 ON n1.id != n2.id
                WHERE n1.id = :note_id
                  AND n1.embedding IS NOT NULL
                  AND n2.embedding IS NOT NULL
                  AND 1 - (n1.embedding <=> n2.embedding) > 0.7
                ORDER BY n1.embedding <=> n2.embedding
                LIMIT 5
            """),
            {"note_id": note_id},
        )
        similar_notes = [dict(row) for row in similar_result.mappings().all()]

        for similar in similar_notes:
            target_id = similar["id"]
            similarity = similar["similarity"]

            await create_note_link(
                session,
                source_note_id=note_id,
                target_note_id=target_id,
                link_reason=f"Embedding similarity: {similarity:.2f}",
                similarity_score=float(similarity),
                auto_discovered=True,
            )
            links_created += 1

    logger.info(
        "consolidation_links_discovered",
        recent_notes_checked=len(recent_notes),
        links_created=links_created,
    )
    return links_created
