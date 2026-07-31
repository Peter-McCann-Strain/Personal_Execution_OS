"""LangGraph orchestrator — routes messages through specialist agents.

The central graph that:
1. Classifies intent via supervisor (Haiku)
2. Routes to the appropriate specialist
3. Returns the result

Uses LangGraph for graph-based workflow orchestration.
"""

from typing import Any, TypedDict

import structlog
from anthropic import AsyncAnthropic
from langgraph.graph import END, START, StateGraph

from src.app.agents.specialists.communications import triage_email
from src.app.agents.specialists.diary import process_diary_entry
from src.app.agents.specialists.memory import answer_from_memory
from src.app.agents.specialists.notification import FatigueManager, Notification
from src.app.agents.specialists.project import ai_breakdown_project
from src.app.agents.specialists.research import run_research
from src.app.agents.specialists.review import generate_weekly_review
from src.app.agents.specialists.tools import plan_tool_calls
from src.app.core.exceptions import RoutingError
from src.app.domain.models import Specialist
from src.app.domain.services.orchestrator import classify_intent

logger = structlog.get_logger()


class AgentState(TypedDict, total=False):
    """State passed through the orchestrator graph."""

    message: str
    specialist: str
    result: Any
    client: Any
    intent: Any
    context_chunks: list
    search_client: Any
    fatigue_manager: Any
    notification: Any
    # Correlation ID propagated end-to-end (HTTP middleware → graph → LLM → worker).
    # Populated in classify_node from structlog contextvars when absent.
    request_id: str


async def classify_node(state: AgentState) -> dict:
    """Supervisor node — classifies intent and picks specialist."""
    client: AsyncAnthropic = state["client"]
    # Inherit the request_id bound upstream by the HTTP middleware so every
    # LLM call, tool span, and enqueued job in this turn shares one ID.
    request_id = state.get("request_id")
    if not request_id:
        ctx = structlog.contextvars.get_contextvars()
        bound = ctx.get("request_id")
        if isinstance(bound, str) and bound:
            request_id = bound
    intent = await classify_intent(state["message"], client)
    updated: dict = {
        **state,
        "intent": intent,
        "specialist": intent.specialist.value,
    }
    if request_id:
        updated["request_id"] = request_id
    return updated


async def diary_node(state: AgentState) -> dict:
    """Diary specialist node."""
    entry = await process_diary_entry(state["message"], state["client"])
    return {**state, "result": entry.model_dump()}


async def memory_node(state: AgentState) -> dict:
    """Memory specialist node."""
    context_chunks = state.get("context_chunks", [])
    answer = await answer_from_memory(state["message"], context_chunks, state["client"])
    return {**state, "result": answer.model_dump()}


async def research_node(state: AgentState) -> dict:
    """Research specialist node — runs the full research pipeline."""
    search_client = state.get("search_client")
    if search_client is None:
        raise RuntimeError("Research node requires a 'search_client' (TavilySearch) in state")
    report = await run_research(state["message"], state["client"], search_client)
    return {**state, "result": report.model_dump()}


async def review_node(state: AgentState) -> dict:
    """Review specialist node."""
    review = await generate_weekly_review(state["message"], state["client"])
    return {**state, "result": review.model_dump()}


async def project_node(state: AgentState) -> dict:
    """Project specialist node."""
    breakdown = await ai_breakdown_project(state["message"], state["client"])
    return {**state, "result": breakdown.model_dump()}


async def communications_node(state: AgentState) -> dict:
    """Communications specialist node."""
    classification = await triage_email(state["message"], state["client"])
    return {**state, "result": classification.model_dump()}


async def tools_node(state: AgentState) -> dict:
    """Tools specialist node."""
    plan = await plan_tool_calls(state["message"], state["client"])
    return {**state, "result": plan.model_dump()}


async def notification_node(state: AgentState) -> dict:
    """Notification specialist — evaluates delivery via fatigue manager."""
    fatigue_manager: FatigueManager | None = state.get("fatigue_manager")
    notification: Notification | None = state.get("notification")
    if fatigue_manager is None or notification is None:
        raise RuntimeError(
            "Notification node requires 'fatigue_manager' and 'notification' in state"
        )
    deliver_now = fatigue_manager.should_deliver_now(notification)
    suppressed = await fatigue_manager.is_category_suppressed(notification.category)
    return {
        **state,
        "result": {
            "status": "deliver_now" if deliver_now else "batched",
            "suppressed": suppressed,
            "priority": notification.priority.value,
            "message": notification.message,
        },
    }


# Service layer handles this directly; this stub exists because routing enumerates
# all specialists and the graph must accept them.
async def plan_day_stub(state: AgentState) -> dict:
    """Plan-day stub — full pipeline runs in the chat service handler."""
    return {
        **state,
        "result": {
            "status": "plan_day_routed",
            "message": state["message"],
        },
    }


# Service layer handles this directly; this stub exists because routing enumerates
# all specialists and the graph must accept them.
async def save_stub(state: AgentState) -> dict:
    """Save stub — full pipeline runs in the chat service handler."""
    return {
        **state,
        "result": {
            "status": "save_routed",
            "message": state["message"],
        },
    }


# Service layer handles this directly; this stub exists because routing enumerates
# all specialists and the graph must accept them.
async def socratic_stub(state: AgentState) -> dict:
    """Socratic stub — full pipeline runs in the dedicated socratic handler."""
    return {
        **state,
        "result": {
            "status": "socratic_routed",
            "message": state["message"],
        },
    }


def route_to_specialist(state: dict) -> str:
    """Route to the correct specialist node based on classification."""
    specialist = state.get("specialist")
    if not specialist:
        raise RoutingError("No specialist assigned during classification")
    valid = {s.value for s in Specialist}
    if specialist not in valid:
        raise RoutingError(f"Unknown specialist: {specialist!r}")
    return specialist


def build_orchestrator_graph() -> StateGraph:
    """Build the LangGraph orchestrator graph."""
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("classify", classify_node)
    graph.add_node(Specialist.DIARY.value, diary_node)
    graph.add_node(Specialist.MEMORY.value, memory_node)
    graph.add_node(Specialist.RESEARCH.value, research_node)
    graph.add_node(Specialist.REVIEW.value, review_node)
    graph.add_node(Specialist.PROJECT.value, project_node)
    graph.add_node(Specialist.COMMUNICATIONS.value, communications_node)
    graph.add_node(Specialist.TOOLS.value, tools_node)
    graph.add_node(Specialist.NOTIFICATION.value, notification_node)
    graph.add_node(Specialist.SAVE.value, save_stub)
    graph.add_node(Specialist.PLAN_DAY.value, plan_day_stub)
    graph.add_node(Specialist.SOCRATIC.value, socratic_stub)

    # Entry edge
    graph.add_edge(START, "classify")

    # Conditional routing from classify to specialist
    graph.add_conditional_edges(
        "classify",
        route_to_specialist,
        {
            Specialist.DIARY.value: Specialist.DIARY.value,
            Specialist.MEMORY.value: Specialist.MEMORY.value,
            Specialist.RESEARCH.value: Specialist.RESEARCH.value,
            Specialist.REVIEW.value: Specialist.REVIEW.value,
            Specialist.PROJECT.value: Specialist.PROJECT.value,
            Specialist.COMMUNICATIONS.value: Specialist.COMMUNICATIONS.value,
            Specialist.TOOLS.value: Specialist.TOOLS.value,
            Specialist.NOTIFICATION.value: Specialist.NOTIFICATION.value,
            Specialist.SAVE.value: Specialist.SAVE.value,
            Specialist.PLAN_DAY.value: Specialist.PLAN_DAY.value,
            Specialist.SOCRATIC.value: Specialist.SOCRATIC.value,
        },
    )

    # All specialists end after execution
    for specialist in Specialist:
        graph.add_edge(specialist.value, END)

    return graph
