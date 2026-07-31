"""Plan my day handler — one-shot planning plus interactive morning/evening loops."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import get_settings
from src.app.core.confirmation import is_explicit_confirmation, is_explicit_rejection
from src.app.core.energy_scheduler import format_energy_schedule
from src.app.core.exceptions import DatabaseError
from src.app.core.llm_helpers import call_and_extract_text, call_and_parse
from src.app.domain.models import (
    ChatResponse,
    DayPlanArtifact,
    DayPlanTask,
    Intent,
    MessageInput,
    PendingPlanningSession,
)
from src.app.domain.services.day_plans import (
    build_day_plan_summary,
    day_plan_completion_status,
    load_carry_over_tasks,
    load_latest_day_plan,
    persist_day_plan_artifact,
    planning_source_date,
    renew_planning_session,
)

logger = structlog.get_logger()

_STANDARD_PLAN_PROMPT = (
    "You are a daily planning partner. Generate a time-blocked plan for today "
    "based on the user's calendar, tasks, goals, and configured energy patterns. "
    "Write it as a schedule — plain text time blocks, not a document with headers. "
    "Use the provided energy schedule to sequence work. Be specific about what to do and when. "
    "If the day looks overloaded, say so and suggest what to defer. "
    "No markdown headers. Time blocks like '9:00-11:00 - [task]' are fine. "
    "End with one sentence: the single most important thing to accomplish today."
)

_MORNING_PLAN_PROMPT = (
    "You are the user's pragmatic planning partner.\n"
    "Goal: turn the morning exchange into a concrete, realistic day plan.\n"
    "Rules:\n"
    "- Ask at most one focused follow-up question when the plan is still vague.\n"
    "- Once you have enough detail, switch to a draft plan and ask for confirmation.\n"
    "- Prefer 3-6 concrete tasks, not a long wishlist.\n"
    "- Use carry-over items when they matter, but do not overload the day.\n"
    "- Keep the assistant reply short, direct, and Telegram-friendly.\n"
    "- When returning needs_confirmation, provide a plan summary, a short plan text, and task list."
)

_EVENING_CLOSEOUT_PROMPT = (
    "You are closing out the user's day plan after the evening reflection.\n"
    "Goal: resolve unfinished planned tasks into completed, moved to another day, or backlog.\n"
    "Rules:\n"
    "- Work only with the listed planned tasks.\n"
    "- Ask one short follow-up question if the user's answer does not resolve enough tasks.\n"
    "- When you have enough information, return review_complete.\n"
    "- Use status values only: completed, moved_to_day, moved_to_backlog, cancelled, planned.\n"
    "- If a task moves to another day and the user gave a concrete day, include an ISO date.\n"
    "- Keep the assistant reply concise and operational."
)


class PlanningDraftTask(BaseModel):
    title: str
    source: str = "user"
    notes: str | None = None


class MorningPlanningTurn(BaseModel):
    outcome: Literal["needs_input", "needs_confirmation"]
    assistant_reply: str
    focus_summary: str = ""
    plan_summary: str = ""
    plan_text: str = ""
    tasks: list[PlanningDraftTask] = Field(default_factory=list)


class EveningCloseoutTask(BaseModel):
    title: str
    status: Literal["completed", "moved_to_day", "moved_to_backlog", "cancelled", "planned"]
    rescheduled_for: str | None = None
    notes: str | None = None


class EveningCloseoutTurn(BaseModel):
    outcome: Literal["needs_input", "review_complete"]
    assistant_reply: str
    summary: str = ""
    tasks: list[EveningCloseoutTask] = Field(default_factory=list)


def _render_standard_planning_context(
    *,
    commitments: list[dict],
    goals: list[dict],
    tasks: list[dict],
) -> str:
    """Format DB state for planning prompts."""
    context_parts: list[str] = []

    if commitments:
        lines = ["Today's Commitments:"]
        for c in commitments:
            temporal = c["temporal_normalized"]
            time_str = temporal.strftime("%H:%M") if temporal else "TBD"
            lines.append(f"  - [{time_str}] {c['normalized_action']}")
        context_parts.append("\n".join(lines))
    else:
        context_parts.append("Today's Commitments: None scheduled.")

    if goals:
        lines = ["Active Goals:"]
        for g in goals:
            pct = int((g["progress"] or 0) * 100)
            lines.append(f"  - {g['title']} ({pct}% complete, priority {g['priority']})")
        context_parts.append("\n".join(lines))
    else:
        context_parts.append("Active Goals: None set.")

    if tasks:
        lines = ["Tasks:"]
        for t in tasks:
            tags = ", ".join(t["context_tags"]) if t["context_tags"] else "none"
            lines.append(
                f"  - {t['title']} [{t['status']}] "
                f"(complexity: {t['complexity'] or 'medium'}, tags: {tags})"
            )
        context_parts.append("\n".join(lines))
    else:
        context_parts.append("Tasks: No tasks in progress or backlog.")

    context_parts.append(format_energy_schedule())
    now = datetime.now(tz=UTC)
    context_parts.insert(0, f"Current time (UTC): {now.strftime('%Y-%m-%d %H:%M')}")
    return "\n\n".join(context_parts)


def _render_plan_confirmation(plan: DayPlanArtifact) -> str:
    """Render a concrete draft plan and ask for confirmation."""
    lines = []
    if plan.focus_summary.strip():
        lines.append(plan.focus_summary.strip())
    if plan.plan_text.strip():
        lines.append(plan.plan_text.strip())
    else:
        lines.append("Draft plan for today:")
        for task in plan.tasks:
            title = task.title.strip()
            if title:
                lines.append(f"- {title}")
    lines.append("")
    lines.append("Reply yes to lock this in, or tell me what to change.")
    return "\n".join(lines).strip()


def _match_task_update(task_title: str, tasks: list[DayPlanTask]) -> DayPlanTask | None:
    """Match a closeout update to one stored plan task."""
    normalized = task_title.strip().casefold()
    if not normalized:
        return None
    for task in tasks:
        if task.title.strip().casefold() == normalized:
            return task
    for task in tasks:
        existing = task.title.strip().casefold()
        if normalized in existing or existing in normalized:
            return task
    return None


def _build_day_plan_from_turn(
    turn: MorningPlanningTurn,
    *,
    source_date: str,
    carry_over_tasks: list[str],
    previous_artifact_id: str | None,
) -> DayPlanArtifact:
    """Build a draft day-plan artifact from one planning turn."""
    tasks = [
        DayPlanTask(
            title=item.title.strip(),
            source=item.source or "user",
            notes=item.notes,
        )
        for item in turn.tasks
        if item.title.strip()
    ]
    return DayPlanArtifact(
        source_date=source_date,
        status="draft",
        focus_summary=turn.focus_summary.strip(),
        plan_summary=turn.plan_summary.strip()
        or build_day_plan_summary(
            DayPlanArtifact(
                source_date=source_date,
                tasks=tasks,
            )
        ),
        plan_text=turn.plan_text.strip(),
        tasks=tasks,
        carry_over_tasks=list(carry_over_tasks),
        previous_artifact_id=previous_artifact_id,
        created_from="telegram",
        updated_at=datetime.now(UTC),
    )


async def _fetch_planning_inputs(
    session: AsyncSession,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Load commitments, goals, and tasks for planning flows."""
    try:
        commitments = await _fetch_commitments(session)
        goals = await _fetch_goals(session)
        tasks = await _fetch_tasks(session)
    except Exception as exc:
        logger.exception("plan_day_data_fetch_failed")
        raise DatabaseError(f"plan_day data fetch failed: {exc}") from exc
    return commitments, goals, tasks


async def _handle_morning_planning_session(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    planning_session: PendingPlanningSession,
) -> ChatResponse:
    """Drive the guided morning planning conversation."""
    settings = get_settings()
    source_date = planning_session.source_date or planning_source_date(settings)

    if (
        planning_session.stage == "confirming"
        and planning_session.draft_plan
        and is_explicit_confirmation(message.content)
    ):
        finalized_plan = planning_session.draft_plan.model_copy(
            update={
                "status": "active",
                "created_from": "telegram",
                "updated_at": datetime.now(UTC),
            }
        )
        artifact_id = await persist_day_plan_artifact(
            session,
            user_id=message.user_id,
            plan=finalized_plan,
            source_id=str(
                message.metadata.get("response_id") or message.metadata.get("workflow_id") or ""
            ),
            trace_id=str(message.metadata.get("trace_id") or ""),
            workflow_id=str(message.metadata.get("workflow_id") or ""),
        )
        finalized_plan_text = finalized_plan.plan_text.strip() or "\n".join(
            f"- {task.title.strip()}" for task in finalized_plan.tasks if task.title.strip()
        )
        return ChatResponse(
            content=f"Locked in for today.\n\n{finalized_plan_text}".strip(),
            agent="plan_day",
            metadata={
                "day_plan_artifact_id": artifact_id,
                "pending_planning_session_cleared": True,
            },
        )

    commitments, goals, tasks = await _fetch_planning_inputs(session)
    carry_over_tasks = await load_carry_over_tasks(
        session,
        user_id=message.user_id,
        source_date=source_date,
    )

    prompt_parts = [
        f"Local planning date: {source_date}",
        _render_standard_planning_context(
            commitments=commitments,
            goals=goals,
            tasks=tasks,
        ),
    ]
    if carry_over_tasks:
        prompt_parts.append(
            "Carry-over or backlog to consider:\n- " + "\n- ".join(carry_over_tasks)
        )
    if planning_session.draft_plan is not None:
        prompt_parts.append(
            "Current draft plan:\n"
            + (
                planning_session.draft_plan.plan_text
                or "\n".join(f"- {task.title}" for task in planning_session.draft_plan.tasks)
            )
        )
    prompt_parts.append(f"User message: {message.content}")

    turn = await call_and_parse(
        client,
        model=settings.project_model,
        max_tokens=settings.project_max_tokens,
        system=_MORNING_PLAN_PROMPT,
        messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
        response_model=MorningPlanningTurn,
        error_context="morning_plan_dialogue",
    )

    if turn.outcome == "needs_input" or not turn.tasks:
        next_session = renew_planning_session(
            planning_session,
            settings=settings,
            stage="collecting",
        )
        return ChatResponse(
            content=turn.assistant_reply.strip(),
            agent="plan_day",
            metadata={
                "pending_planning_session": next_session.model_dump(mode="json"),
            },
        )

    latest_plan = await load_latest_day_plan(
        session,
        user_id=message.user_id,
        source_date=source_date,
    )
    draft_plan = _build_day_plan_from_turn(
        turn,
        source_date=source_date,
        carry_over_tasks=carry_over_tasks,
        previous_artifact_id=latest_plan.artifact_id if latest_plan is not None else None,
    )
    next_session = renew_planning_session(
        planning_session,
        settings=settings,
        stage="confirming",
        draft_plan=draft_plan,
    )
    return ChatResponse(
        content=_render_plan_confirmation(draft_plan),
        agent="plan_day",
        metadata={
            "pending_planning_session": next_session.model_dump(mode="json"),
            "day_plan_draft": draft_plan.model_dump(mode="json"),
        },
    )


async def _handle_evening_closeout_session(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    planning_session: PendingPlanningSession,
) -> ChatResponse:
    """Resolve unfinished day-plan tasks into done, another day, or backlog."""
    settings = get_settings()
    latest_plan = await load_latest_day_plan(
        session,
        user_id=message.user_id,
        source_date=planning_session.source_date or planning_source_date(settings),
    )
    if latest_plan is None:
        return ChatResponse(
            content="I could not find today's saved plan, so I'm dropping the closeout loop.",
            agent="plan_day",
            metadata={"pending_planning_session_cleared": True},
        )

    completed, unresolved = day_plan_completion_status(latest_plan.plan)
    unresolved_titles = planning_session.unresolved_tasks or unresolved
    if not unresolved_titles:
        return ChatResponse(
            content="Today's planned tasks already look closed out.",
            agent="plan_day",
            metadata={"pending_planning_session_cleared": True},
        )

    prompt_parts = [
        f"Local plan date: {latest_plan.plan.source_date}",
        "Current day plan:\n"
        + (
            latest_plan.plan.plan_text
            or "\n".join(f"- {task.title}" for task in latest_plan.plan.tasks)
        ),
        "Already completed:\n"
        + (
            "\n".join(f"- {title}" for title in completed)
            if completed
            else "- None explicitly closed"
        ),
        "Still unresolved:\n" + "\n".join(f"- {title}" for title in unresolved_titles),
        f"User message: {message.content}",
    ]

    turn = await call_and_parse(
        client,
        model=settings.project_model,
        max_tokens=settings.project_max_tokens,
        system=_EVENING_CLOSEOUT_PROMPT,
        messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
        response_model=EveningCloseoutTurn,
        error_context="evening_plan_closeout",
    )

    if turn.outcome == "needs_input":
        next_session = renew_planning_session(
            planning_session,
            settings=settings,
            stage="collecting",
            unresolved_tasks=unresolved_titles,
        )
        return ChatResponse(
            content=turn.assistant_reply.strip(),
            agent="plan_day",
            metadata={
                "pending_planning_session": next_session.model_dump(mode="json"),
            },
        )

    updated_tasks = [task.model_copy(deep=True) for task in latest_plan.plan.tasks]
    for update in turn.tasks:
        matched = _match_task_update(update.title, updated_tasks)
        if matched is None:
            continue
        matched.status = update.status
        matched.rescheduled_for = update.rescheduled_for
        matched.notes = update.notes

    reviewed_plan = latest_plan.plan.model_copy(
        update={
            "status": "reviewed",
            "plan_summary": turn.summary.strip() or latest_plan.plan.plan_summary,
            "tasks": updated_tasks,
            "previous_artifact_id": latest_plan.artifact_id,
            "updated_at": datetime.now(UTC),
        }
    )
    artifact_id = await persist_day_plan_artifact(
        session,
        user_id=message.user_id,
        plan=reviewed_plan,
        source_id=str(
            message.metadata.get("response_id") or message.metadata.get("workflow_id") or ""
        ),
        trace_id=str(message.metadata.get("trace_id") or ""),
        workflow_id=str(message.metadata.get("workflow_id") or ""),
    )
    return ChatResponse(
        content=turn.assistant_reply.strip() or "Closed out today's plan.",
        agent="plan_day",
        metadata={
            "day_plan_artifact_id": artifact_id,
            "pending_planning_session_cleared": True,
        },
    )


async def _handle_interactive_plan_day(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    planning_session: PendingPlanningSession,
) -> ChatResponse:
    """Route an active planning session to the right interactive flow."""
    if is_explicit_rejection(message.content):
        return ChatResponse(
            content="Okay. I'll drop the planning loop for now.",
            agent="plan_day",
            metadata={"pending_planning_session_cleared": True},
        )

    if planning_session.session_type == "morning_plan":
        return await _handle_morning_planning_session(message, client, session, planning_session)

    if planning_session.session_type == "evening_review":
        return await _handle_evening_closeout_session(message, client, session, planning_session)

    return ChatResponse(
        content="I couldn't recover the planning session cleanly, so I'm clearing it.",
        agent="plan_day",
        metadata={"pending_planning_session_cleared": True},
    )


async def handle_plan_day(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    _intent: Intent,
) -> ChatResponse:
    """Generate a standard plan or continue an active planning session."""
    pending_planning_payload = message.metadata.get("pending_planning_session")
    if isinstance(pending_planning_payload, dict):
        try:
            planning_session = PendingPlanningSession.model_validate(pending_planning_payload)
        except Exception:
            logger.warning("pending_planning_session_invalid", exc_info=True)
        else:
            return await _handle_interactive_plan_day(message, client, session, planning_session)

    settings = get_settings()
    commitments, goals, tasks = await _fetch_planning_inputs(session)
    full_context = _render_standard_planning_context(
        commitments=commitments,
        goals=goals,
        tasks=tasks,
    )

    user_prompt = f"Plan my day. Here is everything you need to know:\n\n{full_context}"
    if message.content.lower() not in ("plan my day", "plan day", "daily plan"):
        user_prompt += f"\n\nAdditional request: {message.content}"

    plan_text = await call_and_extract_text(
        client,
        model=settings.tools_model,
        max_tokens=settings.tools_summary_max_tokens,
        system=_STANDARD_PLAN_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        error_context="plan_day",
    )

    logger.info(
        "plan_day_generated",
        commitment_count=len(commitments),
        goal_count=len(goals),
        task_count=len(tasks),
    )

    return ChatResponse(
        content=plan_text,
        agent="plan_day",
        metadata={
            "commitment_count": len(commitments),
            "goal_count": len(goals),
            "task_count": len(tasks),
        },
    )


async def _fetch_commitments(session: AsyncSession) -> list[dict]:
    """Fetch today's commitments from the database."""
    try:
        result = await session.execute(
            text("""
            SELECT normalized_action, temporal_normalized
            FROM commitments
            WHERE status IN ('detected', 'confirmed', 'in_progress')
              AND temporal_normalized IS NOT NULL
              AND temporal_normalized::date = CURRENT_DATE
            ORDER BY temporal_normalized ASC
        """)
        )
        return [dict(row) for row in result.mappings().all()]
    except Exception:
        logger.exception("plan_day_commitments_fetch_failed")
        raise


async def _fetch_goals(session: AsyncSession) -> list[dict]:
    """Fetch active goals (top 5 by priority)."""
    try:
        result = await session.execute(
            text("""
            SELECT title, progress, priority
            FROM goals WHERE status = 'active'
            ORDER BY priority ASC LIMIT 5
        """)
        )
        return [dict(row) for row in result.mappings().all()]
    except Exception:
        logger.exception("plan_day_goals_fetch_failed")
        raise


async def _fetch_tasks(session: AsyncSession) -> list[dict]:
    """Fetch in-progress/backlog tasks ordered by WSJF."""
    try:
        result = await session.execute(
            text("""
            SELECT t.title, t.status, t.complexity, t.context_tags
            FROM tasks t
            WHERE t.status IN ('in_progress', 'backlog')
            ORDER BY t.wsjf_score DESC NULLS LAST
            LIMIT 10
        """)
        )
        return [dict(row) for row in result.mappings().all()]
    except Exception:
        logger.exception("plan_day_tasks_fetch_failed")
        raise
