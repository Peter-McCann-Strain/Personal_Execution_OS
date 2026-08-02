"""Socratic tutorial handler — entry points for the tutorial system.

Three entry points:
1. handle_socratic: Submit work for tutorial (kicks off async preparation)
2. start_tutorial: Begin a prepared tutorial (returns opening question)
3. process_tutorial_turn: Process a user message during active tutorial

The normal chat routing dispatches to handle_socratic for work submission.
Active tutorial turns bypass normal routing entirely.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.socratic.analysis import analyse_tutorial, format_analysis_report
from src.app.agents.socratic.graph import (
    TutorialGraphState,
    TutorialRuntimeContext,
    build_dialogue_graph,
    build_preparation_graph,
)
from src.app.agents.socratic.state import (
    TutorialPhase,
    WorkType,
    make_initial_state,
)
from src.app.domain.models import ChatResponse, Intent, MessageInput
from src.app.persistence.repositories.tutorials import (
    create_tutorial_session,
    get_active_tutorial,
    get_tutorial_session,
    store_preparation,
    store_tutorial_results,
    update_tutorial_phase,
)

logger = structlog.get_logger()

# In-memory checkpoint saver for tutorial graph state.
# Will be replaced with AsyncPostgresSaver in production.
_checkpointer = InMemorySaver()


def _stored_propositions(value: object) -> list[dict[str, Any]]:
    """Normalize persisted JSON into the list-of-objects required by TutorialState."""
    if not isinstance(value, list):
        return []

    propositions: list[dict[str, Any]] = []
    for proposition in value:
        if not isinstance(proposition, dict):
            continue
        propositions.append({str(key): field_value for key, field_value in proposition.items()})
    return propositions


async def handle_socratic(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    _intent: Intent,
) -> ChatResponse:
    """Handle a Socratic tutorial request — submit work for preparation.

    This is the entry point from the normal chat routing. The user sends
    their work and a topic, and we kick off async preparation.
    """
    # Check if user already has an active tutorial
    active = await get_active_tutorial(session, message.user_id)
    if active and active.phase != "complete":
        if active.phase == "ready":
            return ChatResponse(
                content=(
                    f"You have a tutorial ready on '{active.topic}'. "
                    "Send 'start tutorial' to begin, or 'cancel tutorial' to discard it."
                ),
                agent="socratic",
                metadata={"tutorial_id": str(active.id), "phase": active.phase},
            )
        if active.phase in ("dialogue", "opening", "closing"):
            return ChatResponse(
                content=(
                    f"You have an active tutorial on '{active.topic}'. "
                    "Continue with your response, or send 'end tutorial' to finish."
                ),
                agent="socratic",
                metadata={"tutorial_id": str(active.id), "phase": active.phase},
            )
        return ChatResponse(
            content=(
                f"Tutorial on '{active.topic}' is being prepared. I'll notify you when it's ready."
            ),
            agent="socratic",
            metadata={"tutorial_id": str(active.id), "phase": active.phase},
        )

    # Detect work type from content
    work_type = _detect_work_type(message.content)

    # Extract topic (first line or first 100 chars)
    topic = _extract_topic(message.content)

    # Create tutorial session in DB
    tutorial = await create_tutorial_session(
        session,
        user_id=message.user_id,
        topic=topic,
        submitted_work=message.content,
        work_type=work_type,
    )
    await session.commit()

    # Run preparation synchronously for now.
    # In production, this should be enqueued via ARQ for async processing.
    await _run_preparation(
        tutorial_id=tutorial.id,
        user_id=message.user_id,
        topic=topic,
        submitted_work=message.content,
        work_type=work_type,
        client=client,
        session=session,
    )

    return ChatResponse(
        content=(
            f"Tutorial prepared on '{topic}'. Send 'start tutorial' when you're ready to begin."
        ),
        agent="socratic",
        metadata={
            "tutorial_id": str(tutorial.id),
            "phase": "ready",
            "work_type": work_type,
        },
    )


async def start_tutorial(
    tutorial_id: uuid.UUID,
    client: AsyncAnthropic,
    session: AsyncSession,
) -> ChatResponse:
    """Start a prepared tutorial — returns the opening question."""
    tutorial = await get_tutorial_session(session, tutorial_id)
    if tutorial is None:
        return ChatResponse(
            content="Tutorial not found.",
            agent="socratic",
            metadata={"error": "not_found"},
        )

    if tutorial.phase != "ready":
        return ChatResponse(
            content=f"Tutorial is in phase '{tutorial.phase}', not ready to start.",
            agent="socratic",
            metadata={"tutorial_id": str(tutorial_id), "phase": tutorial.phase},
        )

    # Build initial state from stored preparation
    state = make_initial_state(
        session_id=str(tutorial.id),
        user_id=tutorial.user_id,
        topic=tutorial.topic,
        submitted_work=tutorial.submitted_work,
        work_type=tutorial.work_type,
        client=client,
    )

    # Load preparation data into state
    propositions = _stored_propositions(tutorial.propositions)
    if propositions:
        state["propositions"] = propositions
        state["claims_unresolved"] = [dict(proposition) for proposition in propositions]
    if tutorial.preparation:
        state["tutor_prep"] = tutorial.preparation.get("tutor_prep", {})
        state["devils_advocate_prep"] = tutorial.preparation.get("devils_advocate_prep", {})
        state["clarifier_prep"] = tutorial.preparation.get("clarifier_prep", {})
        state["connector_prep"] = tutorial.preparation.get("connector_prep", {})

    # Compile and invoke the dialogue graph
    graph = build_dialogue_graph()
    compiled = graph.compile(checkpointer=_checkpointer)

    config: RunnableConfig = {"configurable": {"thread_id": str(tutorial.id)}}
    result = await compiled.ainvoke(
        TutorialGraphState.model_validate(state),
        config=config,
        context=TutorialRuntimeContext(client=client),
    )

    # Extract the opening question from dialogue history
    dialogue = result.get("dialogue_history", [])
    opening = dialogue[-1] if dialogue else {}
    content = opening.get("content", "Let's begin. Tell me about your work.")

    # Update DB phase
    await update_tutorial_phase(session, tutorial.id, "dialogue")
    await session.commit()

    return ChatResponse(
        content=content,
        agent="socratic",
        metadata={
            "tutorial_id": str(tutorial.id),
            "phase": "dialogue",
            "speaker": "tutor",
        },
    )


async def process_tutorial_turn(
    tutorial_id: uuid.UUID,
    user_message: str,
    client: AsyncAnthropic,
    session: AsyncSession,
) -> ChatResponse:
    """Process a user message during an active tutorial.

    Resumes the LangGraph graph from the interrupt point, passes the
    user's message, and returns the next agent response.
    """
    tutorial = await get_tutorial_session(session, tutorial_id)
    if tutorial is None:
        return ChatResponse(
            content="Tutorial not found.",
            agent="socratic",
            metadata={"error": "not_found"},
        )

    graph = build_dialogue_graph()
    compiled = graph.compile(checkpointer=_checkpointer)
    config: RunnableConfig = {"configurable": {"thread_id": str(tutorial.id)}}

    from langgraph.types import Command

    # Resume from interrupt with the user's message
    result = await compiled.ainvoke(
        Command(resume=user_message),
        config=config,
        context=TutorialRuntimeContext(client=client),
    )

    # Check if tutorial is ending
    phase = result.get("phase", TutorialPhase.DIALOGUE)

    if phase in (TutorialPhase.ANALYSING, TutorialPhase.COMPLETE):
        # Tutorial ended — run analysis
        analysis = await analyse_tutorial(result, client)
        report = format_analysis_report(analysis, tutorial.topic)

        # Store results in DB
        await store_tutorial_results(
            session,
            tutorial.id,
            transcript=result.get("dialogue_history", []),
            assessor_log=result.get("assessor_log", []),
            analysis=analysis.model_dump(),
            turn_count=result.get("current_turn", 0),
            speaking_ratio_student_pct=_calc_speaking_ratio(result),
            bloom_start=_get_bloom_start(result),
            bloom_end=result.get("bloom_level"),
            knowledge_gaps_found=len(analysis.knowledge_gaps),
            knowledge_gaps_addressed=sum(1 for g in analysis.knowledge_gaps if g.get("addressed")),
        )
        await session.commit()

        return ChatResponse(
            content=f"Tutorial complete.\n\n{report}",
            agent="socratic",
            metadata={
                "tutorial_id": str(tutorial.id),
                "phase": "complete",
                "analysis": analysis.model_dump(),
            },
        )

    # Extract the latest agent response
    dialogue = result.get("dialogue_history", [])
    latest = dialogue[-1] if dialogue else {}
    content = latest.get("content", "...")
    speaker = latest.get("role", "tutor")

    return ChatResponse(
        content=content,
        agent="socratic",
        metadata={
            "tutorial_id": str(tutorial.id),
            "phase": phase,
            "speaker": speaker,
            "turn": result.get("current_turn", 0),
            "bloom_level": result.get("bloom_level"),
        },
    )


async def end_tutorial(
    tutorial_id: uuid.UUID,
    client: AsyncAnthropic,
    session: AsyncSession,
) -> ChatResponse:
    """End a tutorial early and run analysis on what we have."""
    tutorial = await get_tutorial_session(session, tutorial_id)
    if tutorial is None:
        return ChatResponse(
            content="Tutorial not found.",
            agent="socratic",
            metadata={"error": "not_found"},
        )

    # Get the current state from the checkpointer
    graph = build_dialogue_graph()
    compiled = graph.compile(checkpointer=_checkpointer)
    config: RunnableConfig = {"configurable": {"thread_id": str(tutorial.id)}}

    snapshot = await compiled.aget_state(config)
    state = snapshot.values if snapshot else {}

    if not state.get("dialogue_history"):
        await update_tutorial_phase(session, tutorial.id, "complete")
        await session.commit()
        return ChatResponse(
            content="Tutorial ended (no dialogue to analyse).",
            agent="socratic",
            metadata={"tutorial_id": str(tutorial.id), "phase": "complete"},
        )

    # Run analysis on what we have
    state["client"] = client
    analysis = await analyse_tutorial(state, client)
    report = format_analysis_report(analysis, tutorial.topic)

    await store_tutorial_results(
        session,
        tutorial.id,
        transcript=state.get("dialogue_history", []),
        assessor_log=state.get("assessor_log", []),
        analysis=analysis.model_dump(),
        turn_count=state.get("current_turn", 0),
        speaking_ratio_student_pct=_calc_speaking_ratio(state),
        bloom_start=_get_bloom_start(state),
        bloom_end=state.get("bloom_level"),
        knowledge_gaps_found=len(analysis.knowledge_gaps),
        knowledge_gaps_addressed=sum(1 for g in analysis.knowledge_gaps if g.get("addressed")),
    )
    await session.commit()

    return ChatResponse(
        content=f"Tutorial ended early.\n\n{report}",
        agent="socratic",
        metadata={
            "tutorial_id": str(tutorial.id),
            "phase": "complete",
            "analysis": analysis.model_dump(),
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _run_preparation(
    *,
    tutorial_id: uuid.UUID,
    user_id: str,
    topic: str,
    submitted_work: str,
    work_type: str,
    client: AsyncAnthropic,
    session: AsyncSession,
) -> None:
    """Run the preparation phase (synchronous for now, async via ARQ later)."""
    state = make_initial_state(
        session_id=str(tutorial_id),
        user_id=user_id,
        topic=topic,
        submitted_work=submitted_work,
        work_type=work_type,
        client=client,
    )

    graph = build_preparation_graph()
    compiled = graph.compile()
    result = await compiled.ainvoke(
        TutorialGraphState.model_validate(state),
        context=TutorialRuntimeContext(client=client),
    )

    # Store preparation in DB
    await store_preparation(
        session,
        tutorial_id,
        propositions=result.get("propositions", []),
        preparation={
            "tutor_prep": result.get("tutor_prep", {}),
            "devils_advocate_prep": result.get("devils_advocate_prep", {}),
            "clarifier_prep": result.get("clarifier_prep", {}),
            "connector_prep": result.get("connector_prep", {}),
        },
    )
    await session.commit()

    logger.info(
        "tutorial_preparation_complete",
        tutorial_id=str(tutorial_id),
        propositions=len(result.get("propositions", [])),
    )


def _detect_work_type(content: str) -> str:
    """Simple heuristic to detect work type from content."""
    lower = content.lower()
    if any(kw in lower for kw in ("def ", "class ", "import ", "function ", "```")):
        return WorkType.CODE
    if any(kw in lower for kw in ("case study", "case-study")):
        return WorkType.CASE_STUDY
    if any(kw in lower for kw in ("blog post", "article")):
        return WorkType.BLOG
    if any(kw in lower for kw in ("argument", "thesis", "position")):
        return WorkType.ARGUMENT
    if any(kw in lower for kw in ("research", "findings", "study")):
        return WorkType.RESEARCH
    if any(kw in lower for kw in ("design", "architecture", "system")):
        return WorkType.DESIGN
    return WorkType.ESSAY


def _extract_topic(content: str) -> str:
    """Extract a topic from the first line or first 100 chars."""
    first_line = content.strip().split("\n")[0].strip()
    if len(first_line) > 100:
        return first_line[:97] + "..."
    return first_line or "Untitled tutorial"


def _calc_speaking_ratio(state: dict[str, Any]) -> float | None:
    """Calculate the student's speaking ratio as a percentage."""
    ratio = state.get("speaking_ratio", {})
    user_words = ratio.get("user_words", 0)
    agent_words = ratio.get("agent_words", 0)
    total = user_words + agent_words
    if total == 0:
        return None
    return round(user_words / total * 100, 1)


def _get_bloom_start(state: dict[str, Any]) -> str | None:
    """Get the Bloom's level from the first assessor log entry."""
    log = state.get("assessor_log", [])
    if log:
        return log[0].get("bloom_level")
    return None
