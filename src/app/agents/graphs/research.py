"""LangGraph research subgraph — multi-step research workflow.

1. Generate search queries
2. Execute searches in parallel
3. Synthesise findings into report
4. Reflect on synthesis — grounded critic (Haiku) checks claims vs findings
   and decides accept / revise. Loop capped at MAX_REFLECTION_STEPS = 2.

Reflection design (2026 best practice):
    * Critic uses the WEAKER model (Haiku) while generator is Sonnet/Opus —
      halves reflection cost and avoids the self-agreement bias that comes
      from having the generator critique itself.
    * Critic is GROUNDED: it checks each synthesis claim against the
      retrieved findings rather than doing free-form vibes-based critique.
      (Naive self-critique is known to degrade open-ended writing.)
    * Max 2 loops — per SitePoint's 2026 agentic patterns guide, beyond
      two iterations accuracy gains are negligible and cost compounds.
    * Verdict is a structured Pydantic enum, not free text.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import structlog
from anthropic import AsyncAnthropic
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from src.app.agents.prompts.research import REFLECTION_PROMPT
from src.app.agents.specialists.research import (
    build_findings_payload,
    generate_search_queries,
    synthesise_findings,
)
from src.app.agents.tools.web_search import TavilySearch
from src.app.core.llm_helpers import call_and_parse_with_retry

logger = structlog.get_logger()

# Hard cap on reflection iterations.  Documented in the module docstring;
# exposed as a constant so tests and callers can reference it.
MAX_REFLECTION_STEPS = 2

# Critic (Haiku) — intentionally weaker than the synthesis generator so
# reflection cost is a fraction of generation cost.
REFLECTION_MODEL = "claude-haiku-4-5-20251001"
REFLECTION_MAX_TOKENS = 1024


class ResearchCritique(BaseModel):
    """Structured verdict returned by the grounded critic.

    Fields
    ------
    claims_traced:
        One bool per atomic claim extracted from the synthesis.  ``True``
        means the critic could trace the claim to at least one retrieved
        finding; ``False`` means the claim is unsupported or hallucinated.
    gaps:
        Specific gaps the critic identified — things the synthesis should
        have addressed but didn't, OR claims lacking evidence.
    verdict:
        ``"accept"`` when the synthesis is grounded and complete; ``"revise"``
        when another loop would materially improve it.
    rationale:
        One-sentence explanation of the verdict.  Used for telemetry and
        debugging, not shown to the user.
    """

    claims_traced: list[bool] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    verdict: Literal["accept", "revise"]
    rationale: str


class ResearchState(BaseModel):
    """Validated research state whose explicitly set fields form node updates.

    Fields default to ``None`` so LangGraph's Pydantic update extractor does not
    overwrite durable state with an unset model default during reflection loops.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    question: str | None = None
    queries: list[str] | None = None
    raw_results: list[dict[str, Any]] | None = None
    result: dict[str, Any] | None = None
    client: Any = None
    search: Any = None
    # --- reflection ---
    # Current iteration count — incremented each time ``reflect_node`` runs.
    # Starts at 0 before the first reflection pass.
    reflection_count: int | None = None
    # Most recent critique — kept on state so the revision path can read it.
    critique: dict[str, Any] | None = None
    # Hard cap on reflection loops.  Populated per-run from MAX_REFLECTION_STEPS
    # so tests can override it cheaply without monkey-patching the module.
    max_reflection_steps: int | None = None

    def __getitem__(self, key: str) -> Any:
        """Expose fields through the mapping interface used by existing nodes."""
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


async def plan_queries_node(state: ResearchState) -> ResearchState:
    """Generate search queries from the research question."""
    client: AsyncAnthropic = state["client"]
    queries = await generate_search_queries(state["question"], client)
    return ResearchState(queries=queries)


async def search_node(state: ResearchState) -> ResearchState:
    """Execute web searches for all queries in parallel.

    Uses asyncio.gather with return_exceptions=True so that a single
    failing query does not abort the whole node — failures are logged
    and the remaining successful results are still returned.
    Ordering of input queries is preserved in the concatenated results.
    """
    search_client: TavilySearch = state["search"]
    queries = state["queries"]
    results_per_query = await asyncio.gather(
        *(search_client.search(query) for query in queries),
        return_exceptions=True,
    )

    all_results: list[dict[str, Any]] = []
    for query, outcome in zip(queries, results_per_query, strict=False):
        if isinstance(outcome, BaseException):
            logger.warning(
                "research_search_query_failed",
                query_length=len(query),
                error_type=type(outcome).__name__,
            )
            continue
        all_results.extend(outcome)
    return ResearchState(raw_results=all_results)


async def synthesise_node(state: ResearchState) -> ResearchState:
    """Synthesise all findings into a report."""
    client: AsyncAnthropic = state["client"]
    findings_text, safety_flags = build_findings_payload(state["raw_results"])
    report = await synthesise_findings(state["question"], findings_text, client)
    report.search_queries = state["queries"]
    if hasattr(report, "safety_flags"):
        report.safety_flags = list(safety_flags)
    return ResearchState(result=report.model_dump())


def _render_findings_for_critic(raw_results: list[dict[str, Any]]) -> str:
    """Render retrieved findings as numbered evidence blocks for the critic.

    Kept separate from build_findings_payload because the critic does not
    need the untrusted-external-prompt wrapping — it only needs a terse,
    citable list of what was retrieved.
    """
    if not raw_results:
        return "(no findings retrieved)"
    blocks = []
    for i, r in enumerate(raw_results, start=1):
        title = (r.get("title") or "").strip() or "(untitled)"
        url = (r.get("url") or "").strip()
        content = (r.get("content") or "").strip()
        blocks.append(f"[Finding {i}] {title} ({url})\n{content}")
    return "\n\n".join(blocks)


async def reflect_node(state: ResearchState) -> ResearchState:
    """Grounded-critic reflection over the synthesis draft.

    Extracts claims from the draft, asks the critic (Haiku) whether each
    claim is supported by at least one retrieved finding, identifies gaps,
    and returns a structured verdict.  Increments ``reflection_count`` so
    the conditional edge can enforce the hard cap.
    """
    client: AsyncAnthropic = state["client"]
    draft = state.get("result") or {}
    synthesis_text = draft.get("synthesis", "") if isinstance(draft, dict) else str(draft)
    findings_text = _render_findings_for_critic(state.get("raw_results", []))
    question = state.get("question", "")

    user_message = (
        f"RESEARCH QUESTION:\n{question}\n\n"
        f"DRAFT SYNTHESIS:\n{synthesis_text}\n\n"
        f"RETRIEVED FINDINGS:\n{findings_text}\n\n"
        "Return the JSON critique."
    )

    critique = await call_and_parse_with_retry(
        client,
        model=REFLECTION_MODEL,
        max_tokens=REFLECTION_MAX_TOKENS,
        system=REFLECTION_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        response_model=ResearchCritique,
        error_context="research_reflection",
        inject_personality=False,
    )

    new_count = int(state.get("reflection_count", 0)) + 1
    return ResearchState(
        critique=critique.model_dump(),
        reflection_count=new_count,
    )


def _route_after_reflect(state: ResearchState) -> str:
    """Conditional edge router: loop to synthesise OR finalise.

    Loops back to ``synthesise`` when the critic requested a revision AND
    we have not exhausted MAX_REFLECTION_STEPS.  Otherwise emits the
    ``research_reflection_result`` telemetry event and routes to END.
    """
    critique = state.get("critique") or {}
    verdict = critique.get("verdict", "accept")
    count = int(state.get("reflection_count", 0))
    cap = int(state.get("max_reflection_steps", MAX_REFLECTION_STEPS))

    should_loop = verdict == "revise" and count < cap
    if should_loop:
        return "synthesise"

    # Terminal — fire telemetry so we can monitor reflection health.
    # accepted_first_pass: did the very first reflection accept the draft?
    # iterations:          how many reflection passes were run (≥1 at this point).
    # gaps_count:          how many gaps the final critique surfaced.
    # accepted:            whether the final verdict was "accept" (as opposed to
    #                      "revise" that hit the cap).
    gaps = critique.get("gaps") or []
    logger.info(
        "research_reflection_result",
        accepted_first_pass=(count == 1 and verdict == "accept"),
        iterations=count,
        gaps_count=len(gaps),
        accepted=(verdict == "accept"),
    )
    return END


def build_research_graph() -> StateGraph[ResearchState]:
    """Build the research subgraph with a grounded reflection loop.

    Flow
    ----
    START → plan_queries → search → synthesise → reflect → (loop | END)

    ``reflect`` either loops back to ``synthesise`` (when the critic says
    revise and we are under the cap) or routes to END.
    """
    graph = StateGraph(ResearchState)

    graph.add_node("plan_queries", plan_queries_node)
    graph.add_node("search", search_node)
    graph.add_node("synthesise", synthesise_node)
    graph.add_node("reflect", reflect_node)

    graph.add_edge(START, "plan_queries")
    graph.add_edge("plan_queries", "search")
    graph.add_edge("search", "synthesise")
    graph.add_edge("synthesise", "reflect")
    graph.add_conditional_edges(
        "reflect",
        _route_after_reflect,
        {"synthesise": "synthesise", END: END},
    )

    return graph
