"""Tests for tutorial API routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.api.routes.tutorials import (
    TutorialDetailDTO,
    TutorialStartResponse,
    TutorialSummaryDTO,
    TutorialTurnResponse,
    _to_detail,
    _to_summary,
)
from src.app.domain.models import ChatResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tutorial_mock(**overrides) -> MagicMock:
    """Create a mock TutorialSession ORM object."""
    t = MagicMock()
    t.id = overrides.get("id", uuid.uuid4())
    t.topic = overrides.get("topic", "Caching")
    t.work_type = overrides.get("work_type", "essay")
    t.phase = overrides.get("phase", "complete")
    t.submitted_work = overrides.get("submitted_work", "My essay...")
    t.turn_count = overrides.get("turn_count", 8)
    t.bloom_start = overrides.get("bloom_start", "understand")
    t.bloom_end = overrides.get("bloom_end", "analyse")
    t.speaking_ratio_student_pct = overrides.get("speaking_ratio_student_pct", 72.0)
    t.knowledge_gaps_found = overrides.get("knowledge_gaps_found", 3)
    t.knowledge_gaps_addressed = overrides.get("knowledge_gaps_addressed", 2)
    t.created_at = overrides.get("created_at", datetime.now(UTC))
    t.completed_at = overrides.get("completed_at", datetime.now(UTC))
    t.propositions = overrides.get("propositions", [{"index": 0, "text": "Claim"}])
    t.transcript = overrides.get(
        "transcript",
        [{"role": "tutor", "content": "Question?"}],
    )
    t.analysis = overrides.get("analysis", {"summary": "Good."})
    return t


# ---------------------------------------------------------------------------
# DTO conversion
# ---------------------------------------------------------------------------


class TestToSummary:
    def test_basic_conversion(self):
        t = _make_tutorial_mock()
        dto = _to_summary(t)
        assert isinstance(dto, TutorialSummaryDTO)
        assert dto.id == str(t.id)
        assert dto.topic == "Caching"
        assert dto.turn_count == 8
        assert dto.bloom_start == "understand"
        assert dto.bloom_end == "analyse"

    def test_null_fields(self):
        t = _make_tutorial_mock(
            turn_count=None,
            bloom_start=None,
            bloom_end=None,
            completed_at=None,
            speaking_ratio_student_pct=None,
            knowledge_gaps_found=None,
            knowledge_gaps_addressed=None,
        )
        dto = _to_summary(t)
        assert dto.turn_count is None
        assert dto.completed_at is None


class TestToDetail:
    def test_includes_transcript_and_analysis(self):
        t = _make_tutorial_mock()
        dto = _to_detail(t)
        assert isinstance(dto, TutorialDetailDTO)
        assert dto.submitted_work == "My essay..."
        assert dto.transcript == [{"role": "tutor", "content": "Question?"}]
        assert dto.analysis == {"summary": "Good."}
        assert dto.propositions == [{"index": 0, "text": "Claim"}]


# ---------------------------------------------------------------------------
# DTO schemas
# ---------------------------------------------------------------------------


class TestDTOSchemas:
    def test_start_response_schema(self):
        resp = TutorialStartResponse(
            tutorial_id="abc",
            content="Tell me about caching.",
            phase="dialogue",
            speaker="tutor",
        )
        assert resp.tutorial_id == "abc"
        assert resp.phase == "dialogue"

    def test_turn_response_schema(self):
        resp = TutorialTurnResponse(
            tutorial_id="abc",
            content="Why do you think so?",
            phase="dialogue",
            speaker="tutor",
            turn=3,
            bloom_level="understand",
        )
        assert resp.turn == 3
        assert resp.bloom_level == "understand"

    def test_turn_response_with_analysis(self):
        resp = TutorialTurnResponse(
            tutorial_id="abc",
            content="Tutorial complete.",
            phase="complete",
            speaker="tutor",
            analysis={"summary": "Good session."},
        )
        assert resp.analysis["summary"] == "Good session."


# ---------------------------------------------------------------------------
# Endpoint logic (unit tests via mock patching)
# ---------------------------------------------------------------------------


class TestListTutorialsEndpoint:
    async def test_returns_paginated(self):
        tutorials = [_make_tutorial_mock(), _make_tutorial_mock(topic="Design")]

        with (
            patch(
                "src.app.api.routes.tutorials.get_past_tutorials",
                new_callable=AsyncMock,
                return_value=tutorials,
            ),
        ):
            from src.app.api.routes.tutorials import list_tutorials

            result = await list_tutorials(db=AsyncMock(), limit=10, offset=0)

        assert result.total == 2
        assert len(result.items) == 2
        assert result.items[0].topic == "Caching"
        assert result.items[1].topic == "Design"


class TestGetTutorialEndpoint:
    async def test_returns_detail(self):
        tutorial = _make_tutorial_mock()

        with patch(
            "src.app.api.routes.tutorials.get_tutorial_session",
            new_callable=AsyncMock,
            return_value=tutorial,
        ):
            from src.app.api.routes.tutorials import get_tutorial

            result = await get_tutorial(tutorial.id, db=AsyncMock())

        assert isinstance(result, TutorialDetailDTO)
        assert result.topic == "Caching"

    async def test_not_found_raises(self):
        from src.app.core.exceptions import NotFoundError

        with (
            patch(
                "src.app.api.routes.tutorials.get_tutorial_session",
                new_callable=AsyncMock,
                return_value=None,
            ),
            pytest.raises(NotFoundError),
        ):
            from src.app.api.routes.tutorials import get_tutorial

            await get_tutorial(uuid.uuid4(), db=AsyncMock())


class TestStartTutorialEndpoint:
    async def test_returns_start_response(self):
        mock_response = ChatResponse(
            content="Tell me about caching.",
            agent="socratic",
            metadata={"phase": "dialogue", "speaker": "tutor"},
        )

        with patch(
            "src.app.api.routes.tutorials.start_tutorial",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from src.app.api.routes.tutorials import start_tutorial_endpoint

            tid = uuid.uuid4()
            result = await start_tutorial_endpoint(
                tid,
                db=AsyncMock(),
                client=AsyncMock(),
            )

        assert isinstance(result, TutorialStartResponse)
        assert result.content == "Tell me about caching."
        assert result.phase == "dialogue"


class TestTutorialTurnEndpoint:
    async def test_returns_turn_response(self):
        mock_response = ChatResponse(
            content="What evidence supports that?",
            agent="socratic",
            metadata={"phase": "dialogue", "speaker": "tutor", "turn": 3},
        )

        with patch(
            "src.app.api.routes.tutorials.process_tutorial_turn",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from src.app.api.routes.tutorials import (
                TutorialTurnRequest,
                tutorial_turn_endpoint,
            )

            tid = uuid.uuid4()
            body = TutorialTurnRequest(message="Caching stores data.")
            result = await tutorial_turn_endpoint(
                tid,
                body,
                db=AsyncMock(),
                client=AsyncMock(),
            )

        assert isinstance(result, TutorialTurnResponse)
        assert result.turn == 3


class TestEndTutorialEndpoint:
    async def test_returns_analysis(self):
        mock_response = ChatResponse(
            content="Tutorial ended.\n\n## Analysis",
            agent="socratic",
            metadata={
                "phase": "complete",
                "analysis": {"summary": "Good session."},
            },
        )

        with patch(
            "src.app.api.routes.tutorials.end_tutorial",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from src.app.api.routes.tutorials import end_tutorial_endpoint

            tid = uuid.uuid4()
            result = await end_tutorial_endpoint(
                tid,
                db=AsyncMock(),
                client=AsyncMock(),
            )

        assert isinstance(result, TutorialTurnResponse)
        assert result.phase == "complete"
        assert result.analysis["summary"] == "Good session."
