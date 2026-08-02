"""Socratic tutorial LangGraph graph — preparation + dialogue + analysis.

Architecture: LangGraph StateGraph with a validated blackboard (TutorialGraphState).
- Preparation: Send() fan-out for parallel agent prep
- Dialogue: Assessor routing via Command(), interrupt() for HITL
- Analysis: Post-tutorial analysis via dedicated node

Key LangGraph patterns:
- Command(goto=..., update=...) for routing + state update in one return
- Send() for parallel fan-out to prep agents
- interrupt() for human-in-the-loop dialogue turns
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, Send, interrupt
from pydantic import BaseModel, ConfigDict, Field

from src.app.agents.socratic.agents.assessor import assess_turn
from src.app.agents.socratic.agents.clarifier import clarify
from src.app.agents.socratic.agents.connector import connect
from src.app.agents.socratic.agents.devils_advocate import challenge
from src.app.agents.socratic.agents.tutor import tutor_opening, tutor_respond
from src.app.agents.socratic.preparation import (
    extract_propositions,
    prepare_clarifier,
    prepare_connector,
    prepare_devils_advocate,
    prepare_tutor,
)
from src.app.agents.socratic.retrieval import retrieve_second_brain_context
from src.app.agents.socratic.state import (
    AssessorAction,
    AssessorDecision,
    DialogueTurn,
    TutorialPhase,
)
from src.app.config import get_settings

logger = structlog.get_logger()

MAX_CONSECUTIVE_SILENCES = 3


def _merge_dialogue(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append dialogue updates emitted by parallel and sequential nodes."""
    return [*existing, *new]


def _merge_assessor_log(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append hidden assessor decisions without replacing prior entries."""
    return [*existing, *new]


class TutorialGraphState(BaseModel):
    """Validated Socratic blackboard state used at the LangGraph boundary.

    The public state factory still returns dictionaries, which LangGraph validates
    into this model before node execution. Mapping compatibility keeps the agent
    payload and direct-node test contracts stable.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str = ""
    user_id: str = ""
    topic: str = ""
    submitted_work: str = ""
    work_type: str = "other"
    phase: str = ""

    propositions: list[dict[str, Any]] = Field(default_factory=list)
    tutor_prep: dict[str, Any] = Field(default_factory=dict)
    devils_advocate_prep: dict[str, Any] = Field(default_factory=dict)
    clarifier_prep: dict[str, Any] = Field(default_factory=dict)
    connector_prep: dict[str, Any] = Field(default_factory=dict)

    dialogue_history: Annotated[list[dict[str, Any]], _merge_dialogue] = Field(default_factory=list)
    current_turn: int = 0
    current_speaker: str = ""
    current_proposition_index: int = 0
    propositions_explored: list[int] = Field(default_factory=list)

    assessor_log: Annotated[list[dict[str, Any]], _merge_assessor_log] = Field(default_factory=list)
    bloom_level: str = ""
    speaking_ratio: dict[str, int] = Field(
        default_factory=lambda: {"user_words": 0, "agent_words": 0}
    )
    cognitive_load: str = ""
    emotional_state: str = ""
    no_intervention_count: int = 0
    assessor_suggestion: str | None = None

    working_memory: list[dict[str, Any]] = Field(default_factory=list)
    session_summary: str = ""

    claims_resolved: list[dict[str, Any]] = Field(default_factory=list)
    claims_unresolved: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_gaps: list[dict[str, str]] = Field(default_factory=list)

    analysis: dict[str, Any] | None = None
    error: str | None = None

    def __getitem__(self, key: str) -> Any:
        """Expose fields through the mapping interface used by existing nodes."""
        if key not in type(self).model_fields:
            raise KeyError(key)
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        """Return a state field or a caller-provided default."""
        if key not in type(self).model_fields:
            return default
        return getattr(self, key)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in type(self).model_fields


class TutorialRuntimeContext(BaseModel):
    """Non-durable dependencies injected per invocation, never checkpointed."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: Any
    db_session: Any = None
    embeddings: Any = None


def _runtime_context(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None,
) -> TutorialRuntimeContext:
    """Read injected dependencies, with a direct-node compatibility fallback."""
    if runtime is not None:
        return runtime.context

    client = state.get("client")
    if client is None:
        raise RuntimeError("Socratic graph node requires a runtime LLM client")
    return TutorialRuntimeContext(
        client=client,
        db_session=state.get("db_session"),
        embeddings=state.get("embeddings"),
    )


# ---------------------------------------------------------------------------
# Preparation phase nodes
# ---------------------------------------------------------------------------


async def extract_propositions_node(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None = None,
) -> Command:
    """Extract atomic propositions from the submitted work.

    After extraction, fan out to 4 prep agents in parallel via Send().
    """
    client = _runtime_context(state, runtime).client
    propositions = await extract_propositions(
        submitted_work=state["submitted_work"],
        work_type=state.get("work_type", "other"),
        client=client,
    )

    prop_dicts = [p.model_dump() for p in propositions]

    # Fan out to all 4 prep agents simultaneously
    return Command(
        update={
            "propositions": prop_dicts,
            "phase": TutorialPhase.PREPARING,
            "claims_unresolved": prop_dicts.copy(),
        },
        goto=[
            Send("tutor_prep_node", {**dict(state), "propositions": prop_dicts}),
            Send("da_prep_node", {**dict(state), "propositions": prop_dicts}),
            Send("clarifier_prep_node", {**dict(state), "propositions": prop_dicts}),
            Send("connector_prep_node", {**dict(state), "propositions": prop_dicts}),
        ],
    )


async def tutor_prep_node(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None = None,
) -> dict:
    """Prepare the Tutor's questioning plan."""
    client = _runtime_context(state, runtime).client
    prep = await prepare_tutor(
        propositions=state.get("propositions", []),
        submitted_work=state["submitted_work"],
        client=client,
    )
    return {"tutor_prep": prep.model_dump()}


async def da_prep_node(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None = None,
) -> dict:
    """Prepare the Devil's Advocate's counter-arguments."""
    client = _runtime_context(state, runtime).client
    prep = await prepare_devils_advocate(
        propositions=state.get("propositions", []),
        submitted_work=state["submitted_work"],
        client=client,
    )
    return {"devils_advocate_prep": prep.model_dump()}


async def clarifier_prep_node(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None = None,
) -> dict:
    """Prepare the Clarifier's ambiguity detection."""
    client = _runtime_context(state, runtime).client
    prep = await prepare_clarifier(
        propositions=state.get("propositions", []),
        submitted_work=state["submitted_work"],
        client=client,
    )
    return {"clarifier_prep": prep.model_dump()}


async def connector_prep_node(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None = None,
) -> dict:
    """Prepare the Connector's second-brain links."""
    context = _runtime_context(state, runtime)
    client = context.client

    # Retrieve second brain context if DB session is available
    second_brain_context = ""
    db_session = context.db_session
    if db_session is not None:
        second_brain_context = await retrieve_second_brain_context(
            user_id=state.get("user_id", ""),
            propositions=state.get("propositions", []),
            submitted_work=state["submitted_work"],
            db_session=db_session,
            embeddings=context.embeddings,
        )

    prep = await prepare_connector(
        propositions=state.get("propositions", []),
        submitted_work=state["submitted_work"],
        client=client,
        second_brain_context=second_brain_context,
    )
    return {"connector_prep": prep.model_dump()}


async def merge_preparation_node(state: TutorialGraphState) -> dict:
    """Merge all preparation results and mark tutorial as ready.

    This node runs after all 4 prep agents complete (Send fan-in).
    """
    logger.info(
        "preparation_complete",
        session_id=state.get("session_id"),
        proposition_count=len(state.get("propositions", [])),
    )
    return {"phase": TutorialPhase.READY}


# ---------------------------------------------------------------------------
# Dialogue phase nodes
# ---------------------------------------------------------------------------


async def opening_node(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None = None,
) -> dict:
    """Tutor delivers the Feynman-style opening question."""
    client = _runtime_context(state, runtime).client
    response = await tutor_opening(dict(state), client)

    turn = DialogueTurn(
        role="tutor",
        content=response.content,
        question_type=response.question_type,
        think=response.think,
    )

    return {
        "phase": TutorialPhase.DIALOGUE,
        "dialogue_history": [turn.model_dump()],
        "current_speaker": "tutor",
        "current_turn": 1,
        "working_memory": [turn.model_dump()],
    }


async def user_turn_node(state: TutorialGraphState) -> dict:
    """Wait for user input via LangGraph interrupt().

    The interrupt pauses the graph and returns control to the caller.
    When resumed with Command(resume=user_message), the user's message
    is captured here.
    """
    user_message = interrupt("Waiting for student response")

    # Update speaking ratio
    ratio = state.get("speaking_ratio", {"user_words": 0, "agent_words": 0})
    user_words = ratio["user_words"] + len(str(user_message).split())

    turn = DialogueTurn(
        role="user",
        content=str(user_message),
    )

    # Update working memory (keep last N turns)
    settings = get_settings()
    max_turns = settings.socratic_working_memory_turns
    working = [*state.get("working_memory", []), turn.model_dump()]
    if len(working) > max_turns:
        working = working[-max_turns:]

    return {
        "dialogue_history": [turn.model_dump()],
        "current_speaker": "user",
        "current_turn": state.get("current_turn", 0) + 1,
        "speaking_ratio": {"user_words": user_words, "agent_words": ratio.get("agent_words", 0)},
        "working_memory": working,
    }


async def assessor_gate_node(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None = None,
) -> Command:
    """Assessor evaluates and routes to the appropriate agent.

    Uses Command() for routing + state update in one return.
    """
    client = _runtime_context(state, runtime).client
    decision = await assess_turn(dict(state), client)

    # Log Assessor's hidden reasoning
    assessor_entry = {
        "turn": state.get("current_turn", 0),
        "action": decision.action,
        "reasoning": decision.reasoning,
        "bloom_level": decision.bloom_level,
        "cognitive_load": decision.cognitive_load,
        "emotional_state": decision.emotional_state,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # Handle proposition advancement
    prop_idx = state.get("current_proposition_index", 0)
    explored = list(state.get("propositions_explored", []))
    if decision.should_advance_proposition:
        explored.append(prop_idx)
        prop_idx = min(prop_idx + 1, len(state.get("propositions", [])) - 1)

    # No-intervention counter
    no_intervention_count = state.get("no_intervention_count", 0)

    # Hard cap: after MAX_CONSECUTIVE_SILENCES, force tutor re-engagement
    if (
        decision.action == AssessorAction.NO_INTERVENTION
        and no_intervention_count >= MAX_CONSECUTIVE_SILENCES
    ):
        logger.warning(
            "silence_cap_reached",
            consecutive=no_intervention_count,
            session_id=state.get("session_id"),
            turn=state.get("current_turn", 0),
        )
        decision = AssessorDecision(
            action=AssessorAction.TUTOR,
            reasoning=f"Auto-escalated after {no_intervention_count} consecutive silences",
            bloom_level=decision.bloom_level,
            cognitive_load=decision.cognitive_load,
            emotional_state=decision.emotional_state,
            question_suggestion=(
                "The student has been quiet for several turns. "
                "Ask a warm, lower-difficulty question to re-engage them."
            ),
            should_advance_proposition=False,
            speaking_ratio_ok=decision.speaking_ratio_ok,
        )

    # State updates common to all routing decisions
    update: dict[str, Any] = {
        "assessor_log": [assessor_entry],
        "bloom_level": decision.bloom_level,
        "cognitive_load": decision.cognitive_load,
        "emotional_state": decision.emotional_state,
        "current_proposition_index": prop_idx,
        "propositions_explored": explored,
    }

    # Route to the selected agent
    action_to_node = {
        AssessorAction.TUTOR: "tutor_turn_node",
        AssessorAction.DEVILS_ADVOCATE: "da_turn_node",
        AssessorAction.CLARIFIER: "clarifier_turn_node",
        AssessorAction.CONNECTOR: "connector_turn_node",
        AssessorAction.NO_INTERVENTION: "no_intervention_node",
        AssessorAction.CLOSING: "closing_node",
    }

    target = action_to_node.get(decision.action, "tutor_turn_node")

    if decision.action == AssessorAction.NO_INTERVENTION:
        update["no_intervention_count"] = no_intervention_count + 1
    else:
        update["no_intervention_count"] = 0

    # Store the suggestion for the selected agent
    update["assessor_suggestion"] = decision.question_suggestion

    return Command(goto=target, update=update)


async def tutor_turn_node(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None = None,
) -> dict:
    """Tutor responds with a Socratic question."""
    client = _runtime_context(state, runtime).client
    suggestion = state.get("assessor_suggestion")
    response = await tutor_respond(dict(state), client, assessor_suggestion=suggestion)

    turn = DialogueTurn(
        role="tutor",
        content=response.content,
        question_type=response.question_type,
        bloom_level=state.get("bloom_level"),
        think=response.think,
    )

    ratio = state.get("speaking_ratio", {"user_words": 0, "agent_words": 0})
    agent_words = ratio.get("agent_words", 0) + len(response.content.split())

    settings = get_settings()
    max_turns = settings.socratic_working_memory_turns
    working = [*state.get("working_memory", []), turn.model_dump()]
    if len(working) > max_turns:
        working = working[-max_turns:]

    return {
        "dialogue_history": [turn.model_dump()],
        "current_speaker": "tutor",
        "speaking_ratio": {"user_words": ratio.get("user_words", 0), "agent_words": agent_words},
        "working_memory": working,
    }


async def da_turn_node(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None = None,
) -> dict:
    """Devil's Advocate challenges the student."""
    client = _runtime_context(state, runtime).client
    suggestion = state.get("assessor_suggestion")
    response = await challenge(dict(state), client, assessor_suggestion=suggestion)

    turn = DialogueTurn(
        role="devils_advocate",
        content=response.content,
        question_type=response.question_type,
        bloom_level=state.get("bloom_level"),
        think=response.think,
    )

    ratio = state.get("speaking_ratio", {"user_words": 0, "agent_words": 0})
    agent_words = ratio.get("agent_words", 0) + len(response.content.split())

    settings = get_settings()
    max_turns = settings.socratic_working_memory_turns
    working = [*state.get("working_memory", []), turn.model_dump()]
    if len(working) > max_turns:
        working = working[-max_turns:]

    return {
        "dialogue_history": [turn.model_dump()],
        "current_speaker": "devils_advocate",
        "speaking_ratio": {"user_words": ratio.get("user_words", 0), "agent_words": agent_words},
        "working_memory": working,
    }


async def clarifier_turn_node(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None = None,
) -> dict:
    """Clarifier demands precision."""
    client = _runtime_context(state, runtime).client
    suggestion = state.get("assessor_suggestion")
    response = await clarify(dict(state), client, assessor_suggestion=suggestion)

    turn = DialogueTurn(
        role="clarifier",
        content=response.content,
        question_type=response.question_type,
        bloom_level=state.get("bloom_level"),
        think=response.think,
    )

    ratio = state.get("speaking_ratio", {"user_words": 0, "agent_words": 0})
    agent_words = ratio.get("agent_words", 0) + len(response.content.split())

    settings = get_settings()
    max_turns = settings.socratic_working_memory_turns
    working = [*state.get("working_memory", []), turn.model_dump()]
    if len(working) > max_turns:
        working = working[-max_turns:]

    return {
        "dialogue_history": [turn.model_dump()],
        "current_speaker": "clarifier",
        "speaking_ratio": {"user_words": ratio.get("user_words", 0), "agent_words": agent_words},
        "working_memory": working,
    }


async def connector_turn_node(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None = None,
) -> dict:
    """Connector links to prior knowledge."""
    client = _runtime_context(state, runtime).client
    suggestion = state.get("assessor_suggestion")
    response = await connect(dict(state), client, assessor_suggestion=suggestion)

    turn = DialogueTurn(
        role="connector",
        content=response.content,
        question_type=response.question_type,
        bloom_level=state.get("bloom_level"),
        think=response.think,
    )

    ratio = state.get("speaking_ratio", {"user_words": 0, "agent_words": 0})
    agent_words = ratio.get("agent_words", 0) + len(response.content.split())

    settings = get_settings()
    max_turns = settings.socratic_working_memory_turns
    working = [*state.get("working_memory", []), turn.model_dump()]
    if len(working) > max_turns:
        working = working[-max_turns:]

    return {
        "dialogue_history": [turn.model_dump()],
        "current_speaker": "connector",
        "speaking_ratio": {"user_words": ratio.get("user_words", 0), "agent_words": agent_words},
        "working_memory": working,
    }


async def no_intervention_node(state: TutorialGraphState) -> dict:
    """Assessor chose silence — let the student continue thinking.

    This is a first-class pedagogical action (MetaCLASS). No agent speaks.
    We just loop back to waiting for user input.
    """
    logger.info(
        "no_intervention",
        turn=state.get("current_turn", 0),
        consecutive_silences=state.get("no_intervention_count", 0),
    )
    return {}


async def closing_node(
    state: TutorialGraphState,
    runtime: Runtime[TutorialRuntimeContext] | None = None,
) -> dict:
    """Tutor delivers closing synthesis question.

    Asks the student to summarise what they've learned — a meta-cognitive
    exercise that reinforces learning.
    """
    client = _runtime_context(state, runtime).client

    # Use the Tutor for the closing meta-question
    response = await tutor_respond(
        dict(state),
        client,
        assessor_suggestion=(
            "Ask a meta-question: what has the student learned? "
            "What would they change about their work now? "
            "This is the final question."
        ),
    )

    turn = DialogueTurn(
        role="tutor",
        content=response.content,
        question_type=response.question_type,
        think=response.think,
    )

    return {
        "phase": TutorialPhase.CLOSING,
        "dialogue_history": [turn.model_dump()],
        "current_speaker": "tutor",
    }


# ---------------------------------------------------------------------------
# Post-dialogue: final user response and end
# ---------------------------------------------------------------------------


async def final_user_response_node(state: TutorialGraphState) -> dict:
    """Capture the student's final reflection after the closing question."""
    user_message = interrupt("Waiting for student's closing reflection")

    turn = DialogueTurn(
        role="user",
        content=str(user_message),
    )

    return {
        "dialogue_history": [turn.model_dump()],
        "phase": TutorialPhase.ANALYSING,
    }


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def _route_after_agent_turn(state: TutorialGraphState) -> str:
    """After any agent speaks, loop back to user_turn for the next response."""
    phase = state.get("phase", TutorialPhase.DIALOGUE)
    if phase == TutorialPhase.CLOSING:
        return "final_user_response_node"
    return "user_turn_node"


def _route_after_opening(state: TutorialGraphState) -> str:
    """After the opening, wait for user response."""
    return "user_turn_node"


def _route_after_no_intervention(state: TutorialGraphState) -> str:
    """After silence, wait for user to continue."""
    return "user_turn_node"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_preparation_graph() -> StateGraph[TutorialGraphState, TutorialRuntimeContext]:
    """Build the preparation subgraph (async, runs before tutorial).

    Flow:
    START → extract_propositions → [Send fan-out to 4 prep agents] → merge → END
    """
    graph = StateGraph(TutorialGraphState, context_schema=TutorialRuntimeContext)

    graph.add_node("extract_propositions", extract_propositions_node)
    graph.add_node("tutor_prep_node", tutor_prep_node)
    graph.add_node("da_prep_node", da_prep_node)
    graph.add_node("clarifier_prep_node", clarifier_prep_node)
    graph.add_node("connector_prep_node", connector_prep_node)
    graph.add_node("merge_preparation", merge_preparation_node)

    graph.add_edge(START, "extract_propositions")
    # extract_propositions_node uses Command with Send() — no static edges needed
    # After all Send() branches complete, they merge into merge_preparation
    graph.add_edge("tutor_prep_node", "merge_preparation")
    graph.add_edge("da_prep_node", "merge_preparation")
    graph.add_edge("clarifier_prep_node", "merge_preparation")
    graph.add_edge("connector_prep_node", "merge_preparation")
    graph.add_edge("merge_preparation", END)

    return graph


def build_dialogue_graph() -> StateGraph[TutorialGraphState, TutorialRuntimeContext]:
    """Build the dialogue subgraph (real-time, with HITL).

    Flow:
    START → opening → user_turn ↔ assessor_gate → [agent] → user_turn (loop)
                                                → closing → final_user_response → END
    """
    graph = StateGraph(TutorialGraphState, context_schema=TutorialRuntimeContext)

    # Dialogue nodes
    graph.add_node("opening_node", opening_node)
    graph.add_node("user_turn_node", user_turn_node)
    graph.add_node("assessor_gate_node", assessor_gate_node)
    graph.add_node("tutor_turn_node", tutor_turn_node)
    graph.add_node("da_turn_node", da_turn_node)
    graph.add_node("clarifier_turn_node", clarifier_turn_node)
    graph.add_node("connector_turn_node", connector_turn_node)
    graph.add_node("no_intervention_node", no_intervention_node)
    graph.add_node("closing_node", closing_node)
    graph.add_node("final_user_response_node", final_user_response_node)

    # Edges
    graph.add_edge(START, "opening_node")
    graph.add_conditional_edges("opening_node", _route_after_opening)
    graph.add_edge("user_turn_node", "assessor_gate_node")
    # assessor_gate_node uses Command() — no static edges needed from it

    # After each agent turn, loop back to user_turn
    graph.add_conditional_edges("tutor_turn_node", _route_after_agent_turn)
    graph.add_conditional_edges("da_turn_node", _route_after_agent_turn)
    graph.add_conditional_edges("clarifier_turn_node", _route_after_agent_turn)
    graph.add_conditional_edges("connector_turn_node", _route_after_agent_turn)
    graph.add_conditional_edges("no_intervention_node", _route_after_no_intervention)

    # Closing → final response → END
    graph.add_conditional_edges("closing_node", _route_after_agent_turn)
    graph.add_edge("final_user_response_node", END)

    return graph


def build_tutorial_graph() -> StateGraph[TutorialGraphState, TutorialRuntimeContext]:
    """Build the complete tutorial graph combining preparation and dialogue.

    For now, preparation and dialogue are separate graphs invoked sequentially.
    The preparation graph runs async (ARQ), the dialogue graph runs real-time.
    """
    return build_dialogue_graph()
