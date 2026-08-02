"""Agent usage, cost, interaction, and prompt-governance monitoring routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.prompts import PROMPT_VERSIONS
from src.app.api.deps import get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.core.exceptions import NotFoundError
from src.app.domain.models import Specialist
from src.app.domain.runtime import get_agent_runtime_config
from src.app.persistence.models import AgentAction

from .monitoring_common import (
    _action_to_dto,
    _optional_dict_field,
    _optional_string_field,
    _period_to_cutoff,
)
from .monitoring_models import (
    AgentActionDTO,
    AgentComparisonDTO,
    AgentCost,
    AgentLatency,
    AgentSummary,
    CostStat,
    CostTrendPoint,
    InteractionRecordDTO,
    LLMStatsDTO,
    ModelCost,
    PromptVersionDTO,
    QualityScoresDTO,
    TokenStat,
    UsageDistribution,
)

router = APIRouter()


@router.get("/monitoring/actions", response_model=PaginatedResponse[AgentActionDTO])
async def list_agent_actions(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    agent: str | None = Query(None),
    model: str | None = Query(None),
    sort: str = Query("newest"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
) -> PaginatedResponse[AgentActionDTO]:
    """List agent actions with filtering and sorting."""
    query = select(AgentAction)

    # --- Filters ---
    if agent:
        query = query.where(AgentAction.agent_name == agent)
    if model:
        query = query.where(AgentAction.model_used == model)
    if date_from:
        query = query.where(AgentAction.created_at >= date_from)
    if date_to:
        query = query.where(AgentAction.created_at <= date_to)

    # --- Sorting ---
    sort_map = {
        "newest": AgentAction.created_at.desc(),
        "oldest": AgentAction.created_at.asc(),
        "costliest": AgentAction.cost_usd.desc().nullslast(),
        "cheapest": AgentAction.cost_usd.asc().nullsfirst(),
        "slowest": AgentAction.duration_ms.desc().nullslast(),
        "fastest": AgentAction.duration_ms.asc().nullsfirst(),
    }
    order_clause = sort_map.get(sort, AgentAction.created_at.desc())
    query = query.order_by(order_clause)

    # --- Count ---
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar_one()

    # --- Paginate ---
    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    actions = list(result.scalars().all())

    items = [_action_to_dto(a) for a in actions]
    return paginate(items=items, total=total, offset=offset, limit=limit)


@router.get("/monitoring/llm-stats", response_model=LLMStatsDTO)
async def llm_stats(
    session: AsyncSession = Depends(get_db),
    period: str = Query("7d"),
) -> LLMStatsDTO:
    """Compute LLM usage statistics from agent_actions."""
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)
    period_cutoff = _period_to_cutoff(period)

    # --- Cost by period ---
    cost_today_row = await session.execute(
        text("SELECT COALESCE(SUM(cost_usd), 0) FROM agent_actions WHERE created_at >= :cutoff"),
        {"cutoff": today_start},
    )
    cost_today = float(cost_today_row.scalar_one())

    cost_week_row = await session.execute(
        text("SELECT COALESCE(SUM(cost_usd), 0) FROM agent_actions WHERE created_at >= :cutoff"),
        {"cutoff": week_start},
    )
    cost_week = float(cost_week_row.scalar_one())

    cost_month_row = await session.execute(
        text("SELECT COALESCE(SUM(cost_usd), 0) FROM agent_actions WHERE created_at >= :cutoff"),
        {"cutoff": month_start},
    )
    cost_month = float(cost_month_row.scalar_one())

    # --- Cost trend (daily) for the requested period ---
    cost_trend_rows = await session.execute(
        text("""
            SELECT DATE(created_at) AS d, COALESCE(SUM(cost_usd), 0) AS cost
            FROM agent_actions
            WHERE created_at >= :cutoff
            GROUP BY DATE(created_at)
            ORDER BY d
        """),
        {"cutoff": period_cutoff},
    )
    cost_trend = [CostTrendPoint(date=str(row.d), cost=float(row.cost)) for row in cost_trend_rows]

    # --- Cost by model ---
    cost_by_model_rows = await session.execute(
        text("""
            SELECT COALESCE(model_used, 'unknown') AS model, COALESCE(SUM(cost_usd), 0) AS cost
            FROM agent_actions
            WHERE created_at >= :cutoff
            GROUP BY model_used
            ORDER BY cost DESC
        """),
        {"cutoff": period_cutoff},
    )
    cost_by_model = [ModelCost(model=row.model, cost=float(row.cost)) for row in cost_by_model_rows]

    # --- Cost by agent ---
    cost_by_agent_rows = await session.execute(
        text("""
            SELECT agent_name AS agent, COALESCE(SUM(cost_usd), 0) AS cost
            FROM agent_actions
            WHERE created_at >= :cutoff
            GROUP BY agent_name
            ORDER BY cost DESC
        """),
        {"cutoff": period_cutoff},
    )
    cost_by_agent = [AgentCost(agent=row.agent, cost=float(row.cost)) for row in cost_by_agent_rows]

    # --- Token totals ---
    token_row = await session.execute(
        text("""
            SELECT COALESCE(SUM(tokens_in), 0) AS input,
                   COALESCE(SUM(tokens_out), 0) AS output
            FROM agent_actions
            WHERE created_at >= :cutoff
        """),
        {"cutoff": period_cutoff},
    )
    token_data = token_row.one()

    # --- Latency by agent ---
    latency_rows = await session.execute(
        text("""
            SELECT agent_name AS agent, COALESCE(AVG(duration_ms), 0) AS avg_ms
            FROM agent_actions
            WHERE created_at >= :cutoff
            GROUP BY agent_name
            ORDER BY avg_ms DESC
        """),
        {"cutoff": period_cutoff},
    )
    latency_by_agent = [
        AgentLatency(agent=row.agent, avg_ms=round(float(row.avg_ms), 1)) for row in latency_rows
    ]

    return LLMStatsDTO(
        cost=CostStat(today=cost_today, week=cost_week, month=cost_month),
        cost_trend=cost_trend,
        cost_by_model=cost_by_model,
        cost_by_agent=cost_by_agent,
        tokens=TokenStat(input=int(token_data.input), output=int(token_data.output)),
        latency_by_agent=latency_by_agent,
    )


@router.get("/monitoring/agent-comparison", response_model=AgentComparisonDTO)
async def agent_comparison(
    session: AsyncSession = Depends(get_db),
    period: str = Query("7d"),
) -> AgentComparisonDTO:
    """Compare agents by cost, latency, error rate, and usage."""
    period_cutoff = _period_to_cutoff(period)

    # --- Agent summaries ---
    summary_rows = await session.execute(
        text("""
            SELECT
                agent_name AS agent,
                COUNT(*) AS call_count,
                COALESCE(AVG(cost_usd), 0) AS avg_cost,
                COALESCE(AVG(duration_ms), 0) AS avg_latency_ms,
                COALESCE(
                    SUM(CASE WHEN action_type = 'error' THEN 1 ELSE 0 END)::float
                    / NULLIF(COUNT(*), 0),
                    0
                ) AS error_rate,
                COALESCE(SUM(COALESCE(tokens_in, 0) + COALESCE(tokens_out, 0)), 0) AS total_tokens
            FROM agent_actions
            WHERE created_at >= :cutoff
            GROUP BY agent_name
            ORDER BY call_count DESC
        """),
        {"cutoff": period_cutoff},
    )
    summaries = [
        AgentSummary(
            agent=row.agent,
            call_count=int(row.call_count),
            avg_cost=round(float(row.avg_cost), 6),
            avg_latency_ms=round(float(row.avg_latency_ms), 1),
            error_rate=round(float(row.error_rate), 4),
            total_tokens=int(row.total_tokens),
        )
        for row in summary_rows
    ]

    # --- Usage distribution ---
    usage_rows = await session.execute(
        text("""
            SELECT agent_name AS agent, COUNT(*) AS calls
            FROM agent_actions
            WHERE created_at >= :cutoff
            GROUP BY agent_name
            ORDER BY calls DESC
        """),
        {"cutoff": period_cutoff},
    )
    usage_distribution = [
        UsageDistribution(agent=row.agent, calls=int(row.calls)) for row in usage_rows
    ]

    return AgentComparisonDTO(
        summaries=summaries,
        usage_distribution=usage_distribution,
    )


@router.get("/monitoring/interactions/{interaction_id}", response_model=InteractionRecordDTO)
async def get_interaction(
    interaction_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> InteractionRecordDTO:
    """Get a single interaction record by ID."""
    from src.app.api.routes import monitoring as monitoring_facade

    record = await monitoring_facade.repo_get_interaction_by_id(session, interaction_id)
    if record is None:
        raise NotFoundError(f"Interaction not found: {interaction_id}")
    return InteractionRecordDTO(
        id=str(record.id),
        trace_id=_optional_string_field(getattr(record, "trace_id", None)),
        response_id=_optional_string_field(getattr(record, "response_id", None)),
        user_id=record.user_id,
        user_message=record.user_message,
        source=record.source,
        intent_type=record.intent_type,
        specialist=record.specialist,
        routing_confidence=record.routing_confidence,
        response_content=record.response_content,
        response_agent=record.response_agent,
        duration_ms=record.duration_ms,
        eval_status=record.eval_status,
        score_relevance=record.score_relevance,
        score_actionability=record.score_actionability,
        score_tone=record.score_tone,
        score_conciseness=record.score_conciseness,
        quality_scores=_optional_dict_field(getattr(record, "quality_scores", None)),
        channel_metrics=_optional_dict_field(getattr(record, "channel_metrics", None)),
        created_at=record.created_at.isoformat(),
    )


@router.get("/monitoring/quality-scores", response_model=QualityScoresDTO)
async def quality_scores(
    session: AsyncSession = Depends(get_db),
    start: datetime = Query(..., description="ISO-8601 start datetime"),
    end: datetime = Query(..., description="ISO-8601 end datetime"),
    specialist: str | None = Query(None, description="Filter by specialist agent name"),
) -> QualityScoresDTO:
    """Get average auto-judge quality scores within a time window."""
    from src.app.api.routes import monitoring as monitoring_facade

    start_dt = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_dt = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    scores = await monitoring_facade.repo_get_avg_scores(
        session,
        start=start_dt,
        end=end_dt,
        specialist=specialist,
    )

    def _round_or_none(val: float | None) -> float | None:
        return round(float(val), 4) if val is not None else None

    return QualityScoresDTO(
        relevance=_round_or_none(scores["relevance"]),
        actionability=_round_or_none(scores["actionability"]),
        tone=_round_or_none(scores["tone"]),
        conciseness=_round_or_none(scores["conciseness"]),
        count=scores["count"],
    )


@router.get("/monitoring/prompt-versions", response_model=list[PromptVersionDTO])
async def prompt_versions() -> list[PromptVersionDTO]:
    """Expose runtime prompt governance metadata for operator tooling."""
    from src.app.api.routes import monitoring as monitoring_facade

    settings = monitoring_facade.get_settings()
    records = [
        PromptVersionDTO(
            kind="supervisor",
            agent="routing",
            prompt_version=PROMPT_VERSIONS.get("routing"),
            prompt_source="src/app/agents/prompts/routing.py",
            model_policy=settings.classifier_model,
            eval_rubric_id=None,
            memory_namespace=None,
            confirmation_policy=None,
            allowed_tool_patterns=[],
        )
    ]

    for specialist in sorted(Specialist, key=lambda item: item.value):
        runtime = get_agent_runtime_config(specialist, settings)
        records.append(
            PromptVersionDTO(
                kind="specialist",
                agent=specialist.value,
                prompt_version=PROMPT_VERSIONS.get(specialist.value),
                prompt_source=runtime.prompt_source,
                model_policy=runtime.model_policy,
                eval_rubric_id=runtime.eval_rubric_id,
                memory_namespace=runtime.memory_namespace,
                confirmation_policy=runtime.confirmation_policy.value,
                allowed_tool_patterns=runtime.allowed_tools,
            )
        )

    return records
