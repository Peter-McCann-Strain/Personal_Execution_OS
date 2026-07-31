"""Tests for diary handler."""

from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.domain.models import (
    ChatResponse,
    DiaryEntry,
    Intent,
    IntentType,
    MessageInput,
    Specialist,
)
from src.app.second_brain.progressive_summary import ProgressiveSummaryResult


@pytest.fixture(autouse=True)
def _restore_imported_modules():
    """Keep isolated import stubs from leaking into the wider test session."""
    module_names = [
        "src.app.domain.services.handlers",
        "src.app.domain.services.handlers._common",
        "src.app.domain.services.handlers.diary",
        "src.app.persistence.repositories.episodes",
        "src.app.second_brain.gtd_processor",
        "src.app.second_brain.para_classifier",
        "src.app.second_brain.progressive_summary",
    ]
    snapshot = {name: sys.modules.get(name) for name in module_names}
    yield
    for name, module in snapshot.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _make_message(content: str = "Feeling productive today") -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _make_intent() -> Intent:
    return Intent(
        intent_type=IntentType.CAPTURE,
        confidence=0.9,
        specialist=Specialist.DIARY,
        reasoning="diary capture",
    )


def _make_diary_entry(**overrides) -> DiaryEntry:
    defaults = {
        "content": "Feeling productive today",
        "summary": "Productive day",
        "mood_score": 7.5,
        "energy_rating": 8.0,
        "tags": ["productivity"],
        "people_mentioned": [],
        "para_category": "area",
    }
    defaults.update(overrides)
    return DiaryEntry(**defaults)


def _make_episode_mock() -> MagicMock:
    episode = MagicMock()
    episode.id = uuid.uuid4()
    episode.metadata_ = {}
    return episode


def _load_diary_handler():
    """Import the diary handler without triggering eager package side effects."""
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
                / "handlers",
            ),
        ]
        sys.modules[package_name] = package

    common_module = sys.modules.get("src.app.domain.services.handlers._common")
    if common_module is None:
        common_module = ModuleType("src.app.domain.services.handlers._common")

        async def _enqueue_entity_extraction(**_kwargs):
            return None

        async def _enqueue_commitment_extraction(**_kwargs):
            return None

        common_module.enqueue_entity_extraction = _enqueue_entity_extraction
        common_module.enqueue_commitment_extraction = _enqueue_commitment_extraction
        sys.modules["src.app.domain.services.handlers._common"] = common_module

    episodes_module = sys.modules.get("src.app.persistence.repositories.episodes")
    if episodes_module is None:
        episodes_module = ModuleType("src.app.persistence.repositories.episodes")

        async def _create_episode(*_args, **_kwargs):
            raise RuntimeError("create_episode stub must be patched in tests")

        async def _update_episode(*_args, **_kwargs):
            raise RuntimeError("update_episode stub must be patched in tests")

        episodes_module.create_episode = _create_episode
        episodes_module.update_episode = _update_episode
        sys.modules["src.app.persistence.repositories.episodes"] = episodes_module

    gtd_module = sys.modules.get("src.app.second_brain.gtd_processor")
    if gtd_module is None:
        gtd_module = ModuleType("src.app.second_brain.gtd_processor")

        async def _process_gtd(*_args, **_kwargs):
            return None

        gtd_module.process_gtd = _process_gtd
        sys.modules["src.app.second_brain.gtd_processor"] = gtd_module

    para_module = sys.modules.get("src.app.second_brain.para_classifier")
    if para_module is None:
        para_module = ModuleType("src.app.second_brain.para_classifier")

        async def _classify_para(*_args, **_kwargs):
            return None

        para_module.classify_para = _classify_para
        sys.modules["src.app.second_brain.para_classifier"] = para_module

    summary_module = sys.modules.get("src.app.second_brain.progressive_summary")
    if summary_module is None:
        summary_module = ModuleType("src.app.second_brain.progressive_summary")

        async def _generate_progressive_summary(*_args, **_kwargs):
            return None

        summary_module.generate_progressive_summary = _generate_progressive_summary
        sys.modules["src.app.second_brain.progressive_summary"] = summary_module

    return importlib.import_module("src.app.domain.services.handlers.diary")


@pytest.mark.asyncio
async def test_handle_diary_happy_path():
    """handle_diary processes entry, stores episode, and returns ChatResponse."""
    message = _make_message()
    intent = _make_intent()
    entry = _make_diary_entry()
    episode = _make_episode_mock()
    diary = _load_diary_handler()

    mock_client = AsyncMock()
    mock_session = AsyncMock()

    with (
        patch.object(
            diary,
            "process_diary_entry",
            new_callable=AsyncMock,
            return_value=entry,
        ) as mock_process,
        patch.object(
            diary,
            "create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ) as mock_create,
        patch.object(
            diary,
            "enqueue_entity_extraction",
            new_callable=AsyncMock,
        ) as mock_enqueue,
        patch.object(
            diary,
            "_run_second_brain_enrichment",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        result = await diary.handle_diary(message, mock_client, mock_session, intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "diary"
    assert "Productive day" in result.content
    assert result.metadata["episode_id"] == str(episode.id)
    assert result.metadata["mood_score"] == 7.5
    assert result.metadata["tags"] == ["productivity"]

    mock_process.assert_awaited_once_with(message.content, mock_client)
    mock_create.assert_awaited_once()
    mock_session.commit.assert_awaited_once()
    mock_enqueue.assert_awaited_once_with(
        episode_id=str(episode.id),
        text_content=entry.content,
    )


@pytest.mark.asyncio
async def test_handle_diary_llm_failure_propagates():
    """handle_diary propagates LLM errors (no silent fallback)."""
    message = _make_message()
    intent = _make_intent()
    diary = _load_diary_handler()

    with (
        patch.object(
            diary,
            "process_diary_entry",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Claude API failed"),
        ),
        pytest.raises(RuntimeError, match="Claude API failed"),
    ):
        await diary.handle_diary(message, AsyncMock(), AsyncMock(), intent)


@pytest.mark.asyncio
async def test_handle_diary_db_failure_propagates():
    """handle_diary propagates database errors."""
    message = _make_message()
    intent = _make_intent()
    entry = _make_diary_entry()
    diary = _load_diary_handler()

    with (
        patch.object(
            diary,
            "process_diary_entry",
            new_callable=AsyncMock,
            return_value=entry,
        ),
        patch.object(
            diary,
            "create_episode",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB connection lost"),
        ),
        pytest.raises(RuntimeError, match="DB connection lost"),
    ):
        await diary.handle_diary(message, AsyncMock(), AsyncMock(), intent)


@pytest.mark.asyncio
async def test_handle_diary_enqueue_success():
    """Diary succeeds when entity-extraction enqueue completes."""
    message = _make_message()
    intent = _make_intent()
    entry = _make_diary_entry()
    episode = _make_episode_mock()
    diary = _load_diary_handler()

    with (
        patch.object(
            diary,
            "process_diary_entry",
            new_callable=AsyncMock,
            return_value=entry,
        ),
        patch.object(
            diary,
            "create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch.object(
            diary,
            "enqueue_entity_extraction",
            new_callable=AsyncMock,
        ),
        patch.object(
            diary,
            "_run_second_brain_enrichment",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        result = await diary.handle_diary(message, AsyncMock(), AsyncMock(), intent)

    assert isinstance(result, ChatResponse)
    assert result.agent == "diary"


@pytest.mark.asyncio
async def test_handle_diary_includes_enrichment_metadata():
    """handle_diary exposes GTD and progressive-summary metadata when present."""
    message = _make_message()
    intent = _make_intent()
    entry = _make_diary_entry(para_category=None)
    episode = _make_episode_mock()
    diary = _load_diary_handler()

    with (
        patch.object(
            diary,
            "process_diary_entry",
            new_callable=AsyncMock,
            return_value=entry,
        ),
        patch.object(
            diary,
            "create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch.object(
            diary,
            "enqueue_entity_extraction",
            new_callable=AsyncMock,
        ),
        patch.object(
            diary,
            "enqueue_commitment_extraction",
            new_callable=AsyncMock,
        ),
        patch.object(
            diary,
            "_run_second_brain_enrichment",
            new_callable=AsyncMock,
            return_value={
                "para_category": "resource",
                "gtd": {"next_actions": ["Send the note"]},
                "progressive_summary": True,
            },
        ),
    ):
        result = await diary.handle_diary(message, AsyncMock(), AsyncMock(), intent)

    assert result.metadata["para_category"] == "resource"
    assert result.metadata["gtd"] == {"next_actions": ["Send the note"]}
    assert result.metadata["progressive_summary"] is True


@pytest.mark.asyncio
async def test_run_second_brain_enrichment_success_updates_episode():
    """Successful enrichment stores PARA and progressive-summary updates."""
    episode = _make_episode_mock()
    session = AsyncMock()
    summary = ProgressiveSummaryResult(
        layer_2_passages=["Keep the core insight"],
        layer_3_highlights=["Insight"],
        layer_4_summary="Short executive summary.",
    )
    diary = _load_diary_handler()

    with (
        patch.object(
            diary,
            "_enrich_para",
            new_callable=AsyncMock,
            return_value="resource",
        ),
        patch.object(
            diary,
            "_enrich_gtd",
            new_callable=AsyncMock,
            return_value={"next_actions": ["File the draft"]},
        ),
        patch.object(
            diary,
            "_enrich_progressive_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ),
        patch.object(
            diary,
            "update_episode",
            new_callable=AsyncMock,
        ) as mock_update,
    ):
        result = await diary._run_second_brain_enrichment(
            episode=episode,
            content="Today's entry",
            current_para=None,
            client=AsyncMock(),
            session=session,
        )

    assert result == {
        "para_category": "resource",
        "gtd": {"next_actions": ["File the draft"]},
        "progressive_summary": True,
    }
    assert mock_update.await_count == 2
    mock_update.assert_any_await(session, episode.id, para_category="resource")
    mock_update.assert_any_await(
        session,
        episode.id,
        metadata={
            "progressive_summary": {
                "layer_2_passages": ["Keep the core insight"],
                "layer_3_highlights": ["Insight"],
                "layer_4_summary": "Short executive summary.",
            }
        },
    )
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_run_second_brain_enrichment_propagates_failures():
    """Enrichment failures should propagate."""
    episode = _make_episode_mock()
    session = AsyncMock()
    diary = _load_diary_handler()

    with (
        patch.object(
            diary,
            "_enrich_para",
            new_callable=AsyncMock,
            side_effect=RuntimeError("para failed"),
        ),
        patch.object(
            diary,
            "_enrich_gtd",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            diary,
            "_enrich_progressive_summary",
            new_callable=AsyncMock,
            return_value=None,
        ),
        pytest.raises(RuntimeError, match="para failed"),
    ):
        await diary._run_second_brain_enrichment(
            episode=episode,
            content="Today's entry",
            current_para=None,
            client=AsyncMock(),
            session=session,
        )
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_second_brain_enrichment_db_update_failure_propagates():
    """Persistence failures during enrichment should propagate."""
    episode = _make_episode_mock()
    session = AsyncMock()
    summary = ProgressiveSummaryResult(
        layer_2_passages=["passage"],
        layer_3_highlights=["highlight"],
        layer_4_summary="summary",
    )
    diary = _load_diary_handler()

    with (
        patch.object(
            diary,
            "_enrich_para",
            new_callable=AsyncMock,
            return_value="project",
        ),
        patch.object(
            diary,
            "_enrich_gtd",
            new_callable=AsyncMock,
            return_value={"captured": True},
        ),
        patch.object(
            diary,
            "_enrich_progressive_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ),
        patch.object(
            diary,
            "update_episode",
            new_callable=AsyncMock,
            side_effect=RuntimeError("para write failed"),
        ),
        pytest.raises(RuntimeError, match="para write failed"),
    ):
        await diary._run_second_brain_enrichment(
            episode=episode,
            content="Today's entry",
            current_para=None,
            client=AsyncMock(),
            session=session,
        )
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_second_brain_enrichment_omits_progressive_summary_when_unavailable():
    """A missing progressive summary should not add summary metadata."""
    episode = _make_episode_mock()
    session = AsyncMock()
    diary = _load_diary_handler()

    with (
        patch.object(
            diary,
            "_enrich_para",
            new_callable=AsyncMock,
            return_value="area",
        ),
        patch.object(
            diary,
            "_enrich_gtd",
            new_callable=AsyncMock,
            return_value={"next_actions": ["File the draft"]},
        ),
        patch.object(
            diary,
            "_enrich_progressive_summary",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            diary,
            "update_episode",
            new_callable=AsyncMock,
        ) as mock_update,
    ):
        result = await diary._run_second_brain_enrichment(
            episode=episode,
            content="Today's entry",
            current_para=None,
            client=AsyncMock(),
            session=session,
        )

    assert result == {
        "para_category": "area",
        "gtd": {"next_actions": ["File the draft"]},
    }
    mock_update.assert_awaited_once_with(session, episode.id, para_category="area")
    assert session.commit.await_count == 1


@pytest.mark.asyncio
async def test_enrich_para_skips_when_already_classified():
    """_enrich_para returns None when the specialist already classified the entry."""
    diary = _load_diary_handler()

    result = await diary._enrich_para("Content", "area", AsyncMock())

    assert result is None


@pytest.mark.asyncio
async def test_enrich_para_calls_classifier():
    """_enrich_para delegates to classify_para when needed."""
    diary = _load_diary_handler()
    with patch.object(
        diary,
        "classify_para",
        new_callable=AsyncMock,
        return_value="resource",
    ) as mock_classify:
        result = await diary._enrich_para("Content", None, AsyncMock())

    assert result == "resource"
    mock_classify.assert_awaited_once()


@pytest.mark.asyncio
async def test_enrich_gtd_and_progressive_summary_delegate():
    """Simple helper wrappers delegate to their second-brain services."""
    diary = _load_diary_handler()
    with (
        patch.object(
            diary,
            "process_gtd",
            new_callable=AsyncMock,
            return_value={"next_actions": ["Do it"]},
        ) as mock_gtd,
        patch.object(
            diary,
            "generate_progressive_summary",
            new_callable=AsyncMock,
            return_value=ProgressiveSummaryResult(
                layer_2_passages=["a"],
                layer_3_highlights=["b"],
                layer_4_summary="c",
            ),
        ) as mock_summary,
    ):
        gtd_result = await diary._enrich_gtd("Content", AsyncMock())
        summary_result = await diary._enrich_progressive_summary("Content", AsyncMock())

    assert gtd_result == {"next_actions": ["Do it"]}
    assert summary_result.layer_4_summary == "c"
    mock_gtd.assert_awaited_once()
    mock_summary.assert_awaited_once()
