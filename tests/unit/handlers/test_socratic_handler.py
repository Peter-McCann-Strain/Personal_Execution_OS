"""Tests for the Socratic tutorial handler."""

from __future__ import annotations

import contextlib
import importlib
import sys
import uuid
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.socratic.state import WorkType
from src.app.domain.models import (
    ChatResponse,
    Intent,
    IntentType,
    MessageInput,
    Specialist,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(content: str = "My essay about caching...") -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _make_intent() -> Intent:
    return Intent(
        intent_type=IntentType.TUTORIAL,
        confidence=0.95,
        specialist=Specialist.SOCRATIC,
        reasoning="Socratic tutorial request",
    )


def _make_tutorial_mock(**overrides) -> MagicMock:
    """Create a mock TutorialSession ORM object."""
    tutorial = MagicMock()
    tutorial.id = overrides.get("id", uuid.uuid4())
    tutorial.user_id = overrides.get("user_id", "user-1")
    tutorial.topic = overrides.get("topic", "Caching strategies")
    tutorial.work_type = overrides.get("work_type", "essay")
    tutorial.submitted_work = overrides.get("submitted_work", "My essay...")
    tutorial.phase = overrides.get("phase", "submitted")
    tutorial.propositions = overrides.get("propositions")
    tutorial.preparation = overrides.get("preparation")
    tutorial.transcript = overrides.get("transcript")
    tutorial.analysis = overrides.get("analysis")
    return tutorial


def _mock_settings():
    settings = MagicMock()
    settings.socratic_tutor_model = "claude-sonnet-4-6"
    settings.socratic_tutor_max_tokens = 2048
    settings.socratic_devils_advocate_model = "claude-opus-4-6"
    settings.socratic_devils_advocate_max_tokens = 2048
    settings.socratic_clarifier_model = "claude-haiku-4-5-20251001"
    settings.socratic_clarifier_max_tokens = 1024
    settings.socratic_connector_model = "claude-sonnet-4-6"
    settings.socratic_connector_max_tokens = 1024
    settings.socratic_assessor_model = "claude-haiku-4-5-20251001"
    settings.socratic_assessor_max_tokens = 1024
    settings.socratic_preparation_model = "claude-sonnet-4-6"
    settings.socratic_preparation_max_tokens = 4096
    settings.socratic_analysis_model = "claude-sonnet-4-6"
    settings.socratic_analysis_max_tokens = 8192
    settings.socratic_working_memory_turns = 6
    settings.socratic_max_propositions = 20
    return settings


@pytest.fixture(autouse=True)
def _patch_settings():
    with patch(
        "src.app.config.get_settings",
        return_value=_mock_settings(),
    ):
        yield


@pytest.fixture(autouse=True)
def _prepare_socratic_handler_module():
    """Load the handler through a lightweight package stub and restore imports afterwards."""
    module_names = [
        "src.app.domain.services.handlers",
        "src.app.domain.services.handlers.socratic",
        "src.app.agents.socratic.analysis",
        "src.app.agents.socratic.graph",
        "src.app.persistence.repositories.tutorials",
    ]
    snapshot = {name: sys.modules.get(name) for name in module_names}
    services_module = importlib.import_module("src.app.domain.services")
    previous_handlers_attr = getattr(services_module, "handlers", None)
    had_handlers_attr = hasattr(services_module, "handlers")

    _load_socratic_handler()
    yield

    for name, module in snapshot.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module

    if had_handlers_attr:
        services_module.handlers = previous_handlers_attr
    else:
        with contextlib.suppress(AttributeError):
            delattr(services_module, "handlers")


def _load_socratic_handler():
    """Import the Socratic handler without triggering eager package side effects."""
    package_name = "src.app.domain.services.handlers"
    services_module = importlib.import_module("src.app.domain.services")

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
    services_module.handlers = package

    tutorials_module = sys.modules.get("src.app.persistence.repositories.tutorials")
    if tutorials_module is None:
        tutorials_module = ModuleType("src.app.persistence.repositories.tutorials")

        async def _create_tutorial_session(*_args, **_kwargs):
            raise RuntimeError("create_tutorial_session stub must be patched in tests")

        async def _get_active_tutorial(*_args, **_kwargs):
            raise RuntimeError("get_active_tutorial stub must be patched in tests")

        async def _get_tutorial_session(*_args, **_kwargs):
            raise RuntimeError("get_tutorial_session stub must be patched in tests")

        async def _store_preparation(*_args, **_kwargs):
            raise RuntimeError("store_preparation stub must be patched in tests")

        async def _store_tutorial_results(*_args, **_kwargs):
            raise RuntimeError("store_tutorial_results stub must be patched in tests")

        async def _update_tutorial_phase(*_args, **_kwargs):
            raise RuntimeError("update_tutorial_phase stub must be patched in tests")

        tutorials_module.create_tutorial_session = _create_tutorial_session
        tutorials_module.get_active_tutorial = _get_active_tutorial
        tutorials_module.get_tutorial_session = _get_tutorial_session
        tutorials_module.store_preparation = _store_preparation
        tutorials_module.store_tutorial_results = _store_tutorial_results
        tutorials_module.update_tutorial_phase = _update_tutorial_phase
        sys.modules["src.app.persistence.repositories.tutorials"] = tutorials_module

    analysis_module = sys.modules.get("src.app.agents.socratic.analysis")
    if analysis_module is None:
        analysis_module = ModuleType("src.app.agents.socratic.analysis")

        async def _analyse_tutorial(*_args, **_kwargs):
            raise RuntimeError("analyse_tutorial stub must be patched in tests")

        def _format_analysis_report(*_args, **_kwargs):
            raise RuntimeError("format_analysis_report stub must be patched in tests")

        analysis_module.analyse_tutorial = _analyse_tutorial
        analysis_module.format_analysis_report = _format_analysis_report
        sys.modules["src.app.agents.socratic.analysis"] = analysis_module

    graph_module = sys.modules.get("src.app.agents.socratic.graph")
    if graph_module is None:
        graph_module = ModuleType("src.app.agents.socratic.graph")

        def _build_dialogue_graph(*_args, **_kwargs):
            raise RuntimeError("build_dialogue_graph stub must be patched in tests")

        def _build_preparation_graph(*_args, **_kwargs):
            raise RuntimeError("build_preparation_graph stub must be patched in tests")

        graph_module.build_dialogue_graph = _build_dialogue_graph
        graph_module.build_preparation_graph = _build_preparation_graph
        sys.modules["src.app.agents.socratic.graph"] = graph_module

    return importlib.import_module("src.app.domain.services.handlers.socratic")


# ---------------------------------------------------------------------------
# handle_socratic
# ---------------------------------------------------------------------------


class TestHandleSocratic:
    async def test_happy_path_creates_and_prepares(self):
        """Submit work → create session → prepare → return ready."""
        message = _make_message()
        intent = _make_intent()
        tutorial = _make_tutorial_mock(phase="submitted")

        with (
            patch(
                "src.app.domain.services.handlers.socratic.get_active_tutorial",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.create_tutorial_session",
                new_callable=AsyncMock,
                return_value=tutorial,
            ) as mock_create,
            patch(
                "src.app.domain.services.handlers.socratic._run_preparation",
                new_callable=AsyncMock,
            ) as mock_prep,
        ):
            from src.app.domain.services.handlers.socratic import handle_socratic

            mock_session = AsyncMock()
            result = await handle_socratic(message, AsyncMock(), mock_session, intent)

        assert isinstance(result, ChatResponse)
        assert result.agent == "socratic"
        assert "prepared" in result.content.lower() or "ready" in result.content.lower()
        assert result.metadata["phase"] == "ready"
        assert result.metadata["tutorial_id"] == str(tutorial.id)
        mock_create.assert_awaited_once()
        mock_prep.assert_awaited_once()
        mock_session.commit.assert_awaited()

    async def test_active_ready_tutorial_returns_hint(self):
        """When user has a ready tutorial, return hint to start it."""
        message = _make_message()
        intent = _make_intent()
        active = _make_tutorial_mock(phase="ready")

        with patch(
            "src.app.domain.services.handlers.socratic.get_active_tutorial",
            new_callable=AsyncMock,
            return_value=active,
        ):
            from src.app.domain.services.handlers.socratic import handle_socratic

            result = await handle_socratic(message, AsyncMock(), AsyncMock(), intent)

        assert "start tutorial" in result.content.lower()
        assert result.metadata["phase"] == "ready"

    async def test_active_dialogue_tutorial_returns_hint(self):
        """When user has active dialogue, return hint to continue."""
        message = _make_message()
        intent = _make_intent()
        active = _make_tutorial_mock(phase="dialogue")

        with patch(
            "src.app.domain.services.handlers.socratic.get_active_tutorial",
            new_callable=AsyncMock,
            return_value=active,
        ):
            from src.app.domain.services.handlers.socratic import handle_socratic

            result = await handle_socratic(message, AsyncMock(), AsyncMock(), intent)

        assert "active tutorial" in result.content.lower()
        assert result.metadata["phase"] == "dialogue"

    async def test_preparing_tutorial_returns_wait(self):
        """When tutorial is being prepared, tell user to wait."""
        message = _make_message()
        intent = _make_intent()
        active = _make_tutorial_mock(phase="preparing")

        with patch(
            "src.app.domain.services.handlers.socratic.get_active_tutorial",
            new_callable=AsyncMock,
            return_value=active,
        ):
            from src.app.domain.services.handlers.socratic import handle_socratic

            result = await handle_socratic(message, AsyncMock(), AsyncMock(), intent)

        assert "prepared" in result.content.lower() or "notify" in result.content.lower()

    async def test_llm_failure_propagates(self):
        """Preparation failure propagates (no silent fallback)."""
        message = _make_message()
        intent = _make_intent()
        tutorial = _make_tutorial_mock()

        with (
            patch(
                "src.app.domain.services.handlers.socratic.get_active_tutorial",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.create_tutorial_session",
                new_callable=AsyncMock,
                return_value=tutorial,
            ),
            patch(
                "src.app.domain.services.handlers.socratic._run_preparation",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM failed"),
            ),
            pytest.raises(RuntimeError, match="LLM failed"),
        ):
            from src.app.domain.services.handlers.socratic import handle_socratic

            await handle_socratic(message, AsyncMock(), AsyncMock(), intent)

    def test_detect_work_type_branches(self):
        """The work-type heuristic should classify the main content families."""
        from src.app.domain.services.handlers.socratic import _detect_work_type

        assert _detect_work_type("def main():\n    pass") == WorkType.CODE
        assert _detect_work_type("This is a case study about X") == WorkType.CASE_STUDY
        assert _detect_work_type("A blog post about caching") == WorkType.BLOG
        assert _detect_work_type("My argument is clear") == WorkType.ARGUMENT
        assert _detect_work_type("Research findings from the study") == WorkType.RESEARCH
        assert _detect_work_type("System architecture and design notes") == WorkType.DESIGN
        assert _detect_work_type("A plain essay") == WorkType.ESSAY

    def test_extract_topic_branches(self):
        """The topic extractor should handle empty, normal, and truncated input."""
        from src.app.domain.services.handlers.socratic import _extract_topic

        assert _extract_topic("") == "Untitled tutorial"
        assert _extract_topic("Short topic") == "Short topic"

        long_topic = "X" * 120
        extracted = _extract_topic(long_topic)
        assert extracted.endswith("...")
        assert len(extracted) == 100


# ---------------------------------------------------------------------------
# start_tutorial
# ---------------------------------------------------------------------------


class TestStartTutorial:
    async def test_happy_path(self):
        """Start a ready tutorial → return opening question."""
        tutorial = _make_tutorial_mock(
            phase="ready",
            propositions=[{"index": 0, "text": "Claim"}],
            preparation={
                "tutor_prep": {"opening_question": "Explain."},
                "devils_advocate_prep": {},
                "clarifier_prep": {},
                "connector_prep": {},
            },
        )

        mock_graph = MagicMock()
        mock_compiled = AsyncMock()
        mock_compiled.ainvoke = AsyncMock(
            return_value={
                "dialogue_history": [{"role": "tutor", "content": "Tell me about caching."}],
                "phase": "dialogue",
            }
        )
        mock_graph.compile.return_value = mock_compiled

        with (
            patch(
                "src.app.domain.services.handlers.socratic.get_tutorial_session",
                new_callable=AsyncMock,
                return_value=tutorial,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.build_dialogue_graph",
                return_value=mock_graph,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.update_tutorial_phase",
                new_callable=AsyncMock,
            ) as mock_phase,
        ):
            from src.app.domain.services.handlers.socratic import start_tutorial

            mock_session = AsyncMock()
            result = await start_tutorial(tutorial.id, AsyncMock(), mock_session)

        assert isinstance(result, ChatResponse)
        assert result.agent == "socratic"
        assert "caching" in result.content.lower()
        assert result.metadata["phase"] == "dialogue"
        mock_phase.assert_awaited_once()

    async def test_not_found(self):
        """start_tutorial with invalid ID → not found."""
        with patch(
            "src.app.domain.services.handlers.socratic.get_tutorial_session",
            new_callable=AsyncMock,
            return_value=None,
        ):
            from src.app.domain.services.handlers.socratic import start_tutorial

            result = await start_tutorial(uuid.uuid4(), AsyncMock(), AsyncMock())

        assert "not found" in result.content.lower()
        assert result.metadata.get("error") == "not_found"

    async def test_wrong_phase(self):
        """start_tutorial on a submitted (not ready) tutorial → error."""
        tutorial = _make_tutorial_mock(phase="submitted")

        with patch(
            "src.app.domain.services.handlers.socratic.get_tutorial_session",
            new_callable=AsyncMock,
            return_value=tutorial,
        ):
            from src.app.domain.services.handlers.socratic import start_tutorial

            result = await start_tutorial(tutorial.id, AsyncMock(), AsyncMock())

        assert "not ready" in result.content.lower()

    async def test_happy_path_without_stored_preparation(self):
        """Start a ready tutorial with no stored prep data."""
        tutorial = _make_tutorial_mock(
            phase="ready",
            propositions=None,
            preparation=None,
        )

        mock_graph = MagicMock()
        mock_compiled = AsyncMock()
        mock_compiled.ainvoke = AsyncMock(
            return_value={
                "dialogue_history": [{"role": "tutor", "content": "Let's begin."}],
                "phase": "dialogue",
            }
        )
        mock_graph.compile.return_value = mock_compiled

        with (
            patch(
                "src.app.domain.services.handlers.socratic.get_tutorial_session",
                new_callable=AsyncMock,
                return_value=tutorial,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.build_dialogue_graph",
                return_value=mock_graph,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.update_tutorial_phase",
                new_callable=AsyncMock,
            ),
        ):
            from src.app.domain.services.handlers.socratic import start_tutorial

            result = await start_tutorial(tutorial.id, AsyncMock(), AsyncMock())

        assert result.content == "Let's begin."
        mock_compiled.ainvoke.assert_awaited_once()
        invoked_state = mock_compiled.ainvoke.await_args.args[0]
        assert invoked_state.get("propositions", []) == []
        assert invoked_state.get("claims_unresolved", []) == []


# ---------------------------------------------------------------------------
# process_tutorial_turn
# ---------------------------------------------------------------------------


class TestProcessTutorialTurn:
    async def test_happy_path(self):
        """Process a mid-dialogue turn → return agent response."""
        tutorial = _make_tutorial_mock(phase="dialogue")

        mock_graph = MagicMock()
        mock_compiled = AsyncMock()
        mock_compiled.ainvoke = AsyncMock(
            return_value={
                "dialogue_history": [
                    {"role": "user", "content": "Caching stores data."},
                    {"role": "tutor", "content": "What evidence supports that?"},
                ],
                "phase": "dialogue",
                "current_turn": 3,
                "bloom_level": "understand",
            }
        )
        mock_graph.compile.return_value = mock_compiled

        with (
            patch(
                "src.app.domain.services.handlers.socratic.get_tutorial_session",
                new_callable=AsyncMock,
                return_value=tutorial,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.build_dialogue_graph",
                return_value=mock_graph,
            ),
        ):
            from src.app.domain.services.handlers.socratic import process_tutorial_turn

            result = await process_tutorial_turn(
                tutorial.id,
                "Caching stores data.",
                AsyncMock(),
                AsyncMock(),
            )

        assert isinstance(result, ChatResponse)
        assert "evidence" in result.content.lower()
        assert result.metadata["turn"] == 3

    async def test_tutorial_completion(self):
        """When tutorial ends, analysis is run and stored."""
        tutorial = _make_tutorial_mock(phase="dialogue")

        mock_graph = MagicMock()
        mock_compiled = AsyncMock()
        mock_compiled.ainvoke = AsyncMock(
            return_value={
                "dialogue_history": [{"role": "tutor", "content": "Great session."}],
                "phase": "complete",
                "current_turn": 8,
                "bloom_level": "analyse",
                "assessor_log": [],
                "speaking_ratio": {"user_words": 200, "agent_words": 50},
            }
        )
        mock_graph.compile.return_value = mock_compiled

        from src.app.agents.socratic.state import TutorialAnalysis

        mock_analysis = TutorialAnalysis(
            summary="Strong session.",
            knowledge_gaps=[],
        )

        with (
            patch(
                "src.app.domain.services.handlers.socratic.get_tutorial_session",
                new_callable=AsyncMock,
                return_value=tutorial,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.build_dialogue_graph",
                return_value=mock_graph,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.analyse_tutorial",
                new_callable=AsyncMock,
                return_value=mock_analysis,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.format_analysis_report",
                return_value="## Analysis\nStrong session.",
            ),
            patch(
                "src.app.domain.services.handlers.socratic.store_tutorial_results",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            from src.app.domain.services.handlers.socratic import process_tutorial_turn

            mock_session = AsyncMock()
            result = await process_tutorial_turn(
                tutorial.id,
                "I learned a lot.",
                AsyncMock(),
                mock_session,
            )

        assert "complete" in result.content.lower() or "analysis" in result.content.lower()
        assert result.metadata["phase"] == "complete"
        mock_store.assert_awaited_once()
        mock_session.commit.assert_awaited()

    async def test_not_found(self):
        """process_tutorial_turn with invalid ID → not found."""
        with patch(
            "src.app.domain.services.handlers.socratic.get_tutorial_session",
            new_callable=AsyncMock,
            return_value=None,
        ):
            from src.app.domain.services.handlers.socratic import process_tutorial_turn

            result = await process_tutorial_turn(
                uuid.uuid4(),
                "msg",
                AsyncMock(),
                AsyncMock(),
            )

        assert "not found" in result.content.lower()

    def test_helper_branches(self):
        """Helper branches should handle empty aggregates and populated logs."""
        from src.app.domain.services.handlers.socratic import (
            _calc_speaking_ratio,
            _get_bloom_start,
        )

        assert _calc_speaking_ratio({"speaking_ratio": {"user_words": 0, "agent_words": 0}}) is None
        assert _calc_speaking_ratio({"speaking_ratio": {"user_words": 3, "agent_words": 1}}) == 75.0
        assert _get_bloom_start({"assessor_log": []}) is None
        assert _get_bloom_start({"assessor_log": [{"bloom_level": "understand"}]}) == "understand"


# ---------------------------------------------------------------------------
# end_tutorial
# ---------------------------------------------------------------------------


class TestEndTutorial:
    async def test_happy_path_with_dialogue(self):
        """End tutorial with dialogue → runs analysis → returns report."""
        tutorial = _make_tutorial_mock(phase="dialogue")

        mock_snapshot = MagicMock()
        mock_snapshot.values = {
            "dialogue_history": [
                {"role": "tutor", "content": "What is caching?"},
                {"role": "user", "content": "Storing data."},
            ],
            "assessor_log": [],
            "current_turn": 2,
            "speaking_ratio": {"user_words": 10, "agent_words": 15},
            "bloom_level": "understand",
        }

        mock_graph = MagicMock()
        mock_compiled = AsyncMock()
        mock_compiled.aget_state = AsyncMock(return_value=mock_snapshot)
        mock_graph.compile.return_value = mock_compiled

        from src.app.agents.socratic.state import TutorialAnalysis

        mock_analysis = TutorialAnalysis(summary="Partial analysis.")

        with (
            patch(
                "src.app.domain.services.handlers.socratic.get_tutorial_session",
                new_callable=AsyncMock,
                return_value=tutorial,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.build_dialogue_graph",
                return_value=mock_graph,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.analyse_tutorial",
                new_callable=AsyncMock,
                return_value=mock_analysis,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.format_analysis_report",
                return_value="## Partial\nPartial analysis.",
            ),
            patch(
                "src.app.domain.services.handlers.socratic.store_tutorial_results",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            from src.app.domain.services.handlers.socratic import end_tutorial

            mock_session = AsyncMock()
            result = await end_tutorial(tutorial.id, AsyncMock(), mock_session)

        assert isinstance(result, ChatResponse)
        assert "ended early" in result.content.lower()
        assert result.metadata["phase"] == "complete"
        mock_store.assert_awaited_once()

    async def test_no_dialogue(self):
        """End tutorial with no dialogue → no analysis, just close."""
        tutorial = _make_tutorial_mock(phase="ready")

        mock_snapshot = MagicMock()
        mock_snapshot.values = {"dialogue_history": []}

        mock_graph = MagicMock()
        mock_compiled = AsyncMock()
        mock_compiled.aget_state = AsyncMock(return_value=mock_snapshot)
        mock_graph.compile.return_value = mock_compiled

        with (
            patch(
                "src.app.domain.services.handlers.socratic.get_tutorial_session",
                new_callable=AsyncMock,
                return_value=tutorial,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.build_dialogue_graph",
                return_value=mock_graph,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.update_tutorial_phase",
                new_callable=AsyncMock,
            ) as mock_phase,
        ):
            from src.app.domain.services.handlers.socratic import end_tutorial

            mock_session = AsyncMock()
            result = await end_tutorial(tutorial.id, AsyncMock(), mock_session)

        assert "no dialogue" in result.content.lower()
        mock_phase.assert_awaited_once()

    async def test_not_found(self):
        """end_tutorial with invalid ID → not found."""
        with patch(
            "src.app.domain.services.handlers.socratic.get_tutorial_session",
            new_callable=AsyncMock,
            return_value=None,
        ):
            from src.app.domain.services.handlers.socratic import end_tutorial

            result = await end_tutorial(uuid.uuid4(), AsyncMock(), AsyncMock())

        assert "not found" in result.content.lower()


class TestRunPreparation:
    async def test_runs_graph_and_stores_preparation(self):
        """Preparation graph output should be persisted and committed."""
        tutorial_id = uuid.uuid4()
        mock_graph = MagicMock()
        mock_compiled = AsyncMock()
        mock_compiled.ainvoke = AsyncMock(
            return_value={
                "propositions": [{"index": 0, "text": "Caching reduces latency"}],
                "tutor_prep": {"opening_question": "What is caching?"},
                "devils_advocate_prep": {"counter_arguments": ["Cold cache misses"]},
                "clarifier_prep": {"ambiguities": ["Cache scope"]},
                "connector_prep": {"links": ["Redis note"]},
            }
        )
        mock_graph.compile.return_value = mock_compiled

        with (
            patch(
                "src.app.domain.services.handlers.socratic.build_preparation_graph",
                return_value=mock_graph,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.store_preparation",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            from src.app.domain.services.handlers.socratic import _run_preparation

            mock_session = AsyncMock()
            await _run_preparation(
                tutorial_id=tutorial_id,
                user_id="user-1",
                topic="Caching strategies",
                submitted_work="My essay about caching.",
                work_type=WorkType.ESSAY,
                client=AsyncMock(),
                session=mock_session,
            )

        mock_graph.compile.assert_called_once_with()
        mock_compiled.ainvoke.assert_awaited_once()
        mock_store.assert_awaited_once_with(
            mock_session,
            tutorial_id,
            propositions=[{"index": 0, "text": "Caching reduces latency"}],
            preparation={
                "tutor_prep": {"opening_question": "What is caching?"},
                "devils_advocate_prep": {"counter_arguments": ["Cold cache misses"]},
                "clarifier_prep": {"ambiguities": ["Cache scope"]},
                "connector_prep": {"links": ["Redis note"]},
            },
        )
        mock_session.commit.assert_awaited_once()

    async def test_defaults_missing_preparation_sections(self):
        """Missing graph keys should be stored as empty lists or dicts."""
        tutorial_id = uuid.uuid4()
        mock_graph = MagicMock()
        mock_compiled = AsyncMock()
        mock_compiled.ainvoke = AsyncMock(return_value={})
        mock_graph.compile.return_value = mock_compiled

        with (
            patch(
                "src.app.domain.services.handlers.socratic.build_preparation_graph",
                return_value=mock_graph,
            ),
            patch(
                "src.app.domain.services.handlers.socratic.store_preparation",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            from src.app.domain.services.handlers.socratic import _run_preparation

            await _run_preparation(
                tutorial_id=tutorial_id,
                user_id="user-2",
                topic="Untitled",
                submitted_work="Brief note",
                work_type=WorkType.ESSAY,
                client=AsyncMock(),
                session=AsyncMock(),
            )

        mock_store.assert_awaited_once()
        kwargs = mock_store.await_args.kwargs
        assert kwargs["propositions"] == []
        assert kwargs["preparation"] == {
            "tutor_prep": {},
            "devils_advocate_prep": {},
            "clarifier_prep": {},
            "connector_prep": {},
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestDetectWorkType:
    def test_detects_code(self):
        from src.app.domain.services.handlers.socratic import _detect_work_type

        assert _detect_work_type("def foo():\n    pass") == "code"
        assert _detect_work_type("class MyClass:") == "code"
        assert _detect_work_type("import os") == "code"
        assert _detect_work_type("Here is some ```python code```") == "code"

    def test_detects_case_study(self):
        from src.app.domain.services.handlers.socratic import _detect_work_type

        assert _detect_work_type("This case study examines...") == "case_study"
        assert _detect_work_type("A case-study of Netflix.") == "case_study"

    def test_detects_blog(self):
        from src.app.domain.services.handlers.socratic import _detect_work_type

        assert _detect_work_type("My blog post about AI.") == "blog"
        assert _detect_work_type("In this article, I argue...") == "blog"

    def test_detects_argument(self):
        from src.app.domain.services.handlers.socratic import _detect_work_type

        assert _detect_work_type("My thesis on caching.") == "argument"
        assert _detect_work_type("This argument shows...") == "argument"

    def test_detects_research(self):
        from src.app.domain.services.handlers.socratic import _detect_work_type

        assert _detect_work_type("My research findings show...") == "research"

    def test_detects_design(self):
        from src.app.domain.services.handlers.socratic import _detect_work_type

        assert _detect_work_type("This system design includes...") == "design"
        assert _detect_work_type("The architecture uses...") == "design"

    def test_defaults_to_essay(self):
        from src.app.domain.services.handlers.socratic import _detect_work_type

        assert _detect_work_type("Caching improves performance by...") == "essay"
        assert _detect_work_type("Hello world") == "essay"


class TestExtractTopic:
    def test_extracts_first_line(self):
        from src.app.domain.services.handlers.socratic import _extract_topic

        assert _extract_topic("Caching\nMore content") == "Caching"

    def test_truncates_long_line(self):
        from src.app.domain.services.handlers.socratic import _extract_topic

        long = "A" * 200
        result = _extract_topic(long)
        assert len(result) == 100
        assert result.endswith("...")

    def test_empty_content(self):
        from src.app.domain.services.handlers.socratic import _extract_topic

        assert _extract_topic("") == "Untitled tutorial"
        assert _extract_topic("   ") == "Untitled tutorial"


class TestCalcSpeakingRatio:
    def test_normal_ratio(self):
        from src.app.domain.services.handlers.socratic import _calc_speaking_ratio

        state = {"speaking_ratio": {"user_words": 80, "agent_words": 20}}
        assert _calc_speaking_ratio(state) == 80.0

    def test_zero_total(self):
        from src.app.domain.services.handlers.socratic import _calc_speaking_ratio

        state = {"speaking_ratio": {"user_words": 0, "agent_words": 0}}
        assert _calc_speaking_ratio(state) is None

    def test_missing_ratio(self):
        from src.app.domain.services.handlers.socratic import _calc_speaking_ratio

        assert _calc_speaking_ratio({}) is None


class TestGetBloomStart:
    def test_returns_first_entry(self):
        from src.app.domain.services.handlers.socratic import _get_bloom_start

        state = {"assessor_log": [{"bloom_level": "remember"}, {"bloom_level": "apply"}]}
        assert _get_bloom_start(state) == "remember"

    def test_empty_log(self):
        from src.app.domain.services.handlers.socratic import _get_bloom_start

        assert _get_bloom_start({"assessor_log": []}) is None
        assert _get_bloom_start({}) is None
