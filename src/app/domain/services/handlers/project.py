"""Project handler — AI-assisted project breakdown, drafts, and WSJF prioritization."""

from __future__ import annotations

import re
from numbers import Real

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.specialists.project import ai_breakdown_project, calculate_wsjf
from src.app.config import get_settings
from src.app.domain.constants import EpisodeType, ParaCategory
from src.app.domain.models import ChatResponse, Intent, MessageInput
from src.app.domain.services.handlers._common import (
    enqueue_entity_extraction,
    enqueue_reflection_pack_refresh,
)
from src.app.domain.services.message_utils import extract_current_message
from src.app.persistence.repositories.episodes import create_episode
from src.app.persistence.repositories.projects import create_project_draft

logger = structlog.get_logger()

# Patterns that indicate "record a single task", not "break down a project".
# Bug 2 fix: we must not funnel every project-routed message through the
# heavy AI breakdown. A bare "Add a task: write the runbook" is a capture,
# and must land deterministically as a project_drafts row (or equivalent).
_SINGLE_TASK_PATTERNS = (
    "add a task",
    "add a todo",
    "add a to-do",
    "add task",
    "add todo",
    "add to-do",
    "new task",
    "create a task",
    "create task",
    "log a task",
)


async def handle_project(
    message: MessageInput,
    client: AsyncAnthropic,
    session: AsyncSession,
    _intent: Intent,
) -> ChatResponse:
    """Handle project planning and prioritization requests."""
    current = extract_current_message(message.content)
    content_lower = current.lower()

    if _is_wsjf_request(content_lower):
        return _handle_wsjf(current)

    if _is_single_task_request(content_lower):
        return await _handle_single_task(
            message=message,
            session=session,
            current_content=current,
        )

    settings = get_settings()
    breakdown = await ai_breakdown_project(current, client)
    total_hours_raw = getattr(breakdown, "total_estimated_hours", None)
    total_hours = float(total_hours_raw) if isinstance(total_hours_raw, Real) else 0.0
    if total_hours <= 0:
        total_hours = sum(
            task.estimate_hours for milestone in breakdown.milestones for task in milestone.tasks
        )

    serialised_breakdown = breakdown.model_dump(mode="json")
    project_title = breakdown.milestones[0].title if breakdown.milestones else "Project draft"
    draft = None
    if bool(getattr(settings, "project_draft_runtime_enabled", True)):
        draft = await create_project_draft(
            session,
            user_id=message.user_id,
            title=project_title,
            source_message=message.content,
            breakdown=serialised_breakdown,
        )

    lines = _render_breakdown_markdown(breakdown, total_hours=total_hours)
    episode = await create_episode(
        session,
        content="\n".join(lines),
        summary=f"Project draft: {project_title}",
        episode_type=EpisodeType.PROJECT,
        source=message.source,
        para_category=ParaCategory.PROJECT,
        tags=["project_draft"],
        metadata={
            "milestone_count": len(breakdown.milestones),
            "total_hours": total_hours,
            "project_draft_id": str(draft.id) if draft is not None else None,
            "critical_path": breakdown.critical_path,
            "risks": breakdown.risks,
        },
    )
    await session.commit()

    try:
        await enqueue_reflection_pack_refresh("episode_project_saved")
    except Exception as exc:
        logger.warning(
            "project_reflection_pack_refresh_degraded",
            episode_id=str(episode.id),
            error=str(exc),
            exc_info=True,
        )

    try:
        await enqueue_entity_extraction(
            episode_id=str(episode.id),
            text_content="\n".join(lines),
        )
    except Exception as exc:
        logger.warning(
            "project_entity_extraction_degraded",
            episode_id=str(episode.id),
            error=str(exc),
            exc_info=True,
        )

    critical_path = breakdown.critical_path or _derive_critical_path(breakdown)
    blockers = _derive_blockers(breakdown)
    unblocked_now = _derive_unblocked_now(breakdown)

    reply_lines = [
        f"Drafted a project plan with {len(breakdown.milestones)} milestones "
        f"and {total_hours:.1f}h total.",
    ]
    if draft is not None:
        reply_lines.append(f"Draft ID: {draft.id}.")
    else:
        reply_lines.append("Project draft storage is disabled by runtime flag.")
    if critical_path:
        reply_lines.append(f"Critical path: {', '.join(critical_path)}.")
    if blockers:
        reply_lines.append(f"Current blockers: {', '.join(blockers)}.")
    elif unblocked_now:
        reply_lines.append(f"Unblocked now: {', '.join(unblocked_now)}.")
    else:
        reply_lines.append("No hard blockers identified in the draft.")

    return ChatResponse(
        content=" ".join(reply_lines),
        agent="project",
        metadata={
            "episode_id": str(episode.id),
            "project_draft_id": str(draft.id) if draft is not None else None,
            "draft_created": draft is not None,
            "milestone_count": len(breakdown.milestones),
            "total_estimated_hours": total_hours,
            "critical_path": critical_path,
            "blockers": blockers,
            "unblocked_now": unblocked_now,
        },
    )


def _render_breakdown_markdown(breakdown, *, total_hours: float) -> list[str]:
    lines = ["# Project Breakdown", ""]
    project_summary = getattr(breakdown, "project_summary", None)
    if isinstance(project_summary, str) and project_summary.strip():
        lines.append(project_summary)
        lines.append("")

    for index, milestone in enumerate(breakdown.milestones, start=1):
        lines.append(f"## Milestone {index}: {milestone.title}")
        if milestone.success_criteria:
            lines.append("Success criteria:")
            for item in milestone.success_criteria:
                lines.append(f"- {item}")
        if milestone.tasks:
            lines.append("Tasks:")
            for task in milestone.tasks:
                dependency_text = (
                    f" depends on: {', '.join(task.depends_on)};" if task.depends_on else ""
                )
                tag_text = f" tags: {', '.join(task.context_tags)};" if task.context_tags else ""
                risk_text = f" risks: {', '.join(task.risks)};" if task.risks else ""
                lines.append(
                    "- "
                    f"{task.title} ({task.estimate_hours}h, {task.complexity};"
                    f"{dependency_text}{tag_text}{risk_text})"
                )
                lines.append(f"  {task.description}")
        lines.append("")

    critical_path = getattr(breakdown, "critical_path", None)
    if isinstance(critical_path, list) and critical_path:
        lines.append(f"Critical path: {', '.join(critical_path)}")
    risks = getattr(breakdown, "risks", None)
    if isinstance(risks, list) and risks:
        lines.append(f"Risks: {', '.join(risks)}")
    lines.append(f"Total estimated hours: {total_hours:.1f}h")
    return lines


def _derive_critical_path(breakdown) -> list[str]:
    critical_path: list[str] = []
    for milestone in breakdown.milestones:
        for task in milestone.tasks:
            if task.depends_on and task.title not in critical_path:
                critical_path.append(task.title)
    return critical_path[:6]


def _derive_blockers(breakdown) -> list[str]:
    blockers: list[str] = []
    for milestone in breakdown.milestones:
        for task in milestone.tasks:
            if task.depends_on:
                blockers.append(f"{task.title} waiting on {', '.join(task.depends_on)}")
            elif any("block" in risk.casefold() for risk in task.risks):
                blockers.append(f"{task.title}: {'; '.join(task.risks)}")
    return blockers[:5]


def _derive_unblocked_now(breakdown) -> list[str]:
    ready: list[str] = []
    for milestone in breakdown.milestones:
        for task in milestone.tasks:
            if not task.depends_on and len(ready) < 5:
                ready.append(task.title)
    return ready


def _is_wsjf_request(content_lower: str) -> bool:
    """Detect if a message is requesting WSJF prioritization with numeric values."""
    wsjf_keywords = {"wsjf", "prioritize", "priority score", "cost of delay"}
    has_keyword = any(keyword in content_lower for keyword in wsjf_keywords)
    numbers = re.findall(r"\b(\d{1,2})\b", content_lower)
    return has_keyword and len(numbers) >= 4


def _is_single_task_request(content_lower: str) -> bool:
    """Detect 'add a task: ...' style single-task captures."""
    return any(pattern in content_lower for pattern in _SINGLE_TASK_PATTERNS)


_TASK_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?"
    r"(?:add|create|log|new)\s+(?:a\s+|the\s+)?"
    r"(?:task|todo|to-do)"
    r"\s*[:\-]?\s*",
    flags=re.IGNORECASE,
)


def _extract_task_title(content: str) -> str:
    """Strip the leading 'add a task:' prefix and return a clean title."""
    cleaned = _TASK_PREFIX_RE.sub("", content, count=1).strip(" \t\n:;,-.")
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or content.strip()


async def _handle_single_task(
    *,
    message: MessageInput,
    session: AsyncSession,
    current_content: str,
) -> ChatResponse:
    """Persist a single-task capture as a minimal project_drafts row.

    Bug 2 regression: 'Add a task: ...' messages used to silently fail because
    the handler always ran the heavy breakdown path. Now we write a
    project_drafts row directly with a single trivial milestone so the task
    is captured even when settings.project_draft_runtime_enabled is false.
    """
    task_title = _extract_task_title(current_content)
    settings = get_settings()

    breakdown_payload = {
        "project_summary": "Single task captured from chat.",
        "milestones": [
            {
                "title": task_title,
                "success_criteria": [task_title],
                "tasks": [
                    {
                        "title": task_title,
                        "description": current_content,
                        "estimate_hours": 1.0,
                        "complexity": "simple",
                        "context_tags": ["task"],
                        "depends_on": [],
                        "risks": [],
                    },
                ],
            },
        ],
        "total_estimated_hours": 1.0,
        "critical_path": [task_title],
        "risks": [],
    }

    draft = None
    if bool(getattr(settings, "project_draft_runtime_enabled", True)):
        draft = await create_project_draft(
            session,
            user_id=message.user_id,
            title=task_title[:120] or "New task",
            source_message=current_content,
            breakdown=breakdown_payload,
        )

    episode = await create_episode(
        session,
        content=f"Task: {task_title}\n\nOriginal request: {current_content}",
        summary=f"Task captured: {task_title}"[:500],
        episode_type=EpisodeType.PROJECT,
        source=message.source,
        para_category=ParaCategory.PROJECT,
        tags=["project_task"],
        metadata={
            "project_draft_id": str(draft.id) if draft is not None else None,
            "task_title": task_title,
            "capture_mode": "single_task",
        },
    )
    await session.commit()

    try:
        await enqueue_entity_extraction(
            episode_id=str(episode.id),
            text_content=current_content,
        )
    except Exception as exc:
        logger.warning(
            "project_task_entity_extraction_degraded",
            episode_id=str(episode.id),
            error=str(exc),
            exc_info=True,
        )

    reply_parts = [f'Captured task: "{task_title}".']
    if draft is not None:
        reply_parts.append(f"Draft ID: {draft.id}.")
    else:
        reply_parts.append("Project draft storage is disabled by runtime flag.")

    return ChatResponse(
        content=" ".join(reply_parts),
        agent="project",
        metadata={
            "episode_id": str(episode.id),
            "project_draft_id": str(draft.id) if draft is not None else None,
            "draft_created": draft is not None,
            "task_title": task_title,
            "capture_mode": "single_task",
        },
    )


def _handle_wsjf(content: str) -> ChatResponse:
    """Extract WSJF parameters and calculate the score."""
    numbers = [int(n) for n in re.findall(r"\b(\d{1,2})\b", content)]

    if len(numbers) < 4:
        return ChatResponse(
            content=(
                "To calculate WSJF, I need 4 values (each 1-10): "
                "business value, time criticality, risk reduction, and job size."
            ),
            agent="project",
            metadata={"error": "insufficient_wsjf_params"},
        )

    bv, tc, rr, js = numbers[0], numbers[1], numbers[2], numbers[3]
    try:
        score = calculate_wsjf(bv, tc, rr, js)
    except ValueError as exc:
        return ChatResponse(
            content=f"Invalid WSJF parameters: {exc}",
            agent="project",
            metadata={"error": "invalid_wsjf_params"},
        )

    cost_of_delay = bv + tc + rr
    if score >= 5:
        priority_word = "high priority"
    elif score >= 2:
        priority_word = "middle of the stack"
    else:
        priority_word = "lower priority"
    return ChatResponse(
        content=(
            f"WSJF score is {score} — {priority_word}. "
            f"Cost of delay is {cost_of_delay} (BV {bv} + TC {tc} + RR {rr}) vs job size {js}."
        ),
        agent="project",
        metadata={
            "wsjf_score": score,
            "business_value": bv,
            "time_criticality": tc,
            "risk_reduction": rr,
            "job_size": js,
        },
    )
