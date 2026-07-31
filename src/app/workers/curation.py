"""Content curation pipeline for RSS, trending topics, and digest generation."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.app.core.exceptions import ConfigError, DatabaseError, EmbeddingError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger()

# Redis key for storing the latest curated digest
_REDIS_KEY_CURATED_DIGEST = "curation:latest_digest"
# TTL for cached digest (24 hours)
_DIGEST_TTL_SECONDS = 86400


class CuratedItem(BaseModel):
    """A single curated content item."""

    title: str
    url: str
    source: str
    snippet: str = Field(default="", description="Brief excerpt or description")
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    published_at: datetime | None = None


class CurationResult(BaseModel):
    """Result of a curation run."""

    items: list[CuratedItem] = Field(default_factory=list)
    digest: str = Field(default="")
    rss_count: int = 0
    trending_count: int = 0
    filtered_count: int = 0


async def run_curation(ctx: dict) -> None:
    """Main curation pipeline.

    1. Poll RSS feeds (feedparser)
    2. Search Tavily for trending topics matching user interests
    3. Score relevance using embedding similarity
    4. Format curated digest for morning briefing
    5. Store digest in Redis for morning briefing to pick up
    """
    logger.info("curation_pipeline_started")

    settings = ctx.get("settings")
    if not settings:
        raise ConfigError("Curation settings are not available.")

    # Step 1: Poll RSS feeds
    rss_items = await _poll_rss_feeds(ctx)

    # Step 2: Search trending topics (if Tavily configured)
    trending_items = await _search_trending_topics(ctx)

    # Combine all items
    all_items = rss_items + trending_items
    if not all_items:
        logger.info("curation_no_items_found")
        return

    # Step 3: Score relevance (if Ollama configured)
    scored_items = await _score_relevance(ctx, all_items)

    # Step 4: Format digest
    digest = _format_digest(scored_items)

    # Step 5: Store in Redis for morning briefing
    await _store_digest(ctx, digest)

    logger.info(
        "curation_pipeline_completed",
        rss_items=len(rss_items),
        trending_items=len(trending_items),
        scored_items=len(scored_items),
        digest_length=len(digest),
    )


async def _poll_rss_feeds(ctx: dict) -> list[CuratedItem]:
    """Poll active RSS feeds using feedparser."""
    try:
        import feedparser
    except ImportError as exc:
        raise ConfigError("feedparser is required for content curation.") from exc

    feeds = await _load_rss_feeds(ctx)

    items: list[CuratedItem] = []
    cutoff = datetime.now(tz=UTC) - timedelta(hours=24)

    for feed_config in feeds:
        feed_name = feed_config["name"]
        feed_url = feed_config["url"]
        try:
            # feedparser.parse is synchronous — run in thread with timeout
            # to avoid blocking the async event loop on slow/unresponsive feeds
            parsed = await asyncio.wait_for(
                asyncio.to_thread(feedparser.parse, feed_url),
                timeout=15.0,
            )
            if parsed.bozo and not parsed.entries:
                error = str(parsed.bozo_exception) if parsed.bozo_exception else "unknown"
                raise RuntimeError(f"RSS feed '{feed_name}' could not be parsed: {error}")

            for entry in parsed.entries[:10]:  # Cap per-feed to avoid flooding
                # Parse published date
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    with contextlib.suppress(TypeError, ValueError):
                        published = datetime(*entry.published_parsed[:6], tzinfo=UTC)

                # Skip entries older than 24 hours if we have a date
                if published and published < cutoff:
                    continue

                title = getattr(entry, "title", "Untitled")
                link = getattr(entry, "link", "")
                snippet = getattr(entry, "summary", "")[:300] if hasattr(entry, "summary") else ""

                items.append(
                    CuratedItem(
                        title=title,
                        url=link,
                        source=feed_name,
                        snippet=snippet,
                        published_at=published,
                    )
                )

            logger.info("curation_feed_polled", feed=feed_name, items=len(parsed.entries))
        except Exception as exc:
            logger.exception("curation_feed_failed", feed=feed_name)
            raise RuntimeError(f"RSS feed '{feed_name}' failed: {exc}") from exc

    logger.info("curation_rss_complete", total_items=len(items))
    return items


async def _search_trending_topics(ctx: dict) -> list[CuratedItem]:
    """Search for trending content matching user interests via Tavily.

    Returns an empty list only when Tavily is intentionally not configured.
    """
    settings = ctx.get("settings")
    if not settings or not settings.tavily_configured:
        logger.info("curation_tavily_not_configured")
        return []

    from src.app.agents.tools.web_search import TavilySearch

    tavily = TavilySearch(api_key=settings.tavily_api_key.get_secret_value())
    items: list[CuratedItem] = []

    # Get user interests — try extracting from recent entities, fall back to defaults
    interests = await _get_user_interests(ctx)

    # Search for 2-3 interest topics to stay within rate limits
    search_queries = interests[:3]

    try:
        for query in search_queries:
            try:
                results = await tavily.search(
                    query=f"latest news: {query}",
                    max_results=3,
                    search_depth="basic",
                )
                for r in results:
                    items.append(
                        CuratedItem(
                            title=r.get("title", ""),
                            url=r.get("url", ""),
                            source="Tavily",
                            snippet=r.get("content", "")[:300],
                            relevance_score=r.get("score", 0.0),
                        )
                    )
            except Exception as exc:
                logger.exception(
                    "curation_tavily_search_failed",
                    query_length=len(query),
                )
                raise RuntimeError(f"Tavily search failed for query '{query}': {exc}") from exc
    finally:
        await tavily.close()

    logger.info("curation_trending_complete", total_items=len(items))
    return items


async def _get_user_interests(ctx: dict) -> list[str]:
    """Extract user interests from recent entity frequency."""
    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    if not session_factory:
        raise ConfigError("Curation requires a session factory to load user interests.")

    try:
        async with session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT name, mention_count
                    FROM entities
                    WHERE entity_type IN ('topic', 'technology', 'concept')
                    ORDER BY mention_count DESC
                    LIMIT 10
                """)
            )
            entities = result.mappings().all()
            if entities:
                interests = [e["name"] for e in entities]
                logger.info("curation_interests_from_entities", count=len(interests))
                return interests
    except Exception as exc:
        logger.exception("curation_entity_interests_load_failed")
        raise DatabaseError(f"curation interests load failed: {exc}") from exc

    raise ConfigError("No user interests are available from the entities table.")


async def _score_relevance(
    ctx: dict,
    items: list[CuratedItem],
) -> list[CuratedItem]:
    """Score article relevance using embedding similarity."""
    if not items:
        return []

    settings = ctx.get("settings")
    if not settings:
        raise ConfigError("Curation settings are not available for relevance scoring.")

    try:
        from src.app.core.embeddings import OllamaEmbeddings

        embedder = OllamaEmbeddings(
            host=settings.ollama_host,
            model=settings.ollama_embed_model,
        )
    except Exception as exc:
        logger.exception("curation_embeddings_unavailable")
        raise EmbeddingError(f"curation embeddings unavailable: {exc}") from exc

    try:
        # Get interest embeddings
        interests = await _get_user_interests(ctx)
        interest_text = " ".join(interests)
        interest_embedding = await embedder.embed_single(interest_text)

        # Embed item titles + snippets
        item_texts = [f"{item.title}. {item.snippet}" for item in items]
        item_embeddings = await embedder.embed(item_texts)

        # Score by cosine similarity
        for item, item_emb in zip(items, item_embeddings, strict=True):
            similarity = _cosine_similarity(interest_embedding, item_emb)
            # Tavily items already have a score — blend it
            if item.relevance_score > 0:
                item.relevance_score = (item.relevance_score + similarity) / 2
            else:
                item.relevance_score = similarity

        # Filter to relevance > 0.7 and sort descending
        scored = [item for item in items if item.relevance_score > 0.7]
        scored.sort(key=lambda x: x.relevance_score, reverse=True)

        logger.info(
            "curation_scoring_complete",
            total=len(items),
            above_threshold=len(scored),
        )

        # If nothing passed the threshold, return top 5 anyway
        if not scored:
            items.sort(key=lambda x: x.relevance_score, reverse=True)
            return items[:5]

        return scored[:10]
    except Exception as exc:
        logger.exception("curation_scoring_failed")
        raise EmbeddingError(f"curation relevance scoring failed: {exc}") from exc
    finally:
        await embedder.close()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _format_digest(items: list[CuratedItem]) -> str:
    """Format top curated items as a readable digest string."""
    if not items:
        return ""

    lines = [f"CURATED CONTENT ({len(items)} items):\n"]

    for i, item in enumerate(items[:10], 1):
        score_pct = int(item.relevance_score * 100) if item.relevance_score > 0 else 0
        source_tag = f" [{item.source}]" if item.source else ""
        lines.append(f"  {i}. {item.title}{source_tag}")
        if item.snippet:
            # Truncate snippet to keep digest concise
            snippet = item.snippet[:150].rstrip()
            if len(item.snippet) > 150:
                snippet += "..."
            lines.append(f"     {snippet}")
        if item.url:
            lines.append(f"     {item.url}")
        if score_pct > 0:
            lines.append(f"     Relevance: {score_pct}%")
        lines.append("")

    return "\n".join(lines)


async def get_latest_digest(ctx: dict) -> str:
    """Retrieve the latest curated digest from Redis.

    Returns an empty string only when no digest is stored.
    """
    from src.app.core.redis import redis_pool

    settings = ctx.get("settings")
    if not settings:
        raise ConfigError("Curation settings are not available for digest retrieval.")

    try:
        async with redis_pool(settings.redis_url.get_secret_value()) as conn:
            digest = await conn.get(_REDIS_KEY_CURATED_DIGEST)
            return digest or ""
    except Exception as exc:
        logger.exception("curation_digest_retrieval_failed")
        raise RuntimeError(f"curation digest retrieval failed: {exc}") from exc


async def _store_digest(ctx: dict, digest: str) -> None:
    """Store curated digest in Redis for the morning briefing to pick up."""
    if not digest:
        return

    from src.app.core.redis import redis_pool

    settings = ctx.get("settings")
    if not settings:
        raise ConfigError("Curation settings are not available for digest storage.")

    try:
        async with redis_pool(settings.redis_url.get_secret_value()) as conn:
            await conn.set(_REDIS_KEY_CURATED_DIGEST, digest, ex=_DIGEST_TTL_SECONDS)
            logger.info("curation_digest_stored", length=len(digest))
    except Exception as exc:
        logger.exception("curation_digest_store_failed")
        raise RuntimeError(f"curation digest store failed: {exc}") from exc


async def _load_rss_feeds(ctx: dict) -> list[dict[str, str]]:
    """Load active RSS feeds from the database."""
    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    if not session_factory:
        raise ConfigError("Curation requires a session factory to load RSS content sources.")

    try:
        async with session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT name, url FROM content_sources
                    WHERE source_type = 'rss' AND active = true
                    ORDER BY name ASC
                """)
            )
            feeds = [{"name": row["name"], "url": row["url"]} for row in result.mappings().all()]
    except Exception as exc:
        logger.exception("curation_content_sources_load_failed")
        raise DatabaseError(f"curation content source load failed: {exc}") from exc

    if not feeds:
        raise ConfigError("No active RSS content sources are configured.")

    logger.info("curation_loaded_feeds_from_db", count=len(feeds))
    return feeds
