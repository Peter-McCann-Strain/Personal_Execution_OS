"""Tests for pattern detection worker."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.workers.patterns import (
    DetectedPattern,
    PatternAnalysis,
    _format_episodes_for_analysis,
    detect_patterns,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session_factory(episodes: list[dict] | None = None):
    """Create a mock session_factory returning fake episode data."""
    rows = episodes or []

    mock_result = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = rows
    mock_result.mappings.return_value = mock_mappings

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = cm
    return factory


def _make_ctx(
    *,
    with_settings: bool = True,
    with_session_factory: bool = True,
    episodes: list[dict] | None = None,
) -> dict:
    ctx: dict = {}
    if with_settings:
        settings = MagicMock()
        settings.anthropic_api_key.get_secret_value.return_value = "sk-test"
        settings.classifier_model = "claude-haiku-4-5-20251001"
        ctx["settings"] = settings
    if with_session_factory:
        ctx["session_factory"] = _mock_session_factory(episodes)
    return ctx


def _sample_episodes(count: int = 5) -> list[dict]:
    """Generate sample episode dicts for testing."""
    base = datetime.now(tz=UTC) - timedelta(days=7)
    return [
        {
            "summary": f"Day {i}: Had a productive morning working on the project.",
            "mood_score": 6.0 + (i * 0.5),
            "energy_rating": 7.0 - (i * 0.3),
            "tags": ["work", "productivity"],
            "created_at": base + timedelta(days=i),
        }
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# _format_episodes_for_analysis
# ---------------------------------------------------------------------------


class TestFormatEpisodes:
    def test_empty_episodes(self):
        result = _format_episodes_for_analysis([])
        assert "No diary entries" in result

    def test_formats_with_mood_and_energy(self):
        episodes = _sample_episodes(2)
        result = _format_episodes_for_analysis(episodes)
        assert "mood=" in result
        assert "energy=" in result
        assert "Aggregate Stats" in result
        assert "Total entries: 2" in result

    def test_handles_missing_mood(self):
        episodes = [
            {
                "summary": "A day with no mood score",
                "mood_score": None,
                "energy_rating": None,
                "tags": None,
                "created_at": datetime.now(tz=UTC),
            }
        ]
        result = _format_episodes_for_analysis(episodes)
        assert "mood=N/A" in result
        assert "energy=N/A" in result
        assert "no tags" in result

    def test_includes_aggregate_stats(self):
        episodes = _sample_episodes(3)
        result = _format_episodes_for_analysis(episodes)
        assert "avg=" in result
        assert "min=" in result
        assert "max=" in result


# ---------------------------------------------------------------------------
# DetectedPattern model
# ---------------------------------------------------------------------------


class TestDetectedPatternModel:
    def test_valid_pattern(self):
        p = DetectedPattern(
            pattern_type="mood_trend",
            description="Mood is improving over the last week",
            confidence=0.85,
            evidence=["Day 1 mood 6.0", "Day 5 mood 8.0"],
            trend="improving",
        )
        assert p.pattern_type == "mood_trend"
        assert p.confidence == 0.85

    def test_confidence_bounds(self):
        with pytest.raises(ValueError, match="less than or equal to 1"):
            DetectedPattern(
                pattern_type="test",
                description="test",
                confidence=1.5,
                evidence=[],
                trend="stable",
            )


class TestPatternAnalysisModel:
    def test_empty_patterns(self):
        analysis = PatternAnalysis(patterns=[], summary="No patterns found")
        assert len(analysis.patterns) == 0

    def test_with_patterns(self):
        analysis = PatternAnalysis(
            patterns=[
                DetectedPattern(
                    pattern_type="mood_trend",
                    description="Improving",
                    confidence=0.8,
                    evidence=["data"],
                    trend="improving",
                )
            ],
            summary="One pattern found",
        )
        assert len(analysis.patterns) == 1


# ---------------------------------------------------------------------------
# detect_patterns
# ---------------------------------------------------------------------------


class TestDetectPatterns:
    async def test_no_session_factory(self):
        ctx = _make_ctx(with_session_factory=False)
        with pytest.raises(RuntimeError, match="pattern_detection_no_session_factory"):
            await detect_patterns(ctx)

    async def test_no_settings(self):
        ctx = _make_ctx(with_settings=False)
        with pytest.raises(RuntimeError, match="pattern_detection_no_settings"):
            await detect_patterns(ctx)

    async def test_no_episodes_returns_empty(self):
        ctx = _make_ctx(episodes=[])
        result = await detect_patterns(ctx)
        assert result == []

    async def test_successful_pattern_detection(self):
        episodes = _sample_episodes(5)
        ctx = _make_ctx(episodes=episodes)

        mock_analysis = PatternAnalysis(
            patterns=[
                DetectedPattern(
                    pattern_type="mood_trend",
                    description="Mood is gradually improving",
                    confidence=0.8,
                    evidence=["Day 1: 6.0", "Day 5: 8.0"],
                    trend="improving",
                ),
                DetectedPattern(
                    pattern_type="energy_pattern",
                    description="Energy dips mid-week",
                    confidence=0.65,
                    evidence=["Wednesday energy: 5.0"],
                    trend="cyclical",
                ),
            ],
            summary="Two patterns detected",
        )

        with patch(
            "src.app.workers.patterns.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_analysis,
        ):
            result = await detect_patterns(ctx)

        assert len(result) == 2
        assert result[0]["pattern_type"] == "mood_trend"
        assert result[0]["confidence"] == 0.8
        assert result[1]["pattern_type"] == "energy_pattern"
        assert result[1]["trend"] == "cyclical"

    async def test_llm_failure_raises(self):
        episodes = _sample_episodes(3)
        ctx = _make_ctx(episodes=episodes)

        with (
            patch(
                "src.app.workers.patterns.call_and_parse",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM timeout"),
            ),
            pytest.raises(RuntimeError, match="LLM timeout"),
        ):
            await detect_patterns(ctx)

    async def test_returns_dicts_not_models(self):
        """Ensure detect_patterns returns plain dicts, not Pydantic models."""
        episodes = _sample_episodes(2)
        ctx = _make_ctx(episodes=episodes)

        mock_analysis = PatternAnalysis(
            patterns=[
                DetectedPattern(
                    pattern_type="recurring_theme",
                    description="Work mentioned frequently",
                    confidence=0.9,
                    evidence=["work tag in 4/5 entries"],
                    trend="stable",
                )
            ],
            summary="One pattern",
        )

        with patch(
            "src.app.workers.patterns.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_analysis,
        ):
            result = await detect_patterns(ctx)

        assert isinstance(result[0], dict)
        assert "pattern_type" in result[0]
        assert "evidence" in result[0]
