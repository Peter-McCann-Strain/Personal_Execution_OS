"""Tests for Socratic tutorial post-analysis."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.socratic.state import TutorialAnalysis


def _mock_settings():
    settings = MagicMock()
    settings.socratic_analysis_model = "claude-sonnet-4-6"
    settings.socratic_analysis_max_tokens = 8192
    return settings


@pytest.fixture(autouse=True)
def _patch_settings():
    with patch(
        "src.app.config.get_settings",
        return_value=_mock_settings(),
    ):
        yield


class TestAnalyseTutorial:
    async def test_returns_analysis(self):
        mock_client = AsyncMock()
        state = {
            "topic": "Caching",
            "work_type": "essay",
            "dialogue_history": [
                {"role": "tutor", "content": "Explain caching."},
                {"role": "user", "content": "It stores data."},
                {"role": "tutor", "content": "Why is that useful?"},
                {"role": "user", "content": "It reduces latency."},
            ],
            "assessor_log": [
                {"turn": 1, "action": "tutor", "bloom_level": "understand"},
            ],
            "propositions": [
                {"index": 0, "text": "Caching reduces latency"},
            ],
        }

        mock_analysis = TutorialAnalysis(
            summary="Good understanding of basics.",
            bloom_progression=[
                {"segment": "opening", "level": "understand"},
            ],
            knowledge_gaps=[
                {"topic": "invalidation", "severity": "moderate", "addressed": False},
            ],
            strong_areas=[
                {"topic": "latency", "evidence": "Clear explanation"},
            ],
            recommendations=["Study cache invalidation strategies"],
            unresolved_topics=["cache invalidation"],
        )

        with patch(
            "src.app.agents.socratic.analysis.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_analysis,
        ):
            from src.app.agents.socratic.analysis import analyse_tutorial

            result = await analyse_tutorial(state, mock_client)

        assert isinstance(result, TutorialAnalysis)
        assert "Good understanding" in result.summary
        assert len(result.knowledge_gaps) == 1
        assert result.knowledge_gaps[0]["topic"] == "invalidation"

    async def test_handles_empty_dialogue(self):
        mock_client = AsyncMock()
        state = {
            "topic": "Empty",
            "work_type": "other",
            "dialogue_history": [],
            "assessor_log": [],
            "propositions": [],
        }

        mock_analysis = TutorialAnalysis(summary="No dialogue to analyse.")

        with patch(
            "src.app.agents.socratic.analysis.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_analysis,
        ):
            from src.app.agents.socratic.analysis import analyse_tutorial

            result = await analyse_tutorial(state, mock_client)

        assert result.summary == "No dialogue to analyse."


class TestFormatAnalysisReport:
    def test_formats_basic_report(self):
        from src.app.agents.socratic.analysis import format_analysis_report

        analysis = TutorialAnalysis(
            summary="Strong session overall.",
            strong_areas=[
                {"topic": "Architecture", "evidence": "Clear mental model"},
            ],
            knowledge_gaps=[
                {"topic": "Scaling", "severity": "moderate", "addressed": False},
            ],
            recommendations=["Review scaling patterns"],
            unresolved_topics=["Horizontal scaling"],
            engagement_metrics={
                "speaking_ratio_student_pct": 72,
                "self_directed_questions": 3,
                "aha_moments": 1,
            },
        )

        report = format_analysis_report(analysis, "System Design")

        assert "System Design" in report
        assert "Strong session" in report
        assert "Architecture" in report
        assert "Scaling" in report
        assert "**unresolved**" in report
        assert "Review scaling" in report
        assert "Horizontal scaling" in report
        assert "72%" in report

    def test_formats_empty_analysis(self):
        from src.app.agents.socratic.analysis import format_analysis_report

        analysis = TutorialAnalysis(summary="No data.")
        report = format_analysis_report(analysis, "Empty")

        assert "Empty" in report
        assert "No data." in report

    def test_addressed_gaps_not_bold(self):
        from src.app.agents.socratic.analysis import format_analysis_report

        analysis = TutorialAnalysis(
            summary="Good.",
            knowledge_gaps=[
                {"topic": "Caching", "severity": "minor", "addressed": True},
            ],
        )

        report = format_analysis_report(analysis, "Test")
        assert "addressed" in report
        assert "**unresolved**" not in report
