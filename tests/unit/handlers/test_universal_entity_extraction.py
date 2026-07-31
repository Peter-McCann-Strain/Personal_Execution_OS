"""Tests for universal entity extraction across all specialist handlers.

Verifies that entity extraction is called from all handlers that produce
text content, ensuring the knowledge graph receives entities from every
specialist — not just diary.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.domain.models import ChatResponse, Intent, IntentType, MessageInput, Specialist


def _make_message(content: str = "test message") -> MessageInput:
    return MessageInput(content=content, source="test", user_id="user-1")


def _make_intent(specialist: Specialist = Specialist.DIARY) -> Intent:
    return Intent(
        intent_type=IntentType.CAPTURE,
        confidence=0.9,
        specialist=specialist,
        reasoning="test",
    )


def _make_episode_mock() -> MagicMock:
    episode = MagicMock()
    episode.id = uuid.uuid4()
    return episode


# ---------------------------------------------------------------------------
# 1. Research handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_research_handler_calls_entity_extraction():
    """handle_research enqueues entity extraction after storing the research episode."""
    from src.app.agents.specialists.research import ResearchReport

    report = ResearchReport(
        title="Test Research",
        search_queries=["test query"],
        findings=[],
        synthesis="Some synthesis about Python frameworks.",
        decision_framework=None,
    )
    episode = _make_episode_mock()

    with (
        patch(
            "src.app.domain.services.handlers.research.get_settings",
            return_value=MagicMock(
                tavily_configured=True, tavily_api_key=MagicMock(get_secret_value=lambda: "key")
            ),
        ),
        patch(
            "src.app.domain.services.handlers.research.TavilySearch",
            return_value=MagicMock(close=AsyncMock()),
        ),
        patch(
            "src.app.domain.services.handlers.research.run_research",
            new_callable=AsyncMock,
            return_value=report,
        ),
        patch(
            "src.app.domain.services.handlers.research.create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch(
            "src.app.domain.services.handlers.research.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ) as mock_enqueue,
    ):
        from src.app.domain.services.handlers.research import handle_research

        mock_session = AsyncMock()
        result = await handle_research(
            _make_message("research Python frameworks"),
            AsyncMock(),
            mock_session,
            _make_intent(Specialist.RESEARCH),
        )

    assert isinstance(result, ChatResponse)
    assert result.agent == "research"
    mock_enqueue.assert_awaited_once()
    call_kwargs = mock_enqueue.call_args
    assert call_kwargs.kwargs["episode_id"] == str(episode.id)
    assert "Test Research" in call_kwargs.kwargs["text_content"]


# ---------------------------------------------------------------------------
# 2. Review handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_handler_calls_entity_extraction():
    """handle_review enqueues entity extraction after generating the review."""
    from src.app.agents.specialists.review import (
        PatternNoticed,
        Recommendation,
        WeeklyReview,
    )

    review = WeeklyReview(
        period="2026-03-11 to 2026-03-18",
        key_insight="You've been very productive this week.",
        mood_summary="Generally positive",
        average_mood=7.5,
        accomplishments=["Completed project plan"],
        patterns_noticed=[PatternNoticed(pattern="High energy mornings")],
        open_commitments=[],
        recommendations=[Recommendation(action="Continue morning routine")],
    )

    with (
        patch(
            "src.app.domain.services.handlers.review._aggregate_week_data",
            new_callable=AsyncMock,
            return_value="week data",
        ),
        patch(
            "src.app.domain.services.handlers.review.generate_weekly_review",
            new_callable=AsyncMock,
            return_value=review,
        ),
        patch(
            "src.app.domain.services.handlers.review._get_spaced_repetition_items",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.review.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ) as mock_enqueue,
    ):
        from src.app.domain.services.handlers.review import handle_review

        result = await handle_review(
            _make_message("weekly review"),
            AsyncMock(),
            AsyncMock(),
            _make_intent(Specialist.REVIEW),
        )

    assert isinstance(result, ChatResponse)
    assert result.agent == "review"
    mock_enqueue.assert_awaited_once()
    call_kwargs = mock_enqueue.call_args
    assert "episode_id" in call_kwargs.kwargs
    assert "Weekly Review" in call_kwargs.kwargs["text_content"]


# ---------------------------------------------------------------------------
# 3. Project handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_handler_calls_entity_extraction():
    """handle_project enqueues entity extraction after project breakdown."""
    from src.app.agents.specialists.project import (
        MilestoneBreakdown,
        ProjectBreakdownResult,
        TaskBreakdown,
    )

    breakdown = ProjectBreakdownResult(
        milestones=[
            MilestoneBreakdown(
                title="Phase 1: Setup",
                success_criteria=["CI pipeline running"],
                tasks=[
                    TaskBreakdown(
                        title="Configure CI",
                        description="Set up GitHub Actions",
                        estimate_hours=2.0,
                        complexity="low",
                        depends_on=[],
                        context_tags=["devops"],
                    )
                ],
            )
        ]
    )
    episode = _make_episode_mock()

    with (
        patch(
            "src.app.domain.services.handlers.project.ai_breakdown_project",
            new_callable=AsyncMock,
            return_value=breakdown,
        ),
        patch(
            "src.app.domain.services.handlers.project.create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch(
            "src.app.domain.services.handlers.project.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ) as mock_enqueue,
    ):
        from src.app.domain.services.handlers.project import handle_project

        mock_session = AsyncMock()
        result = await handle_project(
            _make_message("break down the CI/CD project"),
            AsyncMock(),
            mock_session,
            _make_intent(Specialist.PROJECT),
        )

    assert isinstance(result, ChatResponse)
    assert result.agent == "project"
    mock_enqueue.assert_awaited_once()
    call_kwargs = mock_enqueue.call_args
    assert call_kwargs.kwargs["episode_id"] == str(episode.id)
    assert "Phase 1" in call_kwargs.kwargs["text_content"]


# ---------------------------------------------------------------------------
# 4. Communications handler (triage path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_communications_triage_calls_entity_extraction():
    """handle_communications (triage) enqueues entity extraction after classification."""
    from src.app.agents.specialists.communications import EmailClassification

    classification = EmailClassification(
        classification="ACTION_REQUIRED",
        sender="alice@example.com",
        subject_summary="Q1 Budget Review",
        urgency_reason="Deadline approaching",
        suggested_action="Review and respond",
    )

    with (
        patch(
            "src.app.domain.services.handlers.communications.triage_email",
            new_callable=AsyncMock,
            return_value=classification,
        ),
        patch(
            "src.app.domain.services.handlers.communications.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ) as mock_enqueue,
    ):
        from src.app.domain.services.handlers.communications import handle_communications

        result = await handle_communications(
            _make_message("classify this email from alice about the budget"),
            AsyncMock(),
            AsyncMock(),
            _make_intent(Specialist.COMMUNICATIONS),
        )

    assert isinstance(result, ChatResponse)
    assert result.agent == "communications"
    mock_enqueue.assert_awaited_once()
    call_kwargs = mock_enqueue.call_args
    assert "alice@example.com" in call_kwargs.kwargs["text_content"]
    assert "Q1 Budget Review" in call_kwargs.kwargs["text_content"]


# ---------------------------------------------------------------------------
# 5. Communications handler (draft path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_communications_draft_calls_entity_extraction():
    """handle_communications (draft) enqueues entity extraction after drafting."""
    from src.app.agents.specialists.communications import EmailDraft

    draft = EmailDraft(
        subject="Re: Q1 Budget Review",
        body="Hi Alice, thanks for sharing the budget...",
        tone="professional",
    )
    episode = _make_episode_mock()

    with (
        patch(
            "src.app.domain.services.handlers.communications.draft_reply",
            new_callable=AsyncMock,
            return_value=draft,
        ),
        patch(
            "src.app.domain.services.handlers.communications.create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch(
            "src.app.domain.services.handlers.communications.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ) as mock_enqueue,
    ):
        from src.app.domain.services.handlers.communications import handle_communications

        mock_session = AsyncMock()
        result = await handle_communications(
            _make_message("draft a reply to alice about the budget"),
            AsyncMock(),
            mock_session,
            _make_intent(Specialist.COMMUNICATIONS),
        )

    assert isinstance(result, ChatResponse)
    assert result.agent == "communications"
    mock_enqueue.assert_awaited_once()
    call_kwargs = mock_enqueue.call_args
    assert call_kwargs.kwargs["episode_id"] == str(episode.id)
    assert "Alice" in call_kwargs.kwargs["text_content"]


# ---------------------------------------------------------------------------
# 6. Memory handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_handler_calls_entity_extraction():
    """handle_memory enqueues entity extraction after synthesizing an answer."""
    from src.app.agents.specialists.memory import MemoryAnswer, MemorySearchResult

    answer = MemoryAnswer(
        answer="You mentioned meeting Bob at the conference last Tuesday.",
        confidence=0.85,
        sources=[
            MemorySearchResult(
                content="Met Bob at PyCon",
                relevance_score=0.9,
                source_type="episode",
                source_id="ep-1",
            )
        ],
        follow_up_suggestions=["When was the conference?"],
    )

    chunks = [
        {
            "content": "Met Bob at PyCon",
            "score": 0.9,
            "source_type": "episode",
            "source_id": str(uuid.uuid4()),
            "search_method": "unified",
        }
    ]

    with (
        patch(
            "src.app.domain.services.handlers.memory._retrieve_context",
            new_callable=AsyncMock,
            return_value=chunks,
        ),
        patch(
            "src.app.domain.services.handlers.memory._retrieve_interaction_context",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory._build_session_context_chunks",
            return_value=[],
        ),
        patch(
            "src.app.domain.services.handlers.memory.gate_by_relevance",
            return_value=(chunks, 0),
        ),
        patch(
            "src.app.domain.services.handlers.memory.answer_from_memory",
            new_callable=AsyncMock,
            return_value=answer,
        ),
        patch(
            "src.app.domain.services.handlers.memory.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ) as mock_enqueue,
        patch(
            "src.app.domain.services.handlers.memory.record_episode_access",
            new_callable=AsyncMock,
        ),
        patch(
            "src.app.domain.services.handlers.memory.record_note_access",
            new_callable=AsyncMock,
        ),
    ):
        from src.app.domain.services.handlers.memory import handle_memory

        result = await handle_memory(
            _make_message("when did I meet Bob?"),
            AsyncMock(),
            AsyncMock(),
            _make_intent(Specialist.MEMORY),
        )

    assert isinstance(result, ChatResponse)
    assert result.agent == "memory"
    mock_enqueue.assert_awaited_once()
    call_kwargs = mock_enqueue.call_args
    assert "Bob" in call_kwargs.kwargs["text_content"]


# ---------------------------------------------------------------------------
# 7. Notification handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notification_handler_calls_entity_extraction():
    """handle_notification enqueues entity extraction after processing."""
    with (
        patch(
            "src.app.domain.services.handlers.notification._get_or_create_fatigue_manager",
            return_value=MagicMock(
                set_focus_mode=MagicMock(),
                focus_mode=False,
                pending_count=0,
                dnd_start=MagicMock(strftime=lambda _fmt: "22:00"),
                dnd_end=MagicMock(strftime=lambda _fmt: "07:00"),
            ),
        ),
        patch(
            "src.app.domain.services.handlers.notification.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ) as mock_enqueue,
    ):
        from src.app.domain.services.handlers.notification import handle_notification

        result = await handle_notification(
            _make_message("notification status"),
            AsyncMock(),
            AsyncMock(),
            _make_intent(Specialist.NOTIFICATION),
        )

    assert isinstance(result, ChatResponse)
    assert result.agent == "notification"
    mock_enqueue.assert_awaited_once()
    call_kwargs = mock_enqueue.call_args
    assert "episode_id" in call_kwargs.kwargs
    assert call_kwargs.kwargs["text_content"]  # non-empty


# ---------------------------------------------------------------------------
# 8. Tools handler (plan-only path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_handler_calls_entity_extraction():
    """handle_tools enqueues entity extraction after MCP execution."""
    manager = MagicMock()
    manager.connected = True
    response = ChatResponse(
        content="I checked your calendar and nothing is booked tomorrow.",
        agent="tools",
        metadata={"mcp_execution": True},
    )

    with (
        patch(
            "src.app.domain.services.handlers.tools.get_mcp_client_manager",
            return_value=manager,
        ),
        patch(
            "src.app.domain.services.handlers.tools._handle_tools_with_mcp",
            new_callable=AsyncMock,
            return_value=response,
        ),
        patch(
            "src.app.domain.services.handlers.tools.enqueue_entity_extraction",
            new_callable=AsyncMock,
        ) as mock_enqueue,
    ):
        from src.app.domain.services.handlers.tools import handle_tools

        result = await handle_tools(
            _make_message("check my calendar for tomorrow"),
            AsyncMock(),
            AsyncMock(),
            _make_intent(Specialist.TOOLS),
        )

    assert isinstance(result, ChatResponse)
    assert result.agent == "tools"
    mock_enqueue.assert_awaited_once()
    call_kwargs = mock_enqueue.call_args
    assert "episode_id" in call_kwargs.kwargs
    assert call_kwargs.kwargs["text_content"]  # non-empty


# ---------------------------------------------------------------------------
# 9. Entity extraction failure does not break handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_extraction_failure_does_not_break_research():
    """If entity extraction fails in research handler, the response is still returned."""
    from src.app.agents.specialists.research import ResearchReport

    report = ResearchReport(
        title="Test Research",
        search_queries=["test"],
        findings=[],
        synthesis="Some findings.",
        decision_framework=None,
    )
    episode = _make_episode_mock()

    with (
        patch(
            "src.app.domain.services.handlers.research.get_settings",
            return_value=MagicMock(
                tavily_configured=True, tavily_api_key=MagicMock(get_secret_value=lambda: "key")
            ),
        ),
        patch(
            "src.app.domain.services.handlers.research.TavilySearch",
            return_value=MagicMock(close=AsyncMock()),
        ),
        patch(
            "src.app.domain.services.handlers.research.run_research",
            new_callable=AsyncMock,
            return_value=report,
        ),
        patch(
            "src.app.domain.services.handlers.research.create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch(
            "src.app.domain.services.handlers.research.enqueue_entity_extraction",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Redis down"),
        ),
        patch("src.app.domain.services.handlers.research.logger.warning"),
    ):
        from src.app.domain.services.handlers.research import handle_research

        result = await handle_research(
            _make_message("research something"),
            AsyncMock(),
            AsyncMock(),
            _make_intent(Specialist.RESEARCH),
        )

    # The response should still be returned despite entity extraction failure
    assert isinstance(result, ChatResponse)
    assert result.agent == "research"
    assert "Test Research" in result.content


@pytest.mark.asyncio
async def test_entity_extraction_failure_does_not_break_project():
    """If entity extraction fails in project handler, the response is still returned."""
    from src.app.agents.specialists.project import (
        MilestoneBreakdown,
        ProjectBreakdownResult,
        TaskBreakdown,
    )

    breakdown = ProjectBreakdownResult(
        milestones=[
            MilestoneBreakdown(
                title="Milestone 1",
                success_criteria=[],
                tasks=[
                    TaskBreakdown(
                        title="Task A",
                        description="Do something",
                        estimate_hours=1.0,
                        complexity="low",
                        depends_on=[],
                        context_tags=[],
                    )
                ],
            )
        ]
    )
    episode = _make_episode_mock()

    with (
        patch(
            "src.app.domain.services.handlers.project.ai_breakdown_project",
            new_callable=AsyncMock,
            return_value=breakdown,
        ),
        patch(
            "src.app.domain.services.handlers.project.create_episode",
            new_callable=AsyncMock,
            return_value=episode,
        ),
        patch(
            "src.app.domain.services.handlers.project.enqueue_entity_extraction",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ARQ failed"),
        ),
    ):
        from src.app.domain.services.handlers.project import handle_project

        result = await handle_project(
            _make_message("break down the project"),
            AsyncMock(),
            AsyncMock(),
            _make_intent(Specialist.PROJECT),
        )

    assert isinstance(result, ChatResponse)
    assert result.agent == "project"
    assert "project plan" in result.content.lower()
