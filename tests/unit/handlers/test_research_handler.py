"""Tests for research handler — multi-step web research with Tavily."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.domain.models import (
    ChatResponse,
    Intent,
    IntentType,
    MessageInput,
    Specialist,
)


@pytest.fixture(autouse=True)
def _restore_imported_modules():
    """Keep isolated import stubs from leaking into the wider test session."""
    module_names = [
        "src.app.domain.services.handlers",
        "src.app.domain.services.handlers._common",
        "src.app.domain.services.handlers.research",
        "src.app.persistence.repositories.episodes",
        "src.app.persistence.repositories.runtime_records",
    ]
    snapshot = {name: sys.modules.get(name) for name in module_names}
    yield
    for name, module in snapshot.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _make_message(content: str = "Research best practices for FastAPI") -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _make_intent() -> Intent:
    return Intent(
        intent_type=IntentType.RESEARCH,
        confidence=0.9,
        specialist=Specialist.RESEARCH,
        reasoning="research request",
    )


def _make_research_report():
    """Build a mock ResearchReport."""
    finding = MagicMock()
    finding.source = "fastapi.tiangolo.com"
    finding.key_points = ["Use async endpoints", "Leverage Pydantic models"]

    option = MagicMock()
    option.name = "FastAPI"
    option.pros = ["Fast", "Type-safe"]
    option.cons = ["Smaller community"]

    decision_framework = MagicMock()
    decision_framework.options = [option]
    decision_framework.recommendation = "Use FastAPI for this project"

    report = MagicMock()
    report.title = "FastAPI Best Practices"
    report.synthesis = "FastAPI is excellent for building APIs with Python."
    report.findings = [finding]
    report.search_queries = ["fastapi best practices", "fastapi vs flask"]
    report.decision_framework = decision_framework
    report.safety_flags = ["untrusted_external_input", "untrusted_external_web_result"]
    return report


def _make_episode_mock():
    episode = MagicMock()
    episode.id = uuid.uuid4()
    return episode


def _load_research_handler():
    """Import the research handler without triggering eager package side effects."""
    package_name = "src.app.domain.services.handlers"
    package = sys.modules.get(package_name)
    if package is None or not getattr(package, "__path__", None):
        package = ModuleType(package_name)
        package.__path__ = [
            str(
                Path(__file__).resolve().parents[3]
                / "src"
                / "app"
                / "domain"
                / "services"
                / "handlers"
            ),
        ]
        sys.modules[package_name] = package

    common_module = sys.modules.get("src.app.domain.services.handlers._common")
    if common_module is None:
        common_module = ModuleType("src.app.domain.services.handlers._common")

        async def _enqueue_entity_extraction(**_kwargs):
            return None

        async def _enqueue_reflection_pack_refresh(*_args, **_kwargs):
            return None

        common_module.enqueue_entity_extraction = _enqueue_entity_extraction
        common_module.enqueue_reflection_pack_refresh = _enqueue_reflection_pack_refresh
        sys.modules["src.app.domain.services.handlers._common"] = common_module

    episodes_module = sys.modules.get("src.app.persistence.repositories.episodes")
    if episodes_module is None:
        episodes_module = ModuleType("src.app.persistence.repositories.episodes")

        async def _create_episode(*_args, **_kwargs):
            raise RuntimeError("create_episode stub must be patched in tests")

        episodes_module.create_episode = _create_episode
        sys.modules["src.app.persistence.repositories.episodes"] = episodes_module

    import importlib

    return importlib.import_module("src.app.domain.services.handlers.research")


@pytest.mark.asyncio
async def test_handle_research_happy_path():
    """handle_research runs full pipeline and returns formatted report."""
    message = _make_message()
    intent = _make_intent()
    report = _make_research_report()
    episode = _make_episode_mock()

    mock_session = AsyncMock()
    mock_search_client = AsyncMock()
    mock_search_client.close = AsyncMock()
    research_handler = _load_research_handler()

    with (
        patch.object(research_handler, "get_settings") as mock_settings,
        patch.object(
            research_handler,
            "TavilySearch",
            return_value=mock_search_client,
        ),
        patch.object(
            research_handler,
            "run_research",
            new_callable=AsyncMock,
            return_value=report,
        ) as mock_run,
        patch.object(
            research_handler,
            "create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch.object(
            research_handler,
            "create_artifact_record",
            new_callable=AsyncMock,
        ) as mock_artifact,
    ):
        settings = MagicMock()
        settings.tavily_configured = True
        settings.tavily_api_key = MagicMock()
        settings.tavily_api_key.get_secret_value.return_value = "test-key"
        mock_settings.return_value = settings

        result = await research_handler.handle_research(
            message,
            AsyncMock(),
            mock_session,
            intent,
        )

    assert isinstance(result, ChatResponse)
    assert result.agent == "research"
    assert "FastAPI Best Practices" in result.content
    assert "excellent for building APIs" in result.content
    assert "Use FastAPI for this project" in result.content
    assert result.metadata["episode_id"] == str(episode.id)
    assert result.metadata["finding_count"] == 1
    assert result.metadata["safety_flags"] == report.safety_flags
    assert result.metadata["citations"][0]["source_id"] == "fastapi.tiangolo.com"
    assert result.metadata["content_blocks"][0]["type"] == "text"
    assert "FastAPI is excellent for building APIs" in result.metadata["content_blocks"][0]["text"]
    assert result.metadata["content_blocks"][1]["type"] == "bullet_list"
    assert result.metadata["content_blocks"][2]["title"] == "Decision framework"
    assert result.metadata["content_blocks"][3]["title"] == "Recommendation"
    mock_run.assert_awaited_once()
    assert mock_session.commit.await_count == 2
    mock_search_client.close.assert_awaited_once()
    mock_artifact.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_research_tavily_not_configured():
    """handle_research returns error when Tavily API key is not set."""
    message = _make_message()
    intent = _make_intent()
    research_handler = _load_research_handler()

    with patch.object(research_handler, "get_settings") as mock_settings:
        settings = MagicMock()
        settings.tavily_configured = False
        mock_settings.return_value = settings

        result = await research_handler.handle_research(
            message,
            AsyncMock(),
            AsyncMock(),
            intent,
        )

    assert isinstance(result, ChatResponse)
    assert result.agent == "research"
    assert "TAVILY_API_KEY is not configured" in result.content
    assert result.metadata["error"] == "tavily_not_configured"


@pytest.mark.asyncio
async def test_handle_research_llm_failure_propagates():
    """handle_research propagates errors from run_research."""
    message = _make_message()
    intent = _make_intent()
    research_handler = _load_research_handler()

    mock_search_client = AsyncMock()
    mock_search_client.close = AsyncMock()

    with (
        patch.object(research_handler, "get_settings") as mock_settings,
        patch.object(
            research_handler,
            "TavilySearch",
            return_value=mock_search_client,
        ),
        patch.object(
            research_handler,
            "run_research",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Research pipeline failed"),
        ),
        pytest.raises(RuntimeError, match="Research pipeline failed"),
    ):
        settings = MagicMock()
        settings.tavily_configured = True
        settings.tavily_api_key = MagicMock()
        settings.tavily_api_key.get_secret_value.return_value = "test-key"
        mock_settings.return_value = settings

        await research_handler.handle_research(
            message,
            AsyncMock(),
            AsyncMock(),
            intent,
        )

    # Even on error, close is called via finally
    mock_search_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_research_report_without_decision_framework():
    """handle_research handles reports with no decision framework."""
    message = _make_message()
    intent = _make_intent()
    episode = _make_episode_mock()
    research_handler = _load_research_handler()

    report = MagicMock()
    report.title = "Simple Research"
    report.synthesis = "Some findings."
    report.findings = []
    report.search_queries = ["query1"]
    report.decision_framework = None

    mock_search_client = AsyncMock()
    mock_search_client.close = AsyncMock()

    with (
        patch.object(research_handler, "get_settings") as mock_settings,
        patch.object(
            research_handler,
            "TavilySearch",
            return_value=mock_search_client,
        ),
        patch.object(
            research_handler,
            "run_research",
            new_callable=AsyncMock,
            return_value=report,
        ),
        patch.object(
            research_handler,
            "create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
    ):
        settings = MagicMock()
        settings.tavily_configured = True
        settings.tavily_api_key = MagicMock()
        settings.tavily_api_key.get_secret_value.return_value = "test-key"
        mock_settings.return_value = settings

        result = await research_handler.handle_research(
            message,
            AsyncMock(),
            AsyncMock(),
            intent,
        )

    assert result.agent == "research"
    assert "Simple Research" in result.content
    assert "Decision Framework" not in result.content


@pytest.mark.asyncio
async def test_handle_research_entity_enqueue_failure_is_swallowed():
    """Entity extraction enqueue failures should not block the research reply."""
    message = _make_message()
    intent = _make_intent()
    episode = _make_episode_mock()
    research_handler = _load_research_handler()

    report = MagicMock()
    report.title = "Minimal Research"
    report.synthesis = ""
    report.findings = []
    report.search_queries = ["query1"]
    report.decision_framework = MagicMock(options=[], recommendation="")

    mock_search_client = AsyncMock()
    mock_search_client.close = AsyncMock()

    with (
        patch.object(research_handler, "get_settings") as mock_settings,
        patch.object(
            research_handler,
            "TavilySearch",
            return_value=mock_search_client,
        ),
        patch.object(
            research_handler,
            "run_research",
            new_callable=AsyncMock,
            return_value=report,
        ),
        patch.object(
            research_handler,
            "create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch.object(
            research_handler,
            "enqueue_entity_extraction",
            new_callable=AsyncMock,
            side_effect=RuntimeError("queue unavailable"),
        ),
    ):
        settings = MagicMock()
        settings.tavily_configured = True
        settings.tavily_api_key = MagicMock()
        settings.tavily_api_key.get_secret_value.return_value = "test-key"
        mock_settings.return_value = settings

        result = await research_handler.handle_research(
            message,
            AsyncMock(),
            AsyncMock(),
            intent,
        )

    assert result.agent == "research"
    assert "Minimal Research" in result.content
    mock_search_client.close.assert_awaited_once()
