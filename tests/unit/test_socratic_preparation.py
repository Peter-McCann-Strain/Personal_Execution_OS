"""Tests for Socratic tutorial preparation phase."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.socratic.state import (
    ClarifierPrep,
    ConnectorPrep,
    DevilsAdvocatePrep,
    Proposition,
    TutorPrep,
)


def _mock_settings():
    settings = MagicMock()
    settings.socratic_preparation_model = "claude-sonnet-4-6"
    settings.socratic_preparation_max_tokens = 4096
    settings.socratic_tutor_model = "claude-sonnet-4-6"
    settings.socratic_devils_advocate_model = "claude-opus-4-6"
    settings.socratic_clarifier_model = "claude-haiku-4-5-20251001"
    settings.socratic_connector_model = "claude-sonnet-4-6"
    settings.socratic_max_propositions = 20
    return settings


@pytest.fixture(autouse=True)
def _patch_settings():
    with patch(
        "src.app.config.get_settings",
        return_value=_mock_settings(),
    ):
        yield


def _make_llm_response(text: str):
    """Create a mock Anthropic API response."""
    content_block = MagicMock()
    content_block.text = text
    content_block.type = "text"
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 200
    response = MagicMock()
    response.content = [content_block]
    response.usage = usage
    return response


class TestExtractPropositions:
    async def test_extracts_propositions(self):
        mock_client = AsyncMock()
        response_text = json.dumps(
            {
                "propositions": [
                    {
                        "index": 0,
                        "text": "Caching improves latency",
                        "source_location": "paragraph 1",
                        "claim_type": "assertion",
                        "centrality": 0.9,
                    },
                    {
                        "index": 1,
                        "text": "Redis is the best cache",
                        "source_location": "paragraph 3",
                        "claim_type": "assumption",
                        "centrality": 0.6,
                    },
                ],
            }
        )
        mock_client.messages.create = AsyncMock(
            return_value=_make_llm_response(response_text),
        )

        with patch(
            "src.app.agents.socratic.preparation.call_llm",
            new_callable=AsyncMock,
            return_value=_make_llm_response(response_text),
        ):
            from src.app.agents.socratic.preparation import extract_propositions

            result = await extract_propositions(
                submitted_work="My essay about caching...",
                work_type="essay",
                client=mock_client,
            )

        assert len(result) == 2
        assert isinstance(result[0], Proposition)
        assert result[0].text == "Caching improves latency"
        assert result[0].centrality == 0.9
        assert result[1].claim_type == "assumption"

    async def test_limits_to_max_propositions(self):
        mock_client = AsyncMock()
        # Return more than max_propositions
        props = [{"index": i, "text": f"Claim {i}", "centrality": 0.5} for i in range(25)]
        response_text = json.dumps({"propositions": props})

        with patch(
            "src.app.agents.socratic.preparation.call_llm",
            new_callable=AsyncMock,
            return_value=_make_llm_response(response_text),
        ):
            from src.app.agents.socratic.preparation import extract_propositions

            result = await extract_propositions(
                submitted_work="Content",
                work_type="essay",
                client=mock_client,
            )

        assert len(result) <= 20  # Max from settings


class TestPrepareTutor:
    async def test_returns_tutor_prep(self):
        mock_client = AsyncMock()
        mock_prep = TutorPrep(
            opening_question="Explain this to me.",
            key_areas=["performance"],
            question_sequence=[],
            work_summary="An essay.",
        )

        with patch(
            "src.app.agents.socratic.preparation.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_prep,
        ):
            from src.app.agents.socratic.preparation import prepare_tutor

            result = await prepare_tutor(
                propositions=[{"index": 0, "text": "Claim"}],
                submitted_work="Content",
                client=mock_client,
            )

        assert isinstance(result, TutorPrep)
        assert result.opening_question == "Explain this to me."


class TestPrepareDevilsAdvocate:
    async def test_returns_da_prep(self):
        mock_client = AsyncMock()
        mock_prep = DevilsAdvocatePrep(
            counter_arguments=[
                {"proposition_index": 0, "counter": "Not always", "strength": "moderate"},
            ],
            vulnerabilities=["Oversimplification"],
        )

        with patch(
            "src.app.agents.socratic.preparation.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_prep,
        ):
            from src.app.agents.socratic.preparation import prepare_devils_advocate

            result = await prepare_devils_advocate(
                propositions=[{"index": 0, "text": "Claim"}],
                submitted_work="Content",
                client=mock_client,
            )

        assert isinstance(result, DevilsAdvocatePrep)
        assert len(result.counter_arguments) == 1


class TestPrepareClarifier:
    async def test_returns_clarifier_prep(self):
        mock_client = AsyncMock()
        mock_prep = ClarifierPrep(
            ambiguous_terms=[
                {"term": "fast", "context": "p1", "why_ambiguous": "relative"},
            ],
        )

        with patch(
            "src.app.agents.socratic.preparation.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_prep,
        ):
            from src.app.agents.socratic.preparation import prepare_clarifier

            result = await prepare_clarifier(
                propositions=[{"index": 0, "text": "Claim"}],
                submitted_work="Content",
                client=mock_client,
            )

        assert isinstance(result, ClarifierPrep)
        assert len(result.ambiguous_terms) == 1


class TestPrepareConnector:
    async def test_returns_connector_prep(self):
        mock_client = AsyncMock()
        mock_prep = ConnectorPrep(
            knowledge_gaps=["Distributed caching"],
        )

        with patch(
            "src.app.agents.socratic.preparation.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_prep,
        ):
            from src.app.agents.socratic.preparation import prepare_connector

            result = await prepare_connector(
                propositions=[{"index": 0, "text": "Claim"}],
                submitted_work="Content",
                client=mock_client,
                second_brain_context="Prior notes about caching.",
            )

        assert isinstance(result, ConnectorPrep)
        assert "Distributed caching" in result.knowledge_gaps

    async def test_defaults_to_no_context(self):
        mock_client = AsyncMock()
        mock_prep = ConnectorPrep()

        with patch(
            "src.app.agents.socratic.preparation.call_and_parse",
            new_callable=AsyncMock,
            return_value=mock_prep,
        ) as mock_call:
            from src.app.agents.socratic.preparation import prepare_connector

            await prepare_connector(
                propositions=[],
                submitted_work="Content",
                client=mock_client,
            )

        # Verify the prompt includes "No prior context"
        messages = mock_call.call_args.kwargs["messages"]
        assert "No prior context available" in messages[0]["content"]
