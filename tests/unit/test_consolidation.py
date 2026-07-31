"""Tests for background memory consolidation worker."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.workers.consolidation import (
    ClusteringResult,
    ConsolidationSummary,
    EpisodeCluster,
    _cluster_episodes,
    _create_summary_note,
    _discover_links,
    _format_episodes_for_clustering,
    _get_recent_episodes,
    _ResolvedCluster,
    run_consolidation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session(query_results: list[dict] | None = None):
    """Create a mock AsyncSession returning fake query data."""
    rows = query_results or []

    mock_result = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = rows
    mock_result.mappings.return_value = mock_mappings

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    return session


def _mock_session_multi(results_list: list[list[dict]]):
    """Create a mock AsyncSession returning different results for sequential execute() calls."""
    execute_results = []
    for rows in results_list:
        mock_result = MagicMock()
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = rows
        mock_result.mappings.return_value = mock_mappings
        execute_results.append(mock_result)

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_results)
    session.commit = AsyncMock()
    return session


def _mock_session_factory(session=None):
    """Wrap a mock session in a factory that supports async with."""
    if session is None:
        session = _mock_session()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = cm
    return factory


def _make_settings(**overrides):
    """Create mock settings with sensible defaults."""
    settings = MagicMock()
    settings.anthropic_api_key.get_secret_value.return_value = "sk-test"
    settings.classifier_model = "claude-haiku-4-5-20251001"
    settings.classifier_max_tokens = 512
    settings.summary_max_tokens = 2048
    settings.consolidation_enabled = True
    settings.consolidation_lookback_hours = 24
    settings.consolidation_min_cluster_size = 2
    settings.ollama_host = "http://localhost:11434"
    settings.ollama_embed_model = "nomic-embed-text:v2-moe"
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def _make_ctx(
    *,
    with_settings: bool = True,
    with_session_factory: bool = True,
    session: AsyncMock | None = None,
    settings_overrides: dict | None = None,
) -> dict:
    ctx: dict = {}
    if with_settings:
        ctx["settings"] = _make_settings(**(settings_overrides or {}))
    if with_session_factory:
        ctx["session_factory"] = _mock_session_factory(session)
    return ctx


def _sample_episodes(count: int = 5) -> list[dict]:
    """Generate sample episode dicts for testing."""
    import uuid

    base = datetime.now(tz=UTC) - timedelta(hours=12)
    return [
        {
            "id": uuid.uuid4(),
            "content": f"Episode {i}: Worked on the AI project and had a meeting.",
            "summary": f"Day {i}: Had a productive session working on the AI project.",
            "episode_type": "diary",
            "para_category": "project",
            "mood_score": 6.0 + (i * 0.5),
            "energy_rating": 7.0 - (i * 0.3),
            "tags": ["work", "AI"],
            "people_mentioned": ["Alice", "Bob"] if i % 2 == 0 else None,
            "created_at": base + timedelta(hours=i),
        }
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TestEpisodeCluster:
    def test_valid_cluster(self):
        c = EpisodeCluster(
            topic_label="AI Work",
            episode_indices=[0, 1, 2],
            summary="Episodes about AI project",
        )
        assert c.topic_label == "AI Work"
        assert len(c.episode_indices) == 3

    def test_empty_cluster(self):
        c = EpisodeCluster(
            topic_label="Empty",
            episode_indices=[],
            summary="Nothing",
        )
        assert len(c.episode_indices) == 0


class TestClusteringResult:
    def test_empty_clusters(self):
        r = ClusteringResult(clusters=[])
        assert len(r.clusters) == 0

    def test_with_clusters(self):
        r = ClusteringResult(
            clusters=[
                EpisodeCluster(
                    topic_label="Work",
                    episode_indices=[0, 1],
                    summary="Work related",
                )
            ]
        )
        assert len(r.clusters) == 1


class TestConsolidationSummary:
    def test_valid_summary(self):
        s = ConsolidationSummary(
            title="AI Project Progress",
            content="Good progress on the AI project this week.",
            tags=["AI", "progress"],
            key_insight="The team is on track for the milestone.",
        )
        assert s.title == "AI Project Progress"
        assert len(s.tags) == 2


# ---------------------------------------------------------------------------
# _format_episodes_for_clustering
# ---------------------------------------------------------------------------


class TestFormatEpisodesForClustering:
    def test_formats_basic_episodes(self):
        episodes = _sample_episodes(3)
        result = _format_episodes_for_clustering(episodes)
        assert "3 total" in result
        assert "[0]" in result
        assert "[1]" in result
        assert "[2]" in result

    def test_includes_tags(self):
        episodes = _sample_episodes(1)
        result = _format_episodes_for_clustering(episodes)
        assert "work" in result
        assert "AI" in result

    def test_includes_people(self):
        episodes = _sample_episodes(1)
        result = _format_episodes_for_clustering(episodes)
        assert "Alice" in result
        assert "Bob" in result

    def test_handles_missing_fields(self):
        episodes = [
            {
                "content": "Minimal episode",
                "summary": None,
                "tags": None,
                "people_mentioned": None,
                "created_at": None,
            }
        ]
        result = _format_episodes_for_clustering(episodes)
        assert "unknown" in result
        assert "none" in result

    def test_uses_summary_when_available(self):
        episodes = [
            {
                "content": "Full content text",
                "summary": "Short summary",
                "tags": None,
                "people_mentioned": None,
                "created_at": datetime.now(tz=UTC),
            }
        ]
        result = _format_episodes_for_clustering(episodes)
        assert "Short summary" in result

    def test_falls_back_to_content_when_no_summary(self):
        episodes = [
            {
                "content": "Full content text that is important",
                "summary": None,
                "tags": None,
                "people_mentioned": None,
                "created_at": datetime.now(tz=UTC),
            }
        ]
        result = _format_episodes_for_clustering(episodes)
        assert "Full content text" in result


# ---------------------------------------------------------------------------
# run_consolidation — main entry point
# ---------------------------------------------------------------------------


class TestRunConsolidation:
    async def test_missing_session_factory_raises(self):
        ctx = _make_ctx(with_session_factory=False)
        with pytest.raises(RuntimeError, match="consolidation_missing_session_factory"):
            await run_consolidation(ctx)

    async def test_missing_settings_raises(self):
        ctx = _make_ctx(with_settings=False)
        with pytest.raises(RuntimeError, match="consolidation_missing_settings"):
            await run_consolidation(ctx)

    async def test_disabled_returns_early(self):
        ctx = _make_ctx(settings_overrides={"consolidation_enabled": False})
        result = await run_consolidation(ctx)
        assert result["status"] == "disabled"

    async def test_too_few_episodes_skips(self):
        # Session returns 2 episodes (below threshold of 3)
        session = _mock_session(query_results=_sample_episodes(2))
        ctx = _make_ctx(session=session)

        result = await run_consolidation(ctx)
        assert result["status"] == "skipped"
        assert result["reason"] == "too_few_episodes"

    async def test_zero_episodes_skips(self):
        session = _mock_session(query_results=[])
        ctx = _make_ctx(session=session)

        result = await run_consolidation(ctx)
        assert result["status"] == "skipped"
        assert result["reason"] == "too_few_episodes"

    async def test_successful_consolidation(self):
        episodes = _sample_episodes(5)

        # Session needs to return episodes for _get_recent_episodes,
        # then handle note creation, then handle link discovery queries
        session = _mock_session_multi(
            [
                episodes,  # _get_recent_episodes
                [],  # _discover_links: recent notes query
            ]
        )
        session.commit = AsyncMock()
        ctx = _make_ctx(session=session)

        mock_note = MagicMock()
        mock_note.id = "test-note-id"

        with (
            patch(
                "src.app.workers.consolidation._cluster_episodes",
                new_callable=AsyncMock,
                return_value=[
                    _ResolvedCluster(
                        topic_label="AI Work",
                        summary="Working on AI project",
                        episodes=episodes[:3],
                    ),
                    _ResolvedCluster(
                        topic_label="Meetings",
                        summary="Meeting discussions",
                        episodes=episodes[3:],
                    ),
                ],
            ),
            patch(
                "src.app.workers.consolidation._create_summary_note",
                new_callable=AsyncMock,
                return_value=mock_note,
            ) as mock_create,
            patch(
                "src.app.workers.consolidation._discover_links",
                new_callable=AsyncMock,
                return_value=3,
            ) as mock_links,
        ):
            result = await run_consolidation(ctx)

        assert result["status"] == "completed"
        assert result["episodes_processed"] == 5
        assert result["clusters_found"] == 2
        assert result["notes_created"] == 2
        assert result["links_discovered"] == 3
        assert mock_create.call_count == 2
        mock_links.assert_awaited_once()

    async def test_small_clusters_not_summarised(self):
        """Clusters smaller than min_cluster_size should not produce notes."""
        episodes = _sample_episodes(4)

        session = _mock_session_multi(
            [
                episodes,  # _get_recent_episodes
                [],  # _discover_links: recent notes query
            ]
        )
        session.commit = AsyncMock()
        ctx = _make_ctx(session=session)

        with (
            patch(
                "src.app.workers.consolidation._cluster_episodes",
                new_callable=AsyncMock,
                return_value=[
                    _ResolvedCluster(
                        topic_label="Big Cluster",
                        summary="Has enough episodes",
                        episodes=episodes[:3],  # 3 >= min_cluster_size(2)
                    ),
                    _ResolvedCluster(
                        topic_label="Small Cluster",
                        summary="Only one episode",
                        episodes=episodes[3:4],  # 1 < min_cluster_size(2)
                    ),
                ],
            ),
            patch(
                "src.app.workers.consolidation._create_summary_note",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ) as mock_create,
            patch(
                "src.app.workers.consolidation._discover_links",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            result = await run_consolidation(ctx)

        assert result["notes_created"] == 1
        mock_create.assert_awaited_once()


# ---------------------------------------------------------------------------
# _get_recent_episodes
# ---------------------------------------------------------------------------


class TestGetRecentEpisodes:
    async def test_returns_episodes(self):
        episodes = _sample_episodes(3)
        session = _mock_session(query_results=episodes)

        result = await _get_recent_episodes(session, hours=24)
        assert len(result) == 3
        session.execute.assert_awaited_once()

    async def test_returns_empty_when_no_episodes(self):
        session = _mock_session(query_results=[])

        result = await _get_recent_episodes(session, hours=24)
        assert result == []

    async def test_uses_provided_hours(self):
        session = _mock_session(query_results=[])

        await _get_recent_episodes(session, hours=48)
        session.execute.assert_awaited_once()
        # Verify the cutoff parameter was passed
        call_args = session.execute.call_args
        params = call_args[0][1]  # Second positional arg is the params dict
        assert "cutoff" in params
        assert "now" in params


# ---------------------------------------------------------------------------
# _cluster_episodes
# ---------------------------------------------------------------------------


class TestClusterEpisodes:
    async def test_clusters_episodes(self):
        episodes = _sample_episodes(4)
        settings = _make_settings()

        mock_result = ClusteringResult(
            clusters=[
                EpisodeCluster(
                    topic_label="Work",
                    episode_indices=[0, 1],
                    summary="Work sessions",
                ),
                EpisodeCluster(
                    topic_label="Meetings",
                    episode_indices=[2, 3],
                    summary="Meeting notes",
                ),
            ]
        )

        with patch(
            "src.app.workers.consolidation.call_and_parse_with_retry",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            clusters = await _cluster_episodes(episodes, settings)

        assert len(clusters) == 2
        assert clusters[0].topic_label == "Work"
        assert len(clusters[0].episodes) == 2
        assert clusters[1].topic_label == "Meetings"
        assert len(clusters[1].episodes) == 2

    async def test_out_of_bounds_indices_filtered(self):
        """Episode indices that exceed the episode list should be ignored."""
        episodes = _sample_episodes(3)
        settings = _make_settings()

        mock_result = ClusteringResult(
            clusters=[
                EpisodeCluster(
                    topic_label="Valid",
                    episode_indices=[0, 1, 99],  # 99 is out of bounds
                    summary="Mostly valid",
                ),
            ]
        )

        with patch(
            "src.app.workers.consolidation.call_and_parse_with_retry",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            clusters = await _cluster_episodes(episodes, settings)

        assert len(clusters) == 1
        assert len(clusters[0].episodes) == 2  # Only 0 and 1 resolved

    async def test_negative_indices_filtered(self):
        """Negative indices should be ignored."""
        episodes = _sample_episodes(3)
        settings = _make_settings()

        mock_result = ClusteringResult(
            clusters=[
                EpisodeCluster(
                    topic_label="Test",
                    episode_indices=[-1, 0],
                    summary="Testing",
                ),
            ]
        )

        with patch(
            "src.app.workers.consolidation.call_and_parse_with_retry",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            clusters = await _cluster_episodes(episodes, settings)

        assert len(clusters) == 1
        assert len(clusters[0].episodes) == 1  # Only index 0

    async def test_empty_cluster_filtered(self):
        """Clusters that resolve to no episodes should be dropped."""
        episodes = _sample_episodes(3)
        settings = _make_settings()

        mock_result = ClusteringResult(
            clusters=[
                EpisodeCluster(
                    topic_label="Ghost",
                    episode_indices=[99, 100],  # All out of bounds
                    summary="Nothing here",
                ),
                EpisodeCluster(
                    topic_label="Real",
                    episode_indices=[0],
                    summary="Real cluster",
                ),
            ]
        )

        with patch(
            "src.app.workers.consolidation.call_and_parse_with_retry",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            clusters = await _cluster_episodes(episodes, settings)

        assert len(clusters) == 1
        assert clusters[0].topic_label == "Real"

    async def test_llm_failure_raises(self):
        episodes = _sample_episodes(3)
        settings = _make_settings()

        with (
            patch(
                "src.app.workers.consolidation.call_and_parse_with_retry",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM down"),
            ),
            pytest.raises(RuntimeError, match="LLM down"),
        ):
            await _cluster_episodes(episodes, settings)


# ---------------------------------------------------------------------------
# _create_summary_note
# ---------------------------------------------------------------------------


class TestCreateSummaryNote:
    async def test_creates_note(self):
        episodes = _sample_episodes(3)
        cluster = _ResolvedCluster(
            topic_label="AI Work",
            summary="Working on AI",
            episodes=episodes,
        )
        settings = _make_settings()
        session = AsyncMock()

        mock_summary = ConsolidationSummary(
            title="AI Project Progress",
            content="Good progress on AI project.",
            tags=["AI", "progress"],
            key_insight="On track for milestone.",
        )

        mock_note = MagicMock()
        mock_note.id = "new-note-id"

        with (
            patch(
                "src.app.workers.consolidation.call_and_parse_with_retry",
                new_callable=AsyncMock,
                return_value=mock_summary,
            ),
            patch(
                "src.app.workers.consolidation.create_note",
                new_callable=AsyncMock,
                return_value=mock_note,
            ) as mock_create_note,
        ):
            result = await _create_summary_note(session, cluster, settings)

        assert result is mock_note
        mock_create_note.assert_awaited_once()
        call_kwargs = mock_create_note.call_args
        assert call_kwargs.kwargs["title"] == "AI Project Progress"
        assert call_kwargs.kwargs["note_type"] == "consolidation"
        assert "AI" in call_kwargs.kwargs["tags"]
        assert "Key Insight" in call_kwargs.kwargs["content"]
        assert "On track for milestone" in call_kwargs.kwargs["content"]

    async def test_llm_failure_raises(self):
        cluster = _ResolvedCluster(
            topic_label="Test",
            summary="Test cluster",
            episodes=_sample_episodes(2),
        )
        settings = _make_settings()
        session = AsyncMock()

        with (
            patch(
                "src.app.workers.consolidation.call_and_parse_with_retry",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM failure"),
            ),
            pytest.raises(RuntimeError, match="LLM failure"),
        ):
            await _create_summary_note(session, cluster, settings)

    async def test_includes_episode_content_in_prompt(self):
        """The LLM should receive episode content for synthesis."""
        episodes = _sample_episodes(2)
        cluster = _ResolvedCluster(
            topic_label="Test Topic",
            summary="Test",
            episodes=episodes,
        )
        settings = _make_settings()
        session = AsyncMock()

        captured_messages = []

        async def _capture(
            client,
            *,
            model,
            max_tokens,
            system,
            messages,
            response_model,
            error_context,
            inject_personality,
        ):
            captured_messages.append(messages)
            return ConsolidationSummary(
                title="Test",
                content="Test content",
                tags=[],
                key_insight="Test insight",
            )

        mock_note = MagicMock()
        mock_note.id = "test-id"

        with (
            patch(
                "src.app.workers.consolidation.call_and_parse_with_retry",
                new_callable=AsyncMock,
                side_effect=_capture,
            ),
            patch(
                "src.app.workers.consolidation.create_note",
                new_callable=AsyncMock,
                return_value=mock_note,
            ),
        ):
            await _create_summary_note(session, cluster, settings)

        assert len(captured_messages) == 1
        msg_content = captured_messages[0][0]["content"]
        assert "Test Topic" in msg_content


# ---------------------------------------------------------------------------
# _discover_links
# ---------------------------------------------------------------------------


class TestDiscoverLinks:
    async def test_no_recent_notes(self):
        session = _mock_session(query_results=[])
        settings = _make_settings()

        result = await _discover_links(session, settings)
        assert result == 0

    async def test_discovers_links(self):
        import uuid

        note_id_1 = uuid.uuid4()
        note_id_2 = uuid.uuid4()

        recent_notes = [
            {"id": note_id_1, "title": "Note 1", "embedding": [0.1] * 768},
        ]
        similar_notes = [
            {"id": note_id_2, "title": "Note 2", "similarity": 0.85},
        ]

        session = _mock_session_multi([recent_notes, similar_notes])
        settings = _make_settings()

        with patch(
            "src.app.workers.consolidation.create_note_link",
            new_callable=AsyncMock,
        ) as mock_link:
            result = await _discover_links(session, settings)

        assert result == 1
        mock_link.assert_awaited_once()
        call_kwargs = mock_link.call_args.kwargs
        assert call_kwargs["source_note_id"] == note_id_1
        assert call_kwargs["target_note_id"] == note_id_2
        assert call_kwargs["auto_discovered"] is True
        assert "0.85" in call_kwargs["link_reason"]

    async def test_multiple_similar_notes(self):
        import uuid

        note_id = uuid.uuid4()
        target_1 = uuid.uuid4()
        target_2 = uuid.uuid4()

        recent_notes = [
            {"id": note_id, "title": "Source Note", "embedding": [0.1] * 768},
        ]
        similar_notes = [
            {"id": target_1, "title": "Target 1", "similarity": 0.9},
            {"id": target_2, "title": "Target 2", "similarity": 0.75},
        ]

        session = _mock_session_multi([recent_notes, similar_notes])
        settings = _make_settings()

        with patch(
            "src.app.workers.consolidation.create_note_link",
            new_callable=AsyncMock,
        ) as mock_link:
            result = await _discover_links(session, settings)

        assert result == 2
        assert mock_link.call_count == 2


# ---------------------------------------------------------------------------
# _ResolvedCluster
# ---------------------------------------------------------------------------


class TestResolvedCluster:
    def test_construction(self):
        episodes = _sample_episodes(2)
        cluster = _ResolvedCluster(
            topic_label="Test",
            summary="Test summary",
            episodes=episodes,
        )
        assert cluster.topic_label == "Test"
        assert cluster.summary == "Test summary"
        assert len(cluster.episodes) == 2


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestConsolidationErrorHandling:
    async def test_clustering_error_propagates(self):
        """If clustering fails, the error should propagate up."""
        episodes = _sample_episodes(5)
        session = _mock_session(query_results=episodes)
        ctx = _make_ctx(session=session)

        with (
            patch(
                "src.app.workers.consolidation._cluster_episodes",
                new_callable=AsyncMock,
                side_effect=RuntimeError("clustering failed"),
            ),
            pytest.raises(RuntimeError, match="clustering failed"),
        ):
            await run_consolidation(ctx)

    async def test_summary_creation_error_propagates(self):
        """If summary creation fails, the error should propagate up."""
        episodes = _sample_episodes(5)
        session = _mock_session(query_results=episodes)
        ctx = _make_ctx(session=session)

        with (
            patch(
                "src.app.workers.consolidation._cluster_episodes",
                new_callable=AsyncMock,
                return_value=[
                    _ResolvedCluster(
                        topic_label="Fail",
                        summary="Will fail",
                        episodes=episodes[:3],
                    ),
                ],
            ),
            patch(
                "src.app.workers.consolidation._create_summary_note",
                new_callable=AsyncMock,
                side_effect=RuntimeError("summary failed"),
            ),
            pytest.raises(RuntimeError, match="summary failed"),
        ):
            await run_consolidation(ctx)
