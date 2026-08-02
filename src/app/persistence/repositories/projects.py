"""Project management repository -- projects, drafts, milestones, tasks, dependencies."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.domain.constants import ProjectStatus, TaskStatus
from src.app.persistence.models import (
    Epic,
    Milestone,
    Project,
    ProjectDraft,
    Task,
    TaskDependency,
)

logger = structlog.get_logger()


async def _session_add(session: AsyncSession, instance: object) -> None:
    result = session.add(instance)
    if inspect.isawaitable(result):
        await result


async def create_project(
    session: AsyncSession,
    title: str,
    description: str | None = None,
    deadline: datetime | None = None,
    appetite: str | None = None,
) -> Project:
    """Create a new project. Returns the ORM model instance."""
    if deadline is not None and not isinstance(deadline, datetime):
        msg = f"deadline must be a datetime, got {type(deadline).__name__}"
        raise TypeError(msg)
    project = Project(
        title=title,
        description=description,
        status=ProjectStatus.PLANNING,
        appetite=appetite,
        deadline=deadline,
    )
    await _session_add(session, project)
    await session.flush()
    logger.info("project_created", project_id=str(project.id))
    return project


async def create_epic(
    session: AsyncSession,
    project_id: uuid.UUID,
    title: str,
    description: str | None = None,
    order: int = 0,
) -> Epic:
    """Create an epic under a project. Returns the ORM model instance."""
    epic = Epic(
        project_id=project_id,
        title=title,
        description=description,
        sort_order=order,
    )
    await _session_add(session, epic)
    await session.flush()
    logger.info("epic_created", epic_id=str(epic.id), project_id=str(project_id))
    return epic


async def create_milestone(
    session: AsyncSession,
    epic_id: uuid.UUID,
    title: str,
    success_criteria: str | None = None,
    order: int = 0,
) -> Milestone:
    """Create a milestone under an epic. Returns the ORM model instance."""
    milestone = Milestone(
        epic_id=epic_id,
        title=title,
        success_criteria=success_criteria,
        sort_order=order,
    )
    await _session_add(session, milestone)
    await session.flush()
    logger.info("milestone_created", milestone_id=str(milestone.id), epic_id=str(epic_id))
    return milestone


async def create_task(
    session: AsyncSession,
    milestone_id: uuid.UUID,
    title: str,
    description: str | None = None,
    estimate_hours: float | None = None,
    complexity: str | None = None,
    context_tags: list[str] | None = None,
    blocked_reason: str | None = None,
    status: str | None = None,
    sort_order: int = 0,
) -> Task:
    """Create a task under a milestone. Returns the ORM model instance."""
    task = Task(
        milestone_id=milestone_id,
        title=title,
        description=description,
        estimate_hours=estimate_hours,
        complexity=complexity,
        context_tags=context_tags,
        blocked_reason=blocked_reason,
        status=status or TaskStatus.BACKLOG,
        sort_order=sort_order,
    )
    await _session_add(session, task)
    await session.flush()
    logger.info("task_created", task_id=str(task.id), milestone_id=str(milestone_id))
    return task


async def create_task_dependency(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    depends_on_task_id: uuid.UUID,
) -> TaskDependency:
    """Create a directional dependency edge between tasks."""
    existing = await session.execute(
        select(TaskDependency).where(
            TaskDependency.task_id == task_id,
            TaskDependency.depends_on_task_id == depends_on_task_id,
        )
    )
    dependency = existing.scalar_one_or_none()
    if dependency is not None:
        return dependency

    dependency = TaskDependency(
        task_id=task_id,
        depends_on_task_id=depends_on_task_id,
    )
    await _session_add(session, dependency)
    await session.flush()
    logger.info(
        "task_dependency_created",
        task_id=str(task_id),
        depends_on_task_id=str(depends_on_task_id),
    )
    return dependency


async def replace_task_dependencies(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    dependency_task_ids: list[uuid.UUID],
) -> None:
    """Replace all dependency edges for one task."""
    await session.execute(delete(TaskDependency).where(TaskDependency.task_id == task_id))
    unique_ids: list[uuid.UUID] = []
    for dependency_task_id in dependency_task_ids:
        if dependency_task_id == task_id or dependency_task_id in unique_ids:
            continue
        unique_ids.append(dependency_task_id)
        await create_task_dependency(
            session,
            task_id=task_id,
            depends_on_task_id=dependency_task_id,
        )


async def update_task_status(
    session: AsyncSession,
    task_id: uuid.UUID,
    status: str,
) -> Task:
    """Update task status. Valid: backlog, ready, in_progress, review, done, blocked."""
    valid_statuses = {status_value.value for status_value in TaskStatus}
    if status not in valid_statuses:
        msg = f"Invalid task status: {status}. Valid: {valid_statuses}"
        raise ValueError(msg)

    values: dict[str, Any] = {
        "status": status,
        "updated_at": func.now(),
    }
    if status == TaskStatus.IN_PROGRESS:
        values["started_at"] = func.coalesce(Task.started_at, func.now())
    elif status == TaskStatus.DONE:
        values["completed_at"] = func.now()

    stmt = update(Task).where(Task.id == task_id).values(**values).returning(Task)
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        msg = f"Task not found: {task_id}"
        raise ValueError(msg)
    return task


async def update_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    estimate_hours: float | None = None,
    actual_hours: float | None = None,
    wsjf_score: float | None = None,
    context_tags: list[str] | None = None,
    blocked_reason: str | None = None,
) -> Task:
    """Update a task and return the fresh ORM object."""
    updates: dict[str, Any] = {"updated_at": func.now()}
    if title is not None:
        updates["title"] = title
    if description is not None:
        updates["description"] = description
    if status is not None:
        valid_statuses = {status_value.value for status_value in TaskStatus}
        if status not in valid_statuses:
            msg = f"Invalid task status: {status}. Valid: {valid_statuses}"
            raise ValueError(msg)
        updates["status"] = status
        if status == TaskStatus.IN_PROGRESS:
            updates["started_at"] = func.coalesce(Task.started_at, func.now())
        elif status == TaskStatus.DONE:
            updates["completed_at"] = func.now()
    if estimate_hours is not None:
        updates["estimate_hours"] = estimate_hours
    if actual_hours is not None:
        updates["actual_hours"] = actual_hours
    if wsjf_score is not None:
        updates["wsjf_score"] = wsjf_score
    if context_tags is not None:
        updates["context_tags"] = context_tags
    if blocked_reason is not None:
        updates["blocked_reason"] = blocked_reason

    stmt = update(Task).where(Task.id == task_id).values(**updates).returning(Task)
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        msg = f"Task not found: {task_id}"
        raise ValueError(msg)
    logger.info("task_updated", task_id=str(task_id), fields=sorted(updates.keys()))
    return task


async def get_wip_count(session: AsyncSession) -> int:
    """Get count of tasks currently in progress."""
    stmt = select(func.count()).select_from(Task).where(Task.status == TaskStatus.IN_PROGRESS)
    result = await session.execute(stmt)
    return result.scalar_one()


async def get_project_tasks(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> list[dict]:
    """Get all tasks for a project with milestone context."""
    result = await session.execute(
        text("""
            SELECT t.id, t.title, t.status, t.estimate_hours, t.actual_hours,
                   t.wsjf_score, t.context_tags, t.complexity, t.blocked_reason,
                   m.title AS milestone_title
            FROM tasks t
            JOIN milestones m ON t.milestone_id = m.id
            JOIN epics e ON m.epic_id = e.id
            WHERE e.project_id = :project_id
            ORDER BY t.wsjf_score DESC NULLS LAST, t.sort_order
        """),
        {"project_id": project_id},
    )
    return [dict(row) for row in result.mappings().all()]


async def create_project_draft(
    session: AsyncSession,
    *,
    user_id: str,
    title: str,
    source_message: str | None,
    breakdown: dict[str, Any],
    status: str = "draft",
) -> ProjectDraft:
    """Persist a project draft derived from a chat breakdown."""
    draft = ProjectDraft(
        user_id=user_id,
        title=title,
        source_message=source_message,
        status=status,
        breakdown=breakdown,
    )
    await _session_add(session, draft)
    await session.flush()
    logger.info("project_draft_created", draft_id=str(draft.id), user_id=str(user_id))
    return draft


async def get_project_draft(
    session: AsyncSession,
    draft_id: uuid.UUID,
) -> ProjectDraft | None:
    """Get a single project draft."""
    return await session.get(ProjectDraft, draft_id)


async def list_project_drafts(
    session: AsyncSession,
    *,
    user_id: str | None = None,
    status: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[ProjectDraft], int]:
    """List project drafts with simple filtering."""
    stmt = select(ProjectDraft)
    if user_id is not None:
        stmt = stmt.where(ProjectDraft.user_id == user_id)
    if status is not None:
        stmt = stmt.where(ProjectDraft.status == status)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    result = await session.execute(
        stmt.order_by(ProjectDraft.updated_at.desc(), ProjectDraft.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), total


def _coerce_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _task_key(milestone_title: str, task_title: str) -> str:
    return f"{milestone_title.strip().casefold()}::{task_title.strip().casefold()}"


def _validated_milestones(
    value: object,
    *,
    draft_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Validate the nested list/object shape before creating live records."""
    if not isinstance(value, list) or not value:
        msg = f"Project draft {draft_id} has no milestones to apply."
        raise ValueError(msg)

    milestones: list[dict[str, Any]] = []
    for milestone_index, milestone in enumerate(value):
        if not isinstance(milestone, dict):
            msg = f"Project draft {draft_id} milestone {milestone_index + 1} must be an object."
            raise ValueError(msg)
        validated_milestone: dict[str, Any] = {}
        for key, field_value in milestone.items():
            if not isinstance(key, str):
                msg = (
                    f"Project draft {draft_id} milestone {milestone_index + 1} "
                    "contains a non-string field name."
                )
                raise ValueError(msg)
            validated_milestone[key] = field_value

        tasks = validated_milestone.get("tasks", [])
        if tasks is None:
            tasks = []
        if not isinstance(tasks, list):
            msg = f"Project draft {draft_id} milestone {milestone_index + 1} tasks must be a list."
            raise ValueError(msg)
        validated_tasks: list[dict[str, Any]] = []
        for task_index, task in enumerate(tasks):
            if not isinstance(task, dict):
                msg = (
                    f"Project draft {draft_id} milestone {milestone_index + 1} "
                    f"task {task_index + 1} must be an object."
                )
                raise ValueError(msg)
            validated_task: dict[str, Any] = {}
            for key, field_value in task.items():
                if not isinstance(key, str):
                    msg = (
                        f"Project draft {draft_id} milestone {milestone_index + 1} "
                        f"task {task_index + 1} contains a non-string field name."
                    )
                    raise ValueError(msg)
                validated_task[key] = field_value
            validated_tasks.append(validated_task)
        validated_milestone["tasks"] = validated_tasks
        milestones.append(validated_milestone)
    return milestones


async def apply_project_draft(
    session: AsyncSession,
    *,
    draft: ProjectDraft,
) -> Project:
    """Create live project records from a draft in one transaction."""
    if draft.applied_project_id is not None:
        project = await session.get(Project, draft.applied_project_id)
        if project is not None:
            return project

    breakdown = draft.breakdown or {}
    milestones = _validated_milestones(
        breakdown.get("milestones"),
        draft_id=draft.id,
    )

    project_summary = str(breakdown.get("project_summary") or draft.source_message or "").strip()
    critical_path = _coerce_str_list(breakdown.get("critical_path"))
    risks = _coerce_str_list(breakdown.get("risks"))
    total_hours = breakdown.get("total_estimated_hours")

    summary_parts = [project_summary] if project_summary else []
    if critical_path:
        summary_parts.append(f"Critical path: {', '.join(critical_path)}.")
    if risks:
        summary_parts.append(f"Risks: {', '.join(risks)}.")
    if total_hours is not None:
        summary_parts.append(f"Estimated effort: {total_hours}h.")

    project = await create_project(
        session,
        title=draft.title,
        description=" ".join(part for part in summary_parts if part).strip() or None,
    )
    epic = await create_epic(
        session,
        project_id=project.id,
        title="Execution Plan",
        description=project_summary or None,
        order=0,
    )

    task_ids_by_title: dict[str, uuid.UUID] = {}
    task_ids_by_key: dict[str, uuid.UUID] = {}
    unresolved_dependencies: dict[uuid.UUID, list[str]] = {}

    for milestone_index, milestone_data in enumerate(milestones):
        milestone_title = str(
            milestone_data.get("title") or f"Milestone {milestone_index + 1}"
        ).strip()
        success_criteria = _coerce_str_list(milestone_data.get("success_criteria"))
        milestone = await create_milestone(
            session,
            epic_id=epic.id,
            title=milestone_title,
            success_criteria="\n".join(success_criteria) if success_criteria else None,
            order=milestone_index,
        )
        tasks = milestone_data.get("tasks") or []
        for task_index, task_data in enumerate(tasks):
            task_title = str(task_data.get("title") or f"Task {task_index + 1}").strip()
            task_risks = _coerce_str_list(task_data.get("risks"))
            dependency_titles = _coerce_str_list(task_data.get("depends_on"))
            blocked_reason = None
            if task_risks:
                blocked_reason = "; ".join(task_risks)
            elif dependency_titles:
                blocked_reason = f"Waiting on: {', '.join(dependency_titles)}"
            task = await create_task(
                session,
                milestone_id=milestone.id,
                title=task_title,
                description=str(task_data.get("description") or "").strip() or None,
                estimate_hours=task_data.get("estimate_hours"),
                complexity=str(task_data.get("complexity") or "").strip() or None,
                context_tags=_coerce_str_list(task_data.get("context_tags")) or None,
                blocked_reason=blocked_reason,
                status=(
                    TaskStatus.BLOCKED
                    if dependency_titles and blocked_reason
                    else TaskStatus.BACKLOG
                ),
                sort_order=task_index,
            )
            task_ids_by_title.setdefault(task_title.casefold(), task.id)
            task_ids_by_key[_task_key(milestone_title, task_title)] = task.id
            if dependency_titles:
                unresolved_dependencies[task.id] = dependency_titles

    for task_id, dependency_titles in unresolved_dependencies.items():
        matched_dependencies: list[uuid.UUID] = []
        unmatched_dependencies: list[str] = []
        for dependency_title in dependency_titles:
            dependency_key = dependency_title.casefold()
            matched_task_id = task_ids_by_title.get(dependency_key)
            if matched_task_id is None:
                unmatched_dependencies.append(dependency_title)
                continue
            matched_dependencies.append(matched_task_id)
        if matched_dependencies:
            await replace_task_dependencies(
                session,
                task_id=task_id,
                dependency_task_ids=matched_dependencies,
            )
        task = await session.get(Task, task_id)
        if task is not None:
            if unmatched_dependencies:
                task.blocked_reason = (
                    f"Blocked on external work: {', '.join(unmatched_dependencies)}"
                )
                task.status = TaskStatus.BLOCKED
            elif matched_dependencies:
                task.blocked_reason = (
                    f"Waiting on {len(matched_dependencies)} dependency"
                    f"{'' if len(matched_dependencies) == 1 else 'ies'}."
                )
                task.status = TaskStatus.BLOCKED

    draft.status = "applied"
    draft.applied_project_id = project.id
    draft.updated_at = datetime.now(UTC)
    await session.flush()
    logger.info(
        "project_draft_applied",
        draft_id=str(draft.id),
        project_id=str(project.id),
    )
    return project
