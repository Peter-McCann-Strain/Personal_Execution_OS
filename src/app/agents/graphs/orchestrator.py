"""LangGraph orchestrator — routes messages through specialist agents.

The central graph that:
1. Classifies intent via supervisor (Haiku)
2. Routes to the appropriate specialist
3. Returns the result

Uses LangGraph for graph-based workflow orchestration.
"""

from typing import Any

import structlog
from anthropic import AsyncAnthropic
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

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


class AgentState(BaseModel):
    """Validated orchestrator state with mapping compatibility for direct node tests.

    Nodes return instances containing only the fields they update. LangGraph reads
    ``model_fields_set`` and merges those fields into the durable graph state. The
    ``None`` defaults are deliberate: LangGraph also emits Pydantic fields whose
    defaults are non-null, even when a node did not explicitly set them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    message: str | None = None
    specialist: str | None = None
    result: Any = None
    client: Any = None
    intent: Any = None
    context_chunks: list[str] | None = None
    search_client: Any = None
    fatigue_manager: FatigueManager | None = None
    notification: Notification | None = None
    # Correlation ID propagated end-to-end (HTTP middleware → graph → LLM → worker).
    # Populated in classify_node from structlog contextvars when absent.
    request_id: str | None = None

    def __getitem__(self, key: str) -> Any:
        """Expose state fields through the legacy mapping interface."""
        if key not in type(self).model_fields:
            raise KeyError(key)
        value = getattr(self, key)
        if value is None:
            raise KeyError(key)
        return value

    def get(self, key: str, default: Any = None) -> Any:
        """Return a state field or a caller-provided default."""
        if key not in type(self).model_fields:
            return default
        value = getattr(self, key)
        return default if value is None else value

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self.model_fields_set


async def classify_node(state: AgentState) -> AgentState:
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
    if request_id:
        return AgentState(
            intent=intent,
            specialist=intent.specialist.value,
            request_id=request_id,
        )
    return AgentState(intent=intent, specialist=intent.specialist.value)


async def diary_node(state: AgentState) -> AgentState:
    """Diary specialist node."""
    entry = await process_diary_entry(state["message"], state["client"])
    return AgentState(result=entry.model_dump())


async def memory_node(state: AgentState) -> AgentState:
    """Memory specialist node."""
    context_chunks = state.get("context_chunks", [])
    answer = await answer_from_memory(state["message"], context_chunks, state["client"])
    return AgentState(result=answer.model_dump())


async def research_node(state: AgentState) -> AgentState:
    """Research specialist node — runs the full research pipeline."""
    search_client = state.get("search_client")
    if search_client is None:
        raise RuntimeError("Research node requires a 'search_client' (TavilySearch) in state")
    report = await run_research(state["message"], state["client"], search_client)
    return AgentState(result=report.model_dump())


async def review_node(state: AgentState) -> AgentState:
    """Review specialist node."""
    review = await generate_weekly_review(state["message"], state["client"])
    return AgentState(result=review.model_dump())


async def project_node(state: AgentState) -> AgentState:
    """Project specialist node."""
    breakdown = await ai_breakdown_project(state["message"], state["client"])
    return AgentState(result=breakdown.model_dump())


async def communications_node(state: AgentState) -> AgentState:
    """Communications specialist node."""
    classification = await triage_email(state["message"], state["client"])
    return AgentState(result=classification.model_dump())


async def tools_node(state: AgentState) -> AgentState:
    """Tools specialist node."""
    plan = await plan_tool_calls(state["message"], state["client"])
    return AgentState(result=plan.model_dump())


async def notification_node(state: AgentState) -> AgentState:
    """Notification specialist — evaluates delivery via fatigue manager."""
    fatigue_manager: FatigueManager | None = state.get("fatigue_manager")
    notification: Notification | None = state.get("notification")
    if fatigue_manager is None or notification is None:
        raise RuntimeError(
            "Notification node requires 'fatigue_manager' and 'notification' in state"
        )
    deliver_now = fatigue_manager.should_deliver_now(notification)
    suppressed = await fatigue_manager.is_category_suppressed(notification.category)
    return AgentState(
        result={
            "status": "deliver_now" if deliver_now else "batched",
            "suppressed": suppressed,
            "priority": notification.priority.value,
            "message": notification.message,
        }
    )


# Service layer handles this directly; this stub exists because routing enumerates
# all specialists and the graph must accept them.
async def plan_day_stub(state: AgentState) -> AgentState:
    """Plan-day stub — full pipeline runs in the chat service handler."""
    return AgentState(
        result={
            "status": "plan_day_routed",
            "message": state["message"],
        }
    )


# Service layer handles this directly; this stub exists because routing enumerates
# all specialists and the graph must accept them.
async def save_stub(state: AgentState) -> AgentState:
    """Save stub — full pipeline runs in the chat service handler."""
    return AgentState(
        result={
            "status": "save_routed",
            "message": state["message"],
        }
    )


# Service layer handles this directly; this stub exists because routing enumerates
# all specialists and the graph must accept them.
async def socratic_stub(state: AgentState) -> AgentState:
    """Socratic stub — full pipeline runs in the dedicated socratic handler."""
    return AgentState(
        result={
            "status": "socratic_routed",
            "message": state["message"],
        }
    )


def route_to_specialist(state: AgentState) -> str:
    """Route to the correct specialist node based on classification."""
    specialist = state.get("specialist")
    if not specialist:
        raise RoutingError("No specialist assigned during classification")
    valid = {s.value for s in Specialist if s is not Specialist.CONVERSATIONAL}
    if specialist not in valid:
        raise RoutingError(f"Unknown specialist: {specialist!r}")
    return specialist


def build_orchestrator_graph() -> StateGraph[AgentState]:
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
        if specialist is Specialist.CONVERSATIONAL:
            continue
        graph.add_edge(specialist.value, END)

    return graph
