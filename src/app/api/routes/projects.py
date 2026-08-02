"""Projects API routes — projects, drafts, dependencies, and task updates."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.api.transactions import session_transaction
from src.app.config import get_settings
from src.app.core.exceptions import NotFoundError
from src.app.persistence.models import Epic, Milestone, Project, ProjectDraft, Task, TaskDependency
from src.app.persistence.repositories.projects import (
    apply_project_draft as repo_apply_project_draft,
)
from src.app.persistence.repositories.projects import create_epic as repo_create_epic
from src.app.persistence.repositories.projects import (
    create_milestone as repo_create_milestone,
)
from src.app.persistence.repositories.projects import create_project, replace_task_dependencies
from src.app.persistence.repositories.projects import get_project_draft as repo_get_project_draft
from src.app.persistence.repositories.projects import (
    list_project_drafts as repo_list_project_drafts,
)
from src.app.persistence.repositories.projects import update_task as repo_update_task

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])

_TASK_STATUS_ALIASES = {
    "in-progress": "in_progress",
    "completed": "done",
}


def _require_project_drafts_enabled() -> None:
    if not bool(getattr(get_settings(), "project_draft_runtime_enabled", True)):
        raise NotFoundError("Project drafts are not enabled.")


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _list_of_strings(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _iso_datetime_value(value: object) -> str | None:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            iso_value = isoformat()
        except TypeError:
            return None
        return iso_value if isinstance(iso_value, str) else None
    return None


class TaskDTO(BaseModel):
    """Task DTO matching frontend Task type."""

    id: str
    milestone_id: str
    title: str
    description: str | None
    status: str
    estimate_hours: float | None
    actual_hours: float | None
    wsjf_score: float | None
    complexity: str | None
    context_tags: list[str]
    blocked_reason: str | None
    dependency_task_ids: list[str]
    sort_order: int
    started_at: str | None
    completed_at: str | None
    created_at: str


class MilestoneDTO(BaseModel):
    """Milestone DTO matching frontend Milestone type."""

    id: str
    epic_id: str
    title: str
    success_criteria: str | None
    sort_order: int
    tasks: list[TaskDTO]
    created_at: str


class EpicDTO(BaseModel):
    """Epic DTO matching frontend Epic type."""

    id: str
    project_id: str
    title: str
    description: str | None
    sort_order: int
    milestones: list[MilestoneDTO]
    created_at: str


class ProjectDTO(BaseModel):
    """Full project DTO with nested hierarchy."""

    id: str
    title: str
    description: str | None
    status: str
    appetite: str | None
    deadline: str | None
    epics: list[EpicDTO]
    created_at: str
    updated_at: str


class ProjectListDTO(BaseModel):
    """Flat project DTO for list view."""

    id: str
    title: str
    description: str | None
    status: str
    appetite: str | None
    deadline: str | None
    epics: list[EpicDTO]
    created_at: str
    updated_at: str


class ProjectDraftDTO(BaseModel):
    """Project draft summary for operator review."""

    id: str
    user_id: str
    title: str
    source_message: str | None
    status: str
    project_summary: str | None
    total_estimated_hours: float | None
    milestone_count: int
    critical_path: list[str]
    risks: list[str]
    applied_project_id: str | None
    breakdown: dict[str, Any]
    created_at: str
    updated_at: str


class CreateProjectBody(BaseModel):
    """Body for POST /projects."""

    title: str
    description: str | None = None
    appetite: str | None = None
    deadline: str | None = None

    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                datetime.fromisoformat(value)
            except (TypeError, ValueError) as exc:
                msg = f"Invalid ISO 8601 datetime: {value!r}"
                raise ValueError(msg) from exc
        return value


class CreateEpicBody(BaseModel):
    """Body for POST /projects/{project_id}/epics."""

    title: str
    description: str | None = None
    order: int = 0


class CreateMilestoneBody(BaseModel):
    """Body for POST /epics/{epic_id}/milestones."""

    title: str
    success_criteria: str | None = None
    order: int = 0


class UpdateTaskBody(BaseModel):
    """Body for PATCH /tasks/{task_id}."""

    title: str | None = None
    description: str | None = None
    status: str | None = None
    estimate_hours: float | None = None
    actual_hours: float | None = None
    wsjf_score: float | None = None
    context_tags: list[str] | None = None
    blocked_reason: str | None = None
    dependency_task_ids: list[str] | None = None


def _draft_to_dto(draft: ProjectDraft) -> ProjectDraftDTO:
    breakdown = draft.breakdown or {}
    milestones = breakdown.get("milestones")
    milestone_count = len(milestones) if isinstance(milestones, list) else 0
    critical_path = breakdown.get("critical_path")
    risks = breakdown.get("risks")
    return ProjectDraftDTO(
        id=str(draft.id),
        user_id=draft.user_id,
        title=draft.title,
        source_message=draft.source_message,
        status=draft.status,
        project_summary=breakdown.get("project_summary"),
        total_estimated_hours=breakdown.get("total_estimated_hours"),
        milestone_count=milestone_count,
        critical_path=(
            [str(item) for item in critical_path] if isinstance(critical_path, list) else []
        ),
        risks=[str(item) for item in risks] if isinstance(risks, list) else [],
        applied_project_id=str(draft.applied_project_id) if draft.applied_project_id else None,
        breakdown=breakdown,
        created_at=draft.created_at.isoformat(),
        updated_at=draft.updated_at.isoformat(),
    )


def _task_to_dto(task: Task, dependency_task_ids: list[uuid.UUID] | None = None) -> TaskDTO:
    return TaskDTO(
        id=str(task.id),
        milestone_id=str(task.milestone_id),
        title=task.title,
        description=_optional_str(task.description),
        status=str(task.status),
        estimate_hours=_optional_float(task.estimate_hours),
        actual_hours=_optional_float(task.actual_hours),
        wsjf_score=_optional_float(task.wsjf_score),
        complexity=_optional_str(task.complexity),
        context_tags=_list_of_strings(task.context_tags),
        blocked_reason=_optional_str(getattr(task, "blocked_reason", None)),
        dependency_task_ids=[str(item) for item in (dependency_task_ids or [])],
        sort_order=_optional_int(task.sort_order) or 0,
        started_at=_iso_datetime_value(task.started_at),
        completed_at=_iso_datetime_value(task.completed_at),
        created_at=_iso_datetime_value(task.created_at) or datetime.now().isoformat(),
    )


def _milestone_to_dto(
    milestone: Milestone,
    tasks: list[Task],
    dependency_map: dict[uuid.UUID, list[uuid.UUID]] | None = None,
) -> MilestoneDTO:
    resolved_dependency_map = dependency_map or {}
    return MilestoneDTO(
        id=str(milestone.id),
        epic_id=str(milestone.epic_id),
        title=milestone.title,
        success_criteria=milestone.success_criteria,
        sort_order=milestone.sort_order,
        tasks=[_task_to_dto(task, resolved_dependency_map.get(task.id, [])) for task in tasks],
        created_at=milestone.created_at.isoformat(),
    )


def _epic_to_dto(
    epic: Epic,
    milestones: list[Milestone],
    tasks_by_milestone: dict[uuid.UUID, list[Task]],
    dependency_map: dict[uuid.UUID, list[uuid.UUID]] | None = None,
) -> EpicDTO:
    resolved_dependency_map = dependency_map or {}
    return EpicDTO(
        id=str(epic.id),
        project_id=str(epic.project_id),
        title=epic.title,
        description=epic.description,
        sort_order=epic.sort_order,
        milestones=[
            _milestone_to_dto(
                milestone,
                tasks_by_milestone.get(milestone.id, []),
                resolved_dependency_map,
            )
            for milestone in milestones
        ],
        created_at=epic.created_at.isoformat(),
    )


def _project_to_dto(project: Project, epics_data: list[EpicDTO] | None = None) -> ProjectDTO:
    return ProjectDTO(
        id=str(project.id),
        title=project.title,
        description=project.description,
        status=project.status,
        appetite=project.appetite,
        deadline=project.deadline.isoformat() if project.deadline else None,
        epics=epics_data or [],
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
    )


def _project_to_list_dto(project: Project) -> ProjectListDTO:
    return ProjectListDTO(
        id=str(project.id),
        title=project.title,
        description=project.description,
        status=project.status,
        appetite=project.appetite,
        deadline=project.deadline.isoformat() if project.deadline else None,
        epics=[],
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
    )


async def _load_dependency_map(
    session: AsyncSession,
    task_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[uuid.UUID]]:
    if not task_ids:
        return {}
    try:
        result = await session.execute(
            select(TaskDependency).where(TaskDependency.task_id.in_(task_ids))
        )
    except Exception:
        return {}
    mapping: dict[uuid.UUID, list[uuid.UUID]] = {}
    dependencies = result.scalars().all()
    for dependency in dependencies:
        mapping.setdefault(dependency.task_id, []).append(dependency.depends_on_task_id)
    return mapping


async def _load_project_tree(session: AsyncSession, project: Project) -> ProjectDTO:
    epics_result = await session.execute(
        select(Epic).where(Epic.project_id == project.id).order_by(Epic.sort_order, Epic.created_at)
    )
    epics = list(epics_result.scalars().all())
    if not epics:
        return _project_to_dto(project, [])

    milestones_result = await session.execute(
        select(Milestone)
        .where(Milestone.epic_id.in_([epic.id for epic in epics]))
        .order_by(Milestone.sort_order, Milestone.created_at)
    )
    milestones = list(milestones_result.scalars().all())

    tasks_by_milestone: dict[uuid.UUID, list[Task]] = {}
    task_ids: list[uuid.UUID] = []
    if milestones:
        tasks_result = await session.execute(
            select(Task)
            .where(Task.milestone_id.in_([milestone.id for milestone in milestones]))
            .order_by(Task.sort_order, Task.created_at)
        )
        for task in tasks_result.scalars().all():
            tasks_by_milestone.setdefault(task.milestone_id, []).append(task)
            task_ids.append(task.id)
    dependency_map = await _load_dependency_map(session, task_ids)

    milestones_by_epic: dict[uuid.UUID, list[Milestone]] = {}
    for milestone in milestones:
        milestones_by_epic.setdefault(milestone.epic_id, []).append(milestone)

    epic_dtos = [
        _epic_to_dto(
            epic,
            milestones_by_epic.get(epic.id, []),
            tasks_by_milestone,
            dependency_map,
        )
        for epic in epics
    ]
    return _project_to_dto(project, epic_dtos)


@router.get("/projects", response_model=PaginatedResponse[ProjectListDTO])
async def list_projects(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: Literal["deadline", "progress", "created_at", "title"] = Query("created_at"),
    order: Literal["asc", "desc"] = Query("desc"),
    status: str | None = Query(None),
    appetite: str | None = Query(None),
) -> PaginatedResponse[ProjectListDTO]:
    """Paginated projects list with optional filters and sorting."""
    stmt = select(Project).where(Project.deleted_at.is_(None))
    if status is not None:
        stmt = stmt.where(Project.status == status)
    if appetite is not None:
        stmt = stmt.where(Project.appetite == appetite)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    sort_column = getattr(Project, sort, Project.created_at)
    if order == "desc":
        stmt = stmt.order_by(sort_column.desc().nulls_last())
    else:
        stmt = stmt.order_by(sort_column.asc().nulls_last())

    result = await session.execute(stmt.offset(offset).limit(limit))
    projects = list(result.scalars().all())
    return paginate(
        items=[_project_to_list_dto(project) for project in projects],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/project-drafts", response_model=PaginatedResponse[ProjectDraftDTO])
async def list_project_drafts(
    session: AsyncSession = Depends(get_db),
    user_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[ProjectDraftDTO]:
    """List project drafts awaiting review or already applied."""
    _require_project_drafts_enabled()
    drafts, total = await repo_list_project_drafts(
        session,
        user_id=user_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return paginate(
        items=[_draft_to_dto(draft) for draft in drafts],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/project-drafts/{draft_id}/apply", response_model=ProjectDTO)
async def apply_project_draft(
    draft_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> ProjectDTO:
    """Apply a stored project draft into live project records."""
    _require_project_drafts_enabled()
    draft = await repo_get_project_draft(session, draft_id)
    if draft is None:
        raise NotFoundError(f"Project draft not found: {draft_id}")

    async with session_transaction(session):
        project = await repo_apply_project_draft(session, draft=draft)
    await session.refresh(project)
    logger.info("project_draft_applied_via_api", draft_id=str(draft_id), project_id=str(project.id))
    return await _load_project_tree(session, project)


@router.get("/projects/{project_id}", response_model=ProjectDTO)
async def get_project(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> ProjectDTO:
    """Get a single project with its full hierarchy."""
    result = await session.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError(f"Project not found: {project_id}")
    return await _load_project_tree(session, project)


@router.post("/projects", response_model=ProjectDTO, status_code=201)
async def create_project_endpoint(
    body: CreateProjectBody,
    session: AsyncSession = Depends(get_db),
) -> ProjectDTO:
    """Create a new project."""
    deadline_dt = datetime.fromisoformat(body.deadline) if body.deadline else None
    async with session_transaction(session):
        project = await create_project(
            session,
            title=body.title,
            description=body.description,
            appetite=body.appetite,
            deadline=deadline_dt,
        )
    await session.refresh(project)
    logger.info("project_created_via_api", project_id=str(project.id))
    return _project_to_dto(project, [])


@router.post("/projects/{project_id}/epics", response_model=EpicDTO, status_code=201)
async def create_epic_endpoint(
    project_id: uuid.UUID,
    body: CreateEpicBody,
    session: AsyncSession = Depends(get_db),
) -> EpicDTO:
    """Create an epic under a project."""
    result = await session.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError(f"Project not found: {project_id}")
    async with session_transaction(session):
        epic = await repo_create_epic(
            session,
            project_id=project_id,
            title=body.title,
            description=body.description,
            order=body.order,
        )
    await session.refresh(epic)
    logger.info("epic_created_via_api", epic_id=str(epic.id), project_id=str(project_id))
    return _epic_to_dto(epic, [], {}, {})


@router.post("/epics/{epic_id}/milestones", response_model=MilestoneDTO, status_code=201)
async def create_milestone_endpoint(
    epic_id: uuid.UUID,
    body: CreateMilestoneBody,
    session: AsyncSession = Depends(get_db),
) -> MilestoneDTO:
    """Create a milestone under an epic."""
    epic = await session.get(Epic, epic_id)
    if epic is None:
        raise NotFoundError(f"Epic not found: {epic_id}")
    async with session_transaction(session):
        milestone = await repo_create_milestone(
            session,
            epic_id=epic_id,
            title=body.title,
            success_criteria=body.success_criteria,
            order=body.order,
        )
    await session.refresh(milestone)
    logger.info("milestone_created_via_api", milestone_id=str(milestone.id), epic_id=str(epic_id))
    return _milestone_to_dto(milestone, [], {})


@router.patch("/tasks/{task_id}", response_model=TaskDTO)
async def update_task(
    task_id: uuid.UUID,
    body: UpdateTaskBody,
    session: AsyncSession = Depends(get_db),
) -> TaskDTO:
    """Update a task's fields including blockers and dependencies."""
    if await session.get(Task, task_id) is None:
        raise NotFoundError(f"Task not found: {task_id}")

    async with session_transaction(session):
        try:
            normalized_status = (
                _TASK_STATUS_ALIASES.get(body.status, body.status)
                if body.status is not None
                else None
            )
            task = await repo_update_task(
                session,
                task_id,
                title=body.title,
                description=body.description,
                status=normalized_status,
                estimate_hours=body.estimate_hours,
                actual_hours=body.actual_hours,
                wsjf_score=body.wsjf_score,
                context_tags=body.context_tags,
                blocked_reason=body.blocked_reason,
            )
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc

        dependency_ids: list[uuid.UUID] = []
        if body.dependency_task_ids is not None:
            dependency_ids = [uuid.UUID(item) for item in body.dependency_task_ids]
            await replace_task_dependencies(
                session,
                task_id=task_id,
                dependency_task_ids=dependency_ids,
            )
        else:
            dependency_ids = []

    await session.refresh(task)
    logger.info("task_updated_via_api", task_id=str(task_id))
    return _task_to_dto(task, dependency_ids)
