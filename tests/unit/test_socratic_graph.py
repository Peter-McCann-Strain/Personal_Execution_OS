"""Tests for Socratic tutorial LangGraph graph construction and nodes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.app.agents.socratic.state import (
    AgentResponse,
    AssessorAction,
    AssessorDecision,
    BloomLevel,
    ClarifierPrep,
    CognitiveLoad,
    ConnectorPrep,
    DevilsAdvocatePrep,
    EmotionalState,
    Proposition,
    QuestionType,
    TutorialPhase,
    TutorPrep,
    make_initial_state,
)


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


class TestGraphConstruction:
    """Test that graphs build correctly."""

    def test_preparation_graph_builds(self):
        from src.app.agents.socratic.graph import build_preparation_graph

        graph = build_preparation_graph()
        assert graph is not None

    def test_preparation_graph_has_all_nodes(self):
        from src.app.agents.socratic.graph import build_preparation_graph

        graph = build_preparation_graph()
        expected = {
            "extract_propositions",
            "tutor_prep_node",
            "da_prep_node",
            "clarifier_prep_node",
            "connector_prep_node",
            "merge_preparation",
        }
        assert expected.issubset(set(graph.nodes.keys()))

    def test_dialogue_graph_builds(self):
        from src.app.agents.socratic.graph import build_dialogue_graph

        graph = build_dialogue_graph()
        assert graph is not None

    def test_dialogue_graph_has_all_nodes(self):
        from src.app.agents.socratic.graph import TutorialGraphState, build_dialogue_graph

        graph = build_dialogue_graph()
        expected = {
            "opening_node",
            "user_turn_node",
            "assessor_gate_node",
            "tutor_turn_node",
            "da_turn_node",
            "clarifier_turn_node",
            "connector_turn_node",
            "no_intervention_node",
            "closing_node",
            "final_user_response_node",
        }
        assert expected.issubset(set(graph.nodes.keys()))
        assert "assessor_suggestion" in TutorialGraphState.model_fields

    def test_tutorial_graph_builds(self):
        from src.app.agents.socratic.graph import build_tutorial_graph

        graph = build_tutorial_graph()
        assert graph is not None

    async def test_dialogue_checkpoint_excludes_runtime_dependencies(self):
        """A non-serializable client belongs in runtime context, not durable state."""
        from src.app.agents.socratic.graph import (
            TutorialGraphState,
            TutorialRuntimeContext,
            build_dialogue_graph,
        )

        state = TutorialGraphState(
            session_id="checkpoint-regression",
            user_id="u1",
            topic="Caching",
            submitted_work="Caching reduces latency.",
            phase=TutorialPhase.READY,
        )
        response = AgentResponse(content="What trade-off does caching create?", agent="tutor")

        with patch(
            "src.app.agents.socratic.graph.tutor_opening",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = (
                await build_dialogue_graph()
                .compile(checkpointer=InMemorySaver())
                .ainvoke(
                    state,
                    config={"configurable": {"thread_id": "checkpoint-regression"}},
                    context=TutorialRuntimeContext(client=AsyncMock()),
                )
            )

        assert result["dialogue_history"][-1]["content"] == response.content
        assert result["__interrupt__"]
        assert "client" not in TutorialGraphState.model_fields


class TestPreparationNodes:
    """Test the preparation-phase nodes."""

    async def test_extract_propositions_node_fans_out(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Caching",
            submitted_work="Caching improves performance.",
            client=AsyncMock(),
        )

        propositions = [
            Proposition(index=0, text="Caching improves performance", centrality=0.8),
            Proposition(index=1, text="Invalidation is hard", centrality=0.7),
        ]

        with patch(
            "src.app.agents.socratic.graph.extract_propositions",
            new_callable=AsyncMock,
            return_value=propositions,
        ):
            from src.app.agents.socratic.graph import extract_propositions_node

            result = await extract_propositions_node(state)

        assert result.update["phase"] == TutorialPhase.PREPARING
        assert len(result.update["propositions"]) == 2
        assert result.update["claims_unresolved"] == result.update["propositions"]
        assert [send.node for send in result.goto] == [
            "tutor_prep_node",
            "da_prep_node",
            "clarifier_prep_node",
            "connector_prep_node",
        ]

    async def test_tutor_prep_node_returns_dump(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Caching",
            submitted_work="Caching improves performance.",
            client=AsyncMock(),
        )
        state["propositions"] = [{"index": 0, "text": "Claim"}]

        prep = TutorPrep(
            opening_question="What trade-off are you making?",
            key_areas=["trade-offs"],
            question_sequence=[{"question": "What is the downside?"}],
            work_summary="Caching summary",
        )

        with patch(
            "src.app.agents.socratic.graph.prepare_tutor",
            new_callable=AsyncMock,
            return_value=prep,
        ):
            from src.app.agents.socratic.graph import tutor_prep_node

            result = await tutor_prep_node(state)

        assert result["tutor_prep"]["opening_question"] == "What trade-off are you making?"

    async def test_da_prep_node_returns_dump(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Caching",
            submitted_work="Caching improves performance.",
            client=AsyncMock(),
        )

        prep = DevilsAdvocatePrep(
            counter_arguments=[{"counter": "Stale reads"}],
            steelman_positions=[],
            vulnerabilities=["Invalidation"],
        )

        with patch(
            "src.app.agents.socratic.graph.prepare_devils_advocate",
            new_callable=AsyncMock,
            return_value=prep,
        ):
            from src.app.agents.socratic.graph import da_prep_node

            result = await da_prep_node(state)

        assert result["devils_advocate_prep"]["vulnerabilities"] == ["Invalidation"]

    async def test_clarifier_prep_node_returns_dump(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Caching",
            submitted_work="Caching improves performance.",
            client=AsyncMock(),
        )

        prep = ClarifierPrep(
            ambiguous_terms=[{"term": "fast", "context": "benchmark", "why_ambiguous": "relative"}],
            vague_claims=[],
            undefined_concepts=["consistency"],
        )

        with patch(
            "src.app.agents.socratic.graph.prepare_clarifier",
            new_callable=AsyncMock,
            return_value=prep,
        ):
            from src.app.agents.socratic.graph import clarifier_prep_node

            result = await clarifier_prep_node(state)

        assert result["clarifier_prep"]["undefined_concepts"] == ["consistency"]

    async def test_connector_prep_node_without_db_session(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Caching",
            submitted_work="Caching improves performance.",
            client=AsyncMock(),
        )

        prep = ConnectorPrep(
            relevant_notes=[{"title": "Cache note", "summary": "Summary", "relevance": "high"}],
            prior_work_links=[],
            knowledge_gaps=["invalidations"],
        )

        with (
            patch(
                "src.app.agents.socratic.graph.prepare_connector",
                new_callable=AsyncMock,
                return_value=prep,
            ) as mock_prepare,
            patch(
                "src.app.agents.socratic.graph.retrieve_second_brain_context",
                new_callable=AsyncMock,
            ) as mock_retrieve,
        ):
            from src.app.agents.socratic.graph import connector_prep_node

            result = await connector_prep_node(state)

        assert result["connector_prep"]["knowledge_gaps"] == ["invalidations"]
        mock_retrieve.assert_not_awaited()
        assert mock_prepare.await_args.kwargs["second_brain_context"] == ""

    async def test_connector_prep_node_with_db_session_uses_retrieval(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Caching",
            submitted_work="Caching improves performance.",
            client=AsyncMock(),
            db_session=AsyncMock(),
            embeddings=AsyncMock(),
        )

        prep = ConnectorPrep(relevant_notes=[], prior_work_links=[], knowledge_gaps=[])

        with (
            patch(
                "src.app.agents.socratic.graph.retrieve_second_brain_context",
                new_callable=AsyncMock,
                return_value="## Relevant Notes from Second Brain",
            ) as mock_retrieve,
            patch(
                "src.app.agents.socratic.graph.prepare_connector",
                new_callable=AsyncMock,
                return_value=prep,
            ) as mock_prepare,
        ):
            from src.app.agents.socratic.graph import connector_prep_node

            await connector_prep_node(state)

        mock_retrieve.assert_awaited_once()
        assert mock_prepare.await_args.kwargs["second_brain_context"] == (
            "## Relevant Notes from Second Brain"
        )

    async def test_merge_preparation_node_sets_ready(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Caching",
            submitted_work="Caching improves performance.",
        )
        state["propositions"] = [{"index": 0, "text": "Claim"}]

        from src.app.agents.socratic.graph import merge_preparation_node

        result = await merge_preparation_node(state)

        assert result == {"phase": TutorialPhase.READY}


class TestOpeningNode:
    """Test the opening node generates the Feynman question."""

    async def test_opening_node_sets_dialogue_phase(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["tutor_prep"] = {
            "opening_question": "Explain this.",
            "work_summary": "Test work",
            "question_sequence": [],
        }
        state["propositions"] = [
            {"index": 0, "text": "Claim 1", "centrality": 0.8},
        ]

        mock_response = AgentResponse(
            content="Tell me in your own words...",
            agent="tutor",
            question_type=QuestionType.CLARIFICATION,
        )

        with patch(
            "src.app.agents.socratic.graph.tutor_opening",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from src.app.agents.socratic.graph import opening_node

            result = await opening_node(state)

        assert result["phase"] == TutorialPhase.DIALOGUE
        assert result["current_turn"] == 1
        assert result["current_speaker"] == "tutor"
        assert len(result["dialogue_history"]) == 1
        assert result["dialogue_history"][0]["role"] == "tutor"


class TestUserTurnNode:
    """Test the captured user-turn node."""

    async def test_user_turn_node_updates_ratio_and_trims_working_memory(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
        )
        state["current_turn"] = 2
        state["speaking_ratio"] = {"user_words": 4, "agent_words": 6}
        state["working_memory"] = [{"role": "user", "content": f"Turn {idx}"} for idx in range(6)]

        with patch("src.app.agents.socratic.graph.interrupt", return_value="I disagree strongly"):
            from src.app.agents.socratic.graph import user_turn_node

            result = await user_turn_node(state)

        assert result["current_speaker"] == "user"
        assert result["current_turn"] == 3
        assert result["speaking_ratio"]["user_words"] == 7
        assert len(result["working_memory"]) == 6
        assert result["working_memory"][-1]["content"] == "I disagree strongly"

    async def test_user_turn_node_keeps_short_working_memory_without_trimming(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
        )
        state["working_memory"] = [{"role": "assistant", "content": "Opening question"}]

        with patch("src.app.agents.socratic.graph.interrupt", return_value="Short answer"):
            from src.app.agents.socratic.graph import user_turn_node

            result = await user_turn_node(state)

        assert len(result["working_memory"]) == 2
        assert result["working_memory"][-1]["content"] == "Short answer"


class TestAssessorGateNode:
    """Test the assessor routing node."""

    async def test_routes_to_tutor(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["propositions"] = [{"index": 0, "text": "Claim", "centrality": 0.8}]
        state["working_memory"] = [
            {"role": "user", "content": "I think caching helps."},
        ]

        mock_decision = AssessorDecision(
            action=AssessorAction.TUTOR,
            reasoning="Push deeper.",
            bloom_level=BloomLevel.UNDERSTAND,
            cognitive_load=CognitiveLoad.LOW,
            emotional_state=EmotionalState.ENGAGED,
        )

        with patch(
            "src.app.agents.socratic.graph.assess_turn",
            new_callable=AsyncMock,
            return_value=mock_decision,
        ):
            from src.app.agents.socratic.graph import assessor_gate_node

            result = await assessor_gate_node(state)

        # Command object with goto and update
        assert result.goto == "tutor_turn_node"
        assert result.update["bloom_level"] == BloomLevel.UNDERSTAND
        assert result.update["no_intervention_count"] == 0

    async def test_routes_to_no_intervention(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["propositions"] = [{"index": 0, "text": "Claim", "centrality": 0.8}]

        mock_decision = AssessorDecision(
            action=AssessorAction.NO_INTERVENTION,
            reasoning="Student is thinking.",
        )

        with patch(
            "src.app.agents.socratic.graph.assess_turn",
            new_callable=AsyncMock,
            return_value=mock_decision,
        ):
            from src.app.agents.socratic.graph import assessor_gate_node

            result = await assessor_gate_node(state)

        assert result.goto == "no_intervention_node"
        assert result.update["no_intervention_count"] == 1

    async def test_routes_to_closing(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["propositions"] = [{"index": 0, "text": "Claim", "centrality": 0.8}]

        mock_decision = AssessorDecision(
            action=AssessorAction.CLOSING,
            reasoning="All propositions explored.",
        )

        with patch(
            "src.app.agents.socratic.graph.assess_turn",
            new_callable=AsyncMock,
            return_value=mock_decision,
        ):
            from src.app.agents.socratic.graph import assessor_gate_node

            result = await assessor_gate_node(state)

        assert result.goto == "closing_node"

    async def test_advances_proposition_when_flagged(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["propositions"] = [
            {"index": 0, "text": "Claim 0", "centrality": 0.8},
            {"index": 1, "text": "Claim 1", "centrality": 0.7},
        ]
        state["current_proposition_index"] = 0
        state["propositions_explored"] = []

        mock_decision = AssessorDecision(
            action=AssessorAction.TUTOR,
            reasoning="Move on.",
            should_advance_proposition=True,
        )

        with patch(
            "src.app.agents.socratic.graph.assess_turn",
            new_callable=AsyncMock,
            return_value=mock_decision,
        ):
            from src.app.agents.socratic.graph import assessor_gate_node

            result = await assessor_gate_node(state)

        assert result.update["current_proposition_index"] == 1
        assert 0 in result.update["propositions_explored"]

    async def test_escalates_after_too_many_silent_turns(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["current_turn"] = 5
        state["no_intervention_count"] = 3

        mock_decision = AssessorDecision(
            action=AssessorAction.NO_INTERVENTION,
            reasoning="Still thinking",
            question_suggestion=None,
        )

        with patch(
            "src.app.agents.socratic.graph.assess_turn",
            new_callable=AsyncMock,
            return_value=mock_decision,
        ):
            from src.app.agents.socratic.graph import assessor_gate_node

            result = await assessor_gate_node(state)

        assert result.goto == "tutor_turn_node"
        assert result.update["no_intervention_count"] == 0
        assert "re-engage" in result.update["assessor_suggestion"]


class TestAgentTurnNodes:
    """Test individual agent turn nodes update state correctly."""

    async def test_tutor_turn_node(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["working_memory"] = []
        state["speaking_ratio"] = {"user_words": 10, "agent_words": 5}

        mock_response = AgentResponse(
            content="Why do you say that?",
            agent="tutor",
            question_type=QuestionType.EVIDENCE,
            think="Testing evidence.",
        )

        with patch(
            "src.app.agents.socratic.graph.tutor_respond",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from src.app.agents.socratic.graph import tutor_turn_node

            result = await tutor_turn_node(state)

        assert result["current_speaker"] == "tutor"
        assert len(result["dialogue_history"]) == 1
        assert result["dialogue_history"][0]["content"] == "Why do you say that?"
        # Agent words should increase
        assert result["speaking_ratio"]["agent_words"] > 5
        # User words unchanged
        assert result["speaking_ratio"]["user_words"] == 10

    async def test_da_turn_node(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["working_memory"] = []
        state["speaking_ratio"] = {"user_words": 20, "agent_words": 10}

        mock_response = AgentResponse(
            content="But what about cache invalidation?",
            agent="devils_advocate",
        )

        with patch(
            "src.app.agents.socratic.graph.challenge",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from src.app.agents.socratic.graph import da_turn_node

            result = await da_turn_node(state)

        assert result["current_speaker"] == "devils_advocate"
        assert "cache invalidation" in result["dialogue_history"][0]["content"]

    async def test_tutor_turn_node_trims_working_memory(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["working_memory"] = [{"role": "user", "content": f"Turn {idx}"} for idx in range(6)]

        with patch(
            "src.app.agents.socratic.graph.tutor_respond",
            new_callable=AsyncMock,
            return_value=AgentResponse(content="One more question", agent="tutor"),
        ):
            from src.app.agents.socratic.graph import tutor_turn_node

            result = await tutor_turn_node(state)

        assert len(result["working_memory"]) == 6
        assert result["working_memory"][-1]["content"] == "One more question"

    async def test_da_turn_node_trims_working_memory(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["working_memory"] = [{"role": "user", "content": f"Turn {idx}"} for idx in range(6)]

        with patch(
            "src.app.agents.socratic.graph.challenge",
            new_callable=AsyncMock,
            return_value=AgentResponse(content="Counterpoint here", agent="devils_advocate"),
        ):
            from src.app.agents.socratic.graph import da_turn_node

            result = await da_turn_node(state)

        assert len(result["working_memory"]) == 6
        assert result["working_memory"][-1]["content"] == "Counterpoint here"

    async def test_clarifier_turn_node(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["working_memory"] = [{"role": "user", "content": f"Turn {idx}"} for idx in range(6)]

        with patch(
            "src.app.agents.socratic.graph.clarify",
            new_callable=AsyncMock,
            return_value=AgentResponse(
                content="What do you mean by fast?",
                agent="clarifier",
                question_type=QuestionType.CLARIFICATION,
            ),
        ):
            from src.app.agents.socratic.graph import clarifier_turn_node

            result = await clarifier_turn_node(state)

        assert result["current_speaker"] == "clarifier"
        assert result["dialogue_history"][0]["content"] == "What do you mean by fast?"
        assert len(result["working_memory"]) == 6

    async def test_clarifier_turn_node_keeps_short_working_memory(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["working_memory"] = [{"role": "user", "content": "Turn 0"}]

        with patch(
            "src.app.agents.socratic.graph.clarify",
            new_callable=AsyncMock,
            return_value=AgentResponse(
                content="Can you define fast more precisely?",
                agent="clarifier",
                question_type=QuestionType.CLARIFICATION,
            ),
        ):
            from src.app.agents.socratic.graph import clarifier_turn_node

            result = await clarifier_turn_node(state)

        assert len(result["working_memory"]) == 2
        assert result["working_memory"][-1]["content"] == "Can you define fast more precisely?"

    async def test_connector_turn_node(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["working_memory"] = [{"role": "user", "content": f"Turn {idx}"} for idx in range(6)]

        with patch(
            "src.app.agents.socratic.graph.connect",
            new_callable=AsyncMock,
            return_value=AgentResponse(
                content="This links back to your note on cache design.",
                agent="connector",
                question_type=QuestionType.PERSPECTIVES,
            ),
        ):
            from src.app.agents.socratic.graph import connector_turn_node

            result = await connector_turn_node(state)

        assert result["current_speaker"] == "connector"
        assert "links back to your note" in result["dialogue_history"][0]["content"]
        assert len(result["working_memory"]) == 6

    async def test_connector_turn_node_keeps_short_working_memory(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["working_memory"] = [{"role": "user", "content": "Turn 0"}]

        with patch(
            "src.app.agents.socratic.graph.connect",
            new_callable=AsyncMock,
            return_value=AgentResponse(
                content="This also connects to your retrieval notes.",
                agent="connector",
                question_type=QuestionType.PERSPECTIVES,
            ),
        ):
            from src.app.agents.socratic.graph import connector_turn_node

            result = await connector_turn_node(state)

        assert len(result["working_memory"]) == 2
        assert result["working_memory"][-1]["content"] == (
            "This also connects to your retrieval notes."
        )


class TestNoInterventionNode:
    """Test the silence node."""

    async def test_no_intervention_returns_empty(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
        )

        from src.app.agents.socratic.graph import no_intervention_node

        result = await no_intervention_node(state)
        assert result == {}


class TestClosingNode:
    """Test the closing synthesis node."""

    async def test_closing_sets_phase(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
            client=AsyncMock(),
        )
        state["working_memory"] = []

        mock_response = AgentResponse(
            content="What have you learned today?",
            agent="tutor",
            question_type=QuestionType.META,
        )

        with patch(
            "src.app.agents.socratic.graph.tutor_respond",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from src.app.agents.socratic.graph import closing_node

            result = await closing_node(state)

        assert result["phase"] == TutorialPhase.CLOSING
        assert result["current_speaker"] == "tutor"


class TestFinalUserResponseNode:
    """Test capture of the student's closing reflection."""

    async def test_final_user_response_node(self):
        state = make_initial_state(
            session_id="test",
            user_id="u1",
            topic="Test",
            submitted_work="Content",
        )

        with patch(
            "src.app.agents.socratic.graph.interrupt",
            return_value="I learned that evidence matters.",
        ):
            from src.app.agents.socratic.graph import final_user_response_node

            result = await final_user_response_node(state)

        assert result["phase"] == TutorialPhase.ANALYSING
        assert result["dialogue_history"][0]["content"] == "I learned that evidence matters."


class TestRouting:
    """Test routing functions."""

    def test_route_after_agent_turn_to_user(self):
        from src.app.agents.socratic.graph import _route_after_agent_turn

        state = {"phase": TutorialPhase.DIALOGUE}
        assert _route_after_agent_turn(state) == "user_turn_node"

    def test_route_after_agent_turn_to_final_on_closing(self):
        from src.app.agents.socratic.graph import _route_after_agent_turn

        state = {"phase": TutorialPhase.CLOSING}
        assert _route_after_agent_turn(state) == "final_user_response_node"

    def test_route_after_no_intervention(self):
        from src.app.agents.socratic.graph import _route_after_no_intervention

        state = {}
        assert _route_after_no_intervention(state) == "user_turn_node"

    def test_route_after_opening(self):
        from src.app.agents.socratic.graph import _route_after_opening

        assert _route_after_opening({}) == "user_turn_node"
