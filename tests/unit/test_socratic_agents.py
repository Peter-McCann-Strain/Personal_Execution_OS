"""Tests for Socratic tutorial agent implementations.

All LLM calls are mocked — no real API calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.socratic.state import (
    AgentResponse,
    AssessorAction,
    AssessorDecision,
    BloomLevel,
    CognitiveLoad,
    EmotionalState,
    QuestionType,
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
    return settings


@pytest.fixture(autouse=True)
def _patch_settings():
    with patch(
        "src.app.config.get_settings",
        return_value=_mock_settings(),
    ):
        yield


def _make_state(**overrides) -> dict:
    """Create a test state with sensible defaults."""
    state = make_initial_state(
        session_id="test-session",
        user_id="user-1",
        topic="Test topic",
        submitted_work="Test work content",
    )
    state["propositions"] = [
        {
            "index": 0,
            "text": "Caching improves performance",
            "source_location": "paragraph 1",
            "claim_type": "assertion",
            "centrality": 0.8,
        },
    ]
    state["tutor_prep"] = {
        "opening_question": "Explain caching to me.",
        "key_areas": ["performance", "trade-offs"],
        "question_sequence": [
            {"question_type": "assumptions", "target_proposition": "0", "question": "Why?"},
        ],
        "work_summary": "An essay about caching.",
    }
    state["devils_advocate_prep"] = {
        "counter_arguments": [
            {"proposition_index": 0, "counter": "Not always true", "strength": "moderate"},
        ],
        "steelman_positions": [],
        "vulnerabilities": ["Oversimplification"],
    }
    state["clarifier_prep"] = {
        "ambiguous_terms": [{"term": "performance", "context": "p1", "why_ambiguous": "vague"}],
        "vague_claims": [],
        "undefined_concepts": [],
    }
    state["connector_prep"] = {
        "relevant_notes": [],
        "prior_work_links": [],
        "knowledge_gaps": ["Distributed caching"],
    }
    state["working_memory"] = [
        {"role": "tutor", "content": "What is caching?"},
        {"role": "user", "content": "It stores data for quick access."},
    ]
    state.update(overrides)
    return state


class TestAssessor:
    def test_build_assessor_context_handles_empty_state(self):
        """The assessor context builder should handle missing prep and proposition data."""
        from src.app.agents.socratic.agents.assessor import _build_assessor_context

        context = _build_assessor_context(
            {
                "phase": "dialogue",
                "current_turn": 0,
                "working_memory": [],
                "propositions": [],
                "propositions_explored": [],
            },
        )

        assert "<current_proposition>" in context
        assert "<tutor_plan_hint>\nNo plan\n</tutor_plan_hint>" in context
        assert "<da_vulnerabilities>\nNone prepared\n</da_vulnerabilities>" in context
        assert "Speaking ratio: student 50% / agents 50%" in context

    async def test_assess_turn_returns_decision(self):
        mock_client = AsyncMock()
        state = _make_state()

        mock_decision = AssessorDecision(
            action=AssessorAction.TUTOR,
            reasoning="Student gave a surface-level answer.",
            bloom_level=BloomLevel.UNDERSTAND,
            cognitive_load=CognitiveLoad.LOW,
            emotional_state=EmotionalState.ENGAGED,
        )

        with patch(
            "src.app.agents.socratic.agents.assessor.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_decision,
        ) as mock_call:
            from src.app.agents.socratic.agents.assessor import assess_turn

            result = await assess_turn(state, mock_client)

        mock_call.assert_awaited_once()
        assert result.action == AssessorAction.TUTOR
        assert result.bloom_level == BloomLevel.UNDERSTAND

    async def test_assess_turn_no_intervention(self):
        mock_client = AsyncMock()
        state = _make_state()

        mock_decision = AssessorDecision(
            action=AssessorAction.NO_INTERVENTION,
            reasoning="Student is mid-thought.",
        )

        with patch(
            "src.app.agents.socratic.agents.assessor.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_decision,
        ):
            from src.app.agents.socratic.agents.assessor import assess_turn

            result = await assess_turn(state, mock_client)

        assert result.action == AssessorAction.NO_INTERVENTION

    async def test_assessor_uses_haiku_model(self):
        mock_client = AsyncMock()
        state = _make_state()

        with patch(
            "src.app.agents.socratic.agents.assessor.call_and_parse",
            new_callable=AsyncMock,
            return_value=AssessorDecision(
                action=AssessorAction.TUTOR,
                reasoning="test",
            ),
        ) as mock_call:
            from src.app.agents.socratic.agents.assessor import assess_turn

            await assess_turn(state, mock_client)

        call_kwargs = mock_call.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
        assert call_kwargs["inject_personality"] is False

    async def test_assess_turn_respects_explicit_model_and_token_overrides(self):
        mock_client = AsyncMock()
        state = _make_state()

        with patch(
            "src.app.agents.socratic.agents.assessor.call_and_parse",
            new_callable=AsyncMock,
            return_value=AssessorDecision(action=AssessorAction.TUTOR, reasoning="test"),
        ) as mock_call:
            from src.app.agents.socratic.agents.assessor import assess_turn

            await assess_turn(
                state,
                mock_client,
                model="custom-model",
                max_tokens=777,
            )

        assert mock_call.call_args.kwargs["model"] == "custom-model"
        assert mock_call.call_args.kwargs["max_tokens"] == 777


class TestTutor:
    def test_build_tutor_context_handles_missing_prep(self):
        """The tutor context builder should handle empty prep and missing propositions."""
        from src.app.agents.socratic.agents.tutor import _build_tutor_context

        context = _build_tutor_context(
            {
                "working_memory": [],
                "propositions": [],
                "tutor_prep": {},
            },
        )

        assert "<current_proposition>" in context
        assert "<your_questioning_plan>\nNone\n</your_questioning_plan>" in context
        assert "<assessor_hint>" not in context

    async def test_tutor_respond(self):
        mock_client = AsyncMock()
        state = _make_state()

        mock_response = AgentResponse(
            content="What do you mean by 'quick access'?",
            agent="tutor",
            question_type=QuestionType.CLARIFICATION,
            think="Student used vague language.",
        )

        with patch(
            "src.app.agents.socratic.agents.tutor.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from src.app.agents.socratic.agents.tutor import tutor_respond

            result = await tutor_respond(state, mock_client)

        assert result.agent == "tutor"
        assert result.content == "What do you mean by 'quick access'?"
        assert result.question_type == QuestionType.CLARIFICATION

    async def test_tutor_opening(self):
        mock_client = AsyncMock()
        state = _make_state()

        mock_response = AgentResponse(
            content="Explain caching to me as if I know nothing.",
            agent="tutor",
            question_type=QuestionType.CLARIFICATION,
        )

        with patch(
            "src.app.agents.socratic.agents.tutor.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from src.app.agents.socratic.agents.tutor import tutor_opening

            result = await tutor_opening(state, mock_client)

        assert "caching" in result.content.lower()

    async def test_tutor_uses_sonnet_model(self):
        mock_client = AsyncMock()
        state = _make_state()

        with patch(
            "src.app.agents.socratic.agents.tutor.call_and_parse",
            new_callable=AsyncMock,
            return_value=AgentResponse(content="?", agent="tutor"),
        ) as mock_call:
            from src.app.agents.socratic.agents.tutor import tutor_respond

            await tutor_respond(state, mock_client)

        assert mock_call.call_args.kwargs["model"] == "claude-sonnet-4-6"

    async def test_tutor_passes_assessor_suggestion(self):
        mock_client = AsyncMock()
        state = _make_state()

        with patch(
            "src.app.agents.socratic.agents.tutor.call_and_parse",
            new_callable=AsyncMock,
            return_value=AgentResponse(content="?", agent="tutor"),
        ) as mock_call:
            from src.app.agents.socratic.agents.tutor import tutor_respond

            await tutor_respond(
                state,
                mock_client,
                assessor_suggestion="Ask about trade-offs",
            )

        messages = mock_call.call_args.kwargs["messages"]
        assert "trade-offs" in messages[0]["content"]

    async def test_tutor_respects_explicit_model_and_token_overrides(self):
        mock_client = AsyncMock()
        state = _make_state()

        with patch(
            "src.app.agents.socratic.agents.tutor.call_and_parse",
            new_callable=AsyncMock,
            return_value=AgentResponse(content="?", agent="tutor"),
        ) as mock_call:
            from src.app.agents.socratic.agents.tutor import tutor_respond

            await tutor_respond(
                state,
                mock_client,
                model="custom-model",
                max_tokens=333,
            )

        assert mock_call.call_args.kwargs["model"] == "custom-model"
        assert mock_call.call_args.kwargs["max_tokens"] == 333
        assert mock_call.call_args.kwargs["inject_personality"] is False


class TestDevilsAdvocate:
    def test_build_da_context_handles_missing_prep(self):
        """The devil's advocate context builder should handle empty prep and missing propositions."""
        from src.app.agents.socratic.agents.devils_advocate import _build_da_context

        context = _build_da_context(
            {
                "working_memory": [],
                "propositions": [],
                "devils_advocate_prep": {},
            },
        )

        assert "<current_proposition>" in context
        assert "<your_counter_arguments>\nNone\n</your_counter_arguments>" in context
        assert "<your_steelman_positions>\nNone\n</your_steelman_positions>" in context

    async def test_challenge(self):
        mock_client = AsyncMock()
        state = _make_state()

        mock_response = AgentResponse(
            content="I see your point about caching, but what about cache invalidation?",
            agent="devils_advocate",
            question_type=QuestionType.PERSPECTIVES,
        )

        with patch(
            "src.app.agents.socratic.agents.devils_advocate.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from src.app.agents.socratic.agents.devils_advocate import challenge

            result = await challenge(state, mock_client)

        assert result.agent == "devils_advocate"

    async def test_da_uses_opus_model(self):
        mock_client = AsyncMock()
        state = _make_state()

        with patch(
            "src.app.agents.socratic.agents.devils_advocate.call_and_parse",
            new_callable=AsyncMock,
            return_value=AgentResponse(content="?", agent="devils_advocate"),
        ) as mock_call:
            from src.app.agents.socratic.agents.devils_advocate import challenge

            await challenge(state, mock_client)

        assert mock_call.call_args.kwargs["model"] == "claude-opus-4-6"

    async def test_da_respects_explicit_model_and_token_overrides(self):
        mock_client = AsyncMock()
        state = _make_state()

        with patch(
            "src.app.agents.socratic.agents.devils_advocate.call_and_parse",
            new_callable=AsyncMock,
            return_value=AgentResponse(content="?", agent="devils_advocate"),
        ) as mock_call:
            from src.app.agents.socratic.agents.devils_advocate import challenge

            await challenge(
                state,
                mock_client,
                model="custom-model",
                max_tokens=222,
            )

        assert mock_call.call_args.kwargs["model"] == "custom-model"
        assert mock_call.call_args.kwargs["max_tokens"] == 222


class TestClarifier:
    async def test_clarify(self):
        mock_client = AsyncMock()
        state = _make_state()

        mock_response = AgentResponse(
            content="When you say 'performance', what metric are you measuring?",
            agent="clarifier",
            question_type=QuestionType.CLARIFICATION,
        )

        with patch(
            "src.app.agents.socratic.agents.clarifier.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from src.app.agents.socratic.agents.clarifier import clarify

            result = await clarify(state, mock_client)

        assert result.agent == "clarifier"
        assert result.question_type == QuestionType.CLARIFICATION

    async def test_clarifier_uses_haiku_model(self):
        mock_client = AsyncMock()
        state = _make_state()

        with patch(
            "src.app.agents.socratic.agents.clarifier.call_and_parse",
            new_callable=AsyncMock,
            return_value=AgentResponse(content="?", agent="clarifier"),
        ) as mock_call:
            from src.app.agents.socratic.agents.clarifier import clarify

            await clarify(state, mock_client)

        assert mock_call.call_args.kwargs["model"] == "claude-haiku-4-5-20251001"


class TestConnector:
    async def test_connect(self):
        mock_client = AsyncMock()
        state = _make_state()

        mock_response = AgentResponse(
            content="This relates to your notes on distributed systems.",
            agent="connector",
            question_type=QuestionType.PERSPECTIVES,
        )

        with patch(
            "src.app.agents.socratic.agents.connector.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from src.app.agents.socratic.agents.connector import connect

            result = await connect(state, mock_client)

        assert result.agent == "connector"

    async def test_connector_uses_sonnet_model(self):
        mock_client = AsyncMock()
        state = _make_state()

        with patch(
            "src.app.agents.socratic.agents.connector.call_and_parse",
            new_callable=AsyncMock,
            return_value=AgentResponse(content="?", agent="connector"),
        ) as mock_call:
            from src.app.agents.socratic.agents.connector import connect

            await connect(state, mock_client)

        assert mock_call.call_args.kwargs["model"] == "claude-sonnet-4-6"
