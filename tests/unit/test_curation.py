"""Tests for content curation pipeline."""

from datetime import UTC, datetime, timedelta
from time import struct_time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.exceptions import ConfigError, DatabaseError, EmbeddingError
from src.app.workers.curation import (
    CuratedItem,
    _cosine_similarity,
    _format_digest,
    _get_user_interests,
    _load_rss_feeds,
    _poll_rss_feeds,
    _score_relevance,
    _search_trending_topics,
    _store_digest,
    get_latest_digest,
    run_curation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    *,
    with_settings: bool = True,
    with_session_factory: bool = False,
    tavily_configured: bool = False,
    session_factory_results: list[list[dict]] | None = None,
) -> dict:
    ctx: dict = {}
    if with_settings:
        settings = MagicMock()
        settings.anthropic_api_key.get_secret_value.return_value = "sk-test"
        settings.tavily_configured = tavily_configured
        settings.tavily_api_key.get_secret_value.return_value = "tvly-test"
        settings.ollama_host = "http://localhost:11434"
        settings.ollama_embed_model = "nomic-embed-text:v2-moe"
        settings.redis_url = MagicMock(get_secret_value=lambda: "redis://localhost:6379")
        ctx["settings"] = settings
    if with_session_factory:
        if session_factory_results is not None:
            # Support sequential query results
            execute_results = []
            for rows in session_factory_results:
                mock_result = MagicMock()
                mock_mappings = MagicMock()
                mock_mappings.all.return_value = rows
                mock_result.mappings.return_value = mock_mappings
                execute_results.append(mock_result)
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(side_effect=execute_results)
        else:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.mappings.return_value.all.return_value = []
            mock_session.execute = AsyncMock(return_value=mock_result)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=False)

        factory = MagicMock()
        factory.return_value = cm
        ctx["session_factory"] = factory
    return ctx


def _sample_items(count: int = 5) -> list[CuratedItem]:
    return [
        CuratedItem(
            title=f"Article {i}",
            url=f"https://example.com/{i}",
            source="Test Feed",
            snippet=f"This is snippet for article {i}",
            relevance_score=round(0.5 + (i * 0.5 / max(count - 1, 1)), 2),
            published_at=datetime(2026, 3, 10, 12, i, tzinfo=UTC),
        )
        for i in range(count)
    ]


def _make_feed_entry(
    *,
    title: str = "Test Article",
    link: str = "https://example.com/test",
    summary: str = "A test article summary",
    published_parsed: struct_time | None = None,
):
    """Create a mock feedparser entry."""
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.summary = summary
    if published_parsed is not None:
        entry.published_parsed = published_parsed
    else:
        # Default to recent time
        now = datetime.now(tz=UTC)
        entry.published_parsed = struct_time(
            (now.year, now.month, now.day, now.hour, now.minute, now.second, 0, 0, 0)
        )
    return entry


def _make_parsed_feed(entries=None, bozo=False, bozo_exception=None):
    """Create a mock feedparser.parse() result."""
    feed = MagicMock()
    feed.entries = entries or []
    feed.bozo = bozo
    feed.bozo_exception = bozo_exception
    return feed


# ---------------------------------------------------------------------------
# CuratedItem model
# ---------------------------------------------------------------------------


class TestCuratedItemModel:
    def test_basic_creation(self):
        item = CuratedItem(title="Test", url="https://example.com", source="Feed")
        assert item.title == "Test"
        assert item.relevance_score == 0.0

    def test_with_all_fields(self):
        item = CuratedItem(
            title="AI News",
            url="https://example.com/ai",
            source="HN",
            snippet="Latest AI developments",
            relevance_score=0.85,
            published_at=datetime(2026, 3, 10, tzinfo=UTC),
        )
        assert item.relevance_score == 0.85


# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 2.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(_cosine_similarity(a, b) + 1.0) < 1e-6


# ---------------------------------------------------------------------------
# _format_digest
# ---------------------------------------------------------------------------


class TestFormatDigest:
    def test_empty_items(self):
        assert _format_digest([]) == ""

    def test_formats_items_with_title_and_url(self):
        items = _sample_items(3)
        digest = _format_digest(items)
        assert "CURATED CONTENT" in digest
        assert "Article 0" in digest
        assert "https://example.com/0" in digest

    def test_includes_relevance_score(self):
        items = [
            CuratedItem(
                title="Scored Article",
                url="https://example.com",
                source="Test",
                relevance_score=0.85,
            )
        ]
        digest = _format_digest(items)
        assert "85%" in digest

    def test_caps_at_ten_items(self):
        items = _sample_items(15)
        digest = _format_digest(items)
        # Should show items 1-10, not 11-15
        assert "1." in digest
        assert "10." in digest

    def test_truncates_long_snippets(self):
        items = [
            CuratedItem(
                title="Long",
                url="https://example.com",
                source="Test",
                snippet="x" * 300,
            )
        ]
        digest = _format_digest(items)
        assert "..." in digest


# ---------------------------------------------------------------------------
# _load_rss_feeds
# ---------------------------------------------------------------------------


class TestLoadRssFeeds:
    async def test_requires_session_factory(self):
        with pytest.raises(ConfigError, match="session factory"):
            await _load_rss_feeds(_make_ctx(with_session_factory=False))

    async def test_returns_feeds_from_db(self):
        feeds = [
            {"name": "Custom Feed", "url": "https://custom.example.com/rss"},
        ]
        result = await _load_rss_feeds(
            _make_ctx(with_session_factory=True, session_factory_results=[feeds])
        )
        assert result == feeds

    async def test_raises_on_db_failure(self):
        ctx = _make_ctx(with_session_factory=True)
        factory = ctx["session_factory"]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("content_sources missing"))
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = cm

        with pytest.raises(DatabaseError, match="content source load failed"):
            await _load_rss_feeds(ctx)

    async def test_raises_when_no_feeds_exist(self):
        with pytest.raises(ConfigError, match="No active RSS content sources"):
            await _load_rss_feeds(
                _make_ctx(with_session_factory=True, session_factory_results=[[]])
            )


# ---------------------------------------------------------------------------
# _get_user_interests
# ---------------------------------------------------------------------------


class TestGetUserInterests:
    async def test_requires_session_factory(self):
        with pytest.raises(ConfigError, match="session factory"):
            await _get_user_interests(_make_ctx(with_session_factory=False))

    async def test_returns_interests_from_entities(self):
        """When entities exist in DB, should return entity names instead of defaults."""
        entity_rows = [
            {"name": "kubernetes", "mention_count": 15},
            {"name": "rust programming", "mention_count": 10},
            {"name": "LLM agents", "mention_count": 8},
        ]
        ctx = _make_ctx(with_session_factory=True, session_factory_results=[entity_rows])
        interests = await _get_user_interests(ctx)
        assert interests == ["kubernetes", "rust programming", "LLM agents"]

    async def test_raises_on_db_exception(self):
        """When DB query raises, the curation job should fail loudly."""
        ctx = _make_ctx(with_session_factory=True)
        factory = ctx["session_factory"]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("DB down"))
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = cm
        with pytest.raises(DatabaseError, match="interests load failed"):
            await _get_user_interests(ctx)

    async def test_raises_when_no_interests_exist(self):
        with pytest.raises(ConfigError, match="No user interests"):
            await _get_user_interests(
                _make_ctx(with_session_factory=True, session_factory_results=[[]])
            )


# ---------------------------------------------------------------------------
# _poll_rss_feeds
# ---------------------------------------------------------------------------


class TestPollRssFeeds:
    async def test_raises_without_feedparser(self):
        """When feedparser is not importable, curation should fail loudly."""
        import sys

        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "Test Feed", "url": "https://example.com/rss"}]],
        )
        # Temporarily hide feedparser from import system
        real_module = sys.modules.get("feedparser")
        sys.modules["feedparser"] = None  # type: ignore[assignment]
        try:
            with pytest.raises(ConfigError, match="feedparser"):
                await _poll_rss_feeds(ctx)
        finally:
            if real_module is not None:
                sys.modules["feedparser"] = real_module
            else:
                sys.modules.pop("feedparser", None)

    async def test_parses_rss_entries(self):
        """Should parse entries from RSS feeds and return CuratedItems."""
        now = datetime.now(tz=UTC)
        recent_time = struct_time(
            (now.year, now.month, now.day, now.hour, now.minute, now.second, 0, 0, 0)
        )
        entries = [
            _make_feed_entry(
                title="Fresh Article",
                link="https://example.com/fresh",
                summary="This is a fresh article",
                published_parsed=recent_time,
            ),
        ]
        parsed_feed = _make_parsed_feed(entries=entries)

        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "Test Feed", "url": "https://example.com/rss"}]],
        )
        with patch("feedparser.parse", return_value=parsed_feed):
            result = await _poll_rss_feeds(ctx)

        assert len(result) >= 1
        found = [item for item in result if item.title == "Fresh Article"]
        assert len(found) >= 1
        assert found[0].url == "https://example.com/fresh"

    async def test_skips_old_entries(self):
        """Entries older than 24 hours with a published date should be skipped."""
        old_time = datetime.now(tz=UTC) - timedelta(hours=48)
        old_struct = struct_time(
            (
                old_time.year,
                old_time.month,
                old_time.day,
                old_time.hour,
                old_time.minute,
                old_time.second,
                0,
                0,
                0,
            )
        )
        entries = [
            _make_feed_entry(
                title="Old Article",
                link="https://example.com/old",
                published_parsed=old_struct,
            ),
        ]
        parsed_feed = _make_parsed_feed(entries=entries)

        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "Test Feed", "url": "https://example.com/rss"}]],
        )
        with patch("feedparser.parse", return_value=parsed_feed):
            result = await _poll_rss_feeds(ctx)

        # All entries from all 5 default feeds should be old
        old_titles = [item for item in result if item.title == "Old Article"]
        assert len(old_titles) == 0

    async def test_handles_bozo_feed_with_no_entries(self):
        """A bozo feed with no entries should fail loudly."""
        parsed_feed = _make_parsed_feed(entries=[], bozo=True, bozo_exception=Exception("bad XML"))

        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "Test Feed", "url": "https://example.com/rss"}]],
        )
        with (
            patch("feedparser.parse", return_value=parsed_feed),
            pytest.raises(RuntimeError, match="could not be parsed"),
        ):
            await _poll_rss_feeds(ctx)

    async def test_handles_feed_exception(self):
        """If feedparser.parse raises, the curation job should fail."""
        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "Test Feed", "url": "https://example.com/rss"}]],
        )
        with (
            patch("feedparser.parse", side_effect=RuntimeError("network error")),
            pytest.raises(RuntimeError, match="network error"),
        ):
            await _poll_rss_feeds(ctx)

    async def test_loads_custom_feeds_from_db(self):
        """When DB has custom feeds, should use those instead of defaults."""
        now = datetime.now(tz=UTC)
        recent_time = struct_time(
            (now.year, now.month, now.day, now.hour, now.minute, now.second, 0, 0, 0)
        )
        db_feeds = [
            {"name": "Custom Feed", "url": "https://custom.example.com/rss"},
        ]
        ctx = _make_ctx(with_session_factory=True, session_factory_results=[db_feeds])

        entry = _make_feed_entry(
            title="Custom Article",
            link="https://custom.example.com/1",
            published_parsed=recent_time,
        )
        parsed_feed = _make_parsed_feed(entries=[entry])

        with patch("feedparser.parse", return_value=parsed_feed):
            result = await _poll_rss_feeds(ctx)

        # Should have parsed from custom feed (only 1 feed, not 5 defaults)
        custom_items = [item for item in result if item.source == "Custom Feed"]
        assert len(custom_items) >= 1

    async def test_raises_on_empty_db_feeds(self):
        """When DB returns no feeds, curation should not substitute defaults."""
        ctx = _make_ctx(with_session_factory=True, session_factory_results=[[]])
        with pytest.raises(ConfigError, match="No active RSS content sources"):
            await _poll_rss_feeds(ctx)

    async def test_db_exception_raises(self):
        """When DB query raises, curation should fail instead of substituting defaults."""
        ctx = _make_ctx(with_session_factory=True)
        factory = ctx["session_factory"]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("content_sources missing"))
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = cm
        with pytest.raises(DatabaseError, match="content source load failed"):
            await _poll_rss_feeds(ctx)

    async def test_entry_without_published_date(self):
        """Entries without published_parsed should still be included."""
        entry = MagicMock()
        entry.title = "No Date Article"
        entry.link = "https://example.com/nodate"
        entry.summary = "Summary text"
        entry.published_parsed = None

        parsed_feed = _make_parsed_feed(entries=[entry])

        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "Test Feed", "url": "https://example.com/rss"}]],
        )
        with patch("feedparser.parse", return_value=parsed_feed):
            result = await _poll_rss_feeds(ctx)

        nodate_items = [item for item in result if item.title == "No Date Article"]
        assert len(nodate_items) >= 1
        assert nodate_items[0].published_at is None

    async def test_entry_without_summary(self):
        """Entries without summary attribute should get empty snippet."""
        now = datetime.now(tz=UTC)
        recent_time = struct_time(
            (now.year, now.month, now.day, now.hour, now.minute, now.second, 0, 0, 0)
        )
        entry = MagicMock(spec=["title", "link", "published_parsed"])
        entry.title = "No Summary"
        entry.link = "https://example.com/nosummary"
        entry.published_parsed = recent_time

        parsed_feed = _make_parsed_feed(entries=[entry])

        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "Test Feed", "url": "https://example.com/rss"}]],
        )
        with patch("feedparser.parse", return_value=parsed_feed):
            result = await _poll_rss_feeds(ctx)

        no_summary = [item for item in result if item.title == "No Summary"]
        assert len(no_summary) >= 1
        assert no_summary[0].snippet == ""

    async def test_caps_entries_per_feed(self):
        """Should cap at 10 entries per feed."""
        now = datetime.now(tz=UTC)
        recent_time = struct_time(
            (now.year, now.month, now.day, now.hour, now.minute, now.second, 0, 0, 0)
        )
        entries = [
            _make_feed_entry(
                title=f"Article {i}",
                link=f"https://example.com/{i}",
                published_parsed=recent_time,
            )
            for i in range(20)
        ]
        parsed_feed = _make_parsed_feed(entries=entries)

        # Use a single custom feed via DB to avoid 5x multiplication
        db_feeds = [{"name": "Big Feed", "url": "https://big.example.com/rss"}]
        ctx = _make_ctx(with_session_factory=True, session_factory_results=[db_feeds])

        with patch("feedparser.parse", return_value=parsed_feed):
            result = await _poll_rss_feeds(ctx)

        # Should have at most 10 from the single feed
        assert len(result) <= 10


# ---------------------------------------------------------------------------
# _search_trending_topics
# ---------------------------------------------------------------------------


class TestSearchTrendingTopics:
    async def test_skips_when_not_configured(self):
        ctx = _make_ctx(tavily_configured=False)
        result = await _search_trending_topics(ctx)
        assert result == []

    async def test_returns_items_when_configured(self):
        ctx = _make_ctx(
            tavily_configured=True,
            with_session_factory=True,
            session_factory_results=[[{"name": "llm agents", "mention_count": 5}]],
        )

        mock_search = AsyncMock(
            return_value=[
                {
                    "title": "AI News",
                    "url": "https://example.com",
                    "content": "stuff",
                    "score": 0.9,
                },
            ]
        )
        mock_close = AsyncMock()

        with patch("src.app.agents.tools.web_search.TavilySearch") as mock_tavily:
            instance = MagicMock()
            instance.search = mock_search
            instance.close = mock_close
            mock_tavily.return_value = instance

            result = await _search_trending_topics(ctx)

        assert len(result) > 0
        assert result[0].title == "AI News"

    async def test_skips_without_settings(self):
        """Should return [] when no settings present."""
        result = await _search_trending_topics({})
        assert result == []

    async def test_handles_search_exception(self):
        """Configured Tavily failures should surface instead of being skipped."""
        ctx = _make_ctx(
            tavily_configured=True,
            with_session_factory=True,
            session_factory_results=[[{"name": "llm agents", "mention_count": 5}]],
        )

        call_count = 0

        async def _failing_search(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Tavily rate limit")
            return [
                {
                    "title": "OK Article",
                    "url": "https://example.com/ok",
                    "content": "ok",
                    "score": 0.5,
                }
            ]

        mock_close = AsyncMock()

        with patch("src.app.agents.tools.web_search.TavilySearch") as mock_tavily:
            instance = MagicMock()
            instance.search = AsyncMock(side_effect=_failing_search)
            instance.close = mock_close
            mock_tavily.return_value = instance

            with pytest.raises(RuntimeError, match="Tavily rate limit"):
                await _search_trending_topics(ctx)

        mock_close.assert_awaited_once()


# ---------------------------------------------------------------------------
# _score_relevance
# ---------------------------------------------------------------------------


class TestScoreRelevance:
    async def test_empty_items_returns_empty(self):
        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "llm agents", "mention_count": 5}]],
        )
        result = await _score_relevance(ctx, [])
        assert result == []

    async def test_no_settings_raises(self):
        items = _sample_items(3)
        with pytest.raises(ConfigError, match="settings are not available"):
            await _score_relevance({}, items)

    async def test_embedding_error_raises(self):
        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "llm agents", "mention_count": 5}]],
        )
        items = _sample_items(3)

        with patch("src.app.core.embeddings.OllamaEmbeddings") as mock_embed:
            instance = MagicMock()
            instance.embed_single = AsyncMock(side_effect=RuntimeError("connection refused"))
            instance.close = AsyncMock()
            mock_embed.return_value = instance

            with pytest.raises(EmbeddingError, match="connection refused"):
                await _score_relevance(ctx, items)

    async def test_embeddings_import_failure_raises(self):
        """When OllamaEmbeddings import fails, curation should fail loudly."""
        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "llm agents", "mention_count": 5}]],
        )
        items = _sample_items(5)

        with (
            patch("src.app.core.embeddings.OllamaEmbeddings", side_effect=ImportError("no module")),
            pytest.raises(EmbeddingError, match="no module"),
        ):
            await _score_relevance(ctx, items)

    async def test_scoring_with_high_relevance(self):
        """Items scoring above 0.7 should be returned."""
        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "llm agents", "mention_count": 5}]],
        )
        items = [
            CuratedItem(
                title="Highly Relevant",
                url="https://example.com/1",
                source="Test",
                snippet="AI and LLM research",
            ),
            CuratedItem(
                title="Also Relevant",
                url="https://example.com/2",
                source="Test",
                snippet="Machine learning advances",
            ),
        ]

        with patch("src.app.core.embeddings.OllamaEmbeddings") as mock_embed:
            instance = MagicMock()
            # Return high-similarity embeddings
            instance.embed_single = AsyncMock(return_value=[1.0, 0.0, 0.0])
            instance.embed = AsyncMock(return_value=[[0.95, 0.05, 0.0], [0.9, 0.1, 0.0]])
            instance.close = AsyncMock()
            mock_embed.return_value = instance

            result = await _score_relevance(ctx, items)

        assert len(result) > 0
        for item in result:
            assert item.relevance_score > 0

    async def test_scoring_with_no_items_above_threshold(self):
        """When no items pass 0.7 threshold, should return top 5 anyway."""
        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "llm agents", "mention_count": 5}]],
        )
        items = [
            CuratedItem(
                title=f"Low Relevance {i}",
                url=f"https://example.com/{i}",
                source="Test",
                snippet="Unrelated content about gardening",
            )
            for i in range(8)
        ]

        with patch("src.app.core.embeddings.OllamaEmbeddings") as mock_embed:
            instance = MagicMock()
            # Interest embedding
            instance.embed_single = AsyncMock(return_value=[1.0, 0.0, 0.0])
            # Item embeddings orthogonal to interest (low similarity)
            instance.embed = AsyncMock(return_value=[[0.0, 1.0, 0.0]] * 8)
            instance.close = AsyncMock()
            mock_embed.return_value = instance

            result = await _score_relevance(ctx, items)

        assert len(result) <= 5

    async def test_scoring_blends_tavily_score(self):
        """Items that already have a Tavily score should blend it with embedding score."""
        ctx = _make_ctx(
            with_session_factory=True,
            session_factory_results=[[{"name": "llm agents", "mention_count": 5}]],
        )
        items = [
            CuratedItem(
                title="Tavily Scored",
                url="https://example.com/1",
                source="Tavily",
                snippet="AI content",
                relevance_score=0.8,
            ),
        ]

        with patch("src.app.core.embeddings.OllamaEmbeddings") as mock_embed:
            instance = MagicMock()
            instance.embed_single = AsyncMock(return_value=[1.0, 0.0, 0.0])
            instance.embed = AsyncMock(return_value=[[0.95, 0.05, 0.0]])
            instance.close = AsyncMock()
            mock_embed.return_value = instance

            result = await _score_relevance(ctx, items)

        # Score should be blended (avg of original + embedding similarity)
        assert len(result) >= 1
        # Original was 0.8, embedding sim is ~0.95, blended should be ~0.875
        assert result[0].relevance_score > 0.7


# ---------------------------------------------------------------------------
# run_curation
# ---------------------------------------------------------------------------


class TestRunCuration:
    async def test_no_settings_raises(self):
        with pytest.raises(ConfigError, match="Curation settings are not available"):
            await run_curation({})

    async def test_no_items_found_logs_and_returns(self):
        ctx = _make_ctx()

        with (
            patch(
                "src.app.workers.curation._poll_rss_feeds", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "src.app.workers.curation._search_trending_topics",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await run_curation(ctx)

    async def test_full_pipeline(self):
        ctx = _make_ctx()
        items = _sample_items(3)

        with (
            patch(
                "src.app.workers.curation._poll_rss_feeds",
                new_callable=AsyncMock,
                return_value=items,
            ),
            patch(
                "src.app.workers.curation._search_trending_topics",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.app.workers.curation._score_relevance",
                new_callable=AsyncMock,
                return_value=items,
            ),
            patch("src.app.workers.curation._store_digest", new_callable=AsyncMock) as mock_store,
        ):
            await run_curation(ctx)

        mock_store.assert_called_once()


# ---------------------------------------------------------------------------
# get_latest_digest
# ---------------------------------------------------------------------------


class TestGetLatestDigest:
    async def test_raises_without_settings(self):
        with pytest.raises(ConfigError, match="settings are not available"):
            await get_latest_digest({})

    async def test_returns_digest_from_redis(self):
        ctx = _make_ctx()

        mock_pool = AsyncMock()
        mock_pool.get = AsyncMock(return_value="CURATED CONTENT (3 items):")
        mock_pool.aclose = AsyncMock()

        with patch("src.app.core.redis.get_redis_client", return_value=mock_pool):
            result = await get_latest_digest(ctx)

        assert "CURATED CONTENT" in result

    async def test_raises_on_redis_error(self):
        ctx = _make_ctx()

        with (
            patch(
                "src.app.core.redis.get_redis_client",
                side_effect=RuntimeError("connection refused"),
            ),
            pytest.raises(RuntimeError, match="connection refused"),
        ):
            await get_latest_digest(ctx)

    async def test_returns_empty_when_no_digest_stored(self):
        """When Redis has no digest, should return empty string."""
        ctx = _make_ctx()

        mock_pool = AsyncMock()
        mock_pool.get = AsyncMock(return_value=None)
        mock_pool.aclose = AsyncMock()

        with patch("src.app.core.redis.get_redis_client", return_value=mock_pool):
            result = await get_latest_digest(ctx)

        assert result == ""


# ---------------------------------------------------------------------------
# _store_digest
# ---------------------------------------------------------------------------


class TestStoreDigest:
    async def test_stores_digest_in_redis(self):
        """Should store digest in Redis with TTL."""
        ctx = _make_ctx()
        digest = "CURATED CONTENT (2 items):\n  1. Article One"

        mock_pool = AsyncMock()
        mock_pool.set = AsyncMock()
        mock_pool.aclose = AsyncMock()

        with patch("src.app.core.redis.get_redis_client", return_value=mock_pool):
            await _store_digest(ctx, digest)

        mock_pool.set.assert_awaited_once_with("curation:latest_digest", digest, ex=86400)

    async def test_empty_digest_is_not_stored(self):
        """Empty digest should not be stored."""
        ctx = _make_ctx()

        with patch("redis.asyncio.from_url") as mock_redis:
            await _store_digest(ctx, "")

        mock_redis.assert_not_called()

    async def test_no_settings_returns_early(self):
        """No settings should fail loudly instead of skipping storage."""
        with pytest.raises(ConfigError, match="settings are not available"):
            await _store_digest({}, "some digest")

    async def test_handles_redis_error(self):
        """Redis errors should propagate instead of being swallowed."""
        ctx = _make_ctx()

        with (
            patch(
                "src.app.core.redis.get_redis_client",
                side_effect=RuntimeError("connection refused"),
            ),
            pytest.raises(RuntimeError, match="connection refused"),
        ):
            await _store_digest(ctx, "some digest content")
