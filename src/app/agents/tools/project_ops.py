"""Project management tool operations for agents."""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.domain.constants import TaskStatus
from src.app.persistence.repositories.projects import (
    get_project_tasks,
    get_wip_count,
    update_task_status,
)

logger = structlog.get_logger()

WIP_LIMIT = 3  # Default work-in-progress limit


async def start_task(
    session: AsyncSession,
    task_id: uuid.UUID,
) -> dict:
    """Start a task — enforces WIP limit."""
    wip = await get_wip_count(session)
    if wip >= WIP_LIMIT:
        return {
            "status": "blocked",
            "message": f"WIP limit reached ({wip}/{WIP_LIMIT}). "
            "Finish or park a task before starting a new one.",
        }

    await update_task_status(session, task_id, TaskStatus.IN_PROGRESS)
    return {"status": "ok", "message": "Task started"}


async def generate_standup(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> dict:
    """Generate a standup report from recent task transitions."""
    tasks = await get_project_tasks(session, project_id)

    in_progress = [t for t in tasks if t["status"] == TaskStatus.IN_PROGRESS]
    done_recent = [t for t in tasks if t["status"] == TaskStatus.DONE]
    blocked = [t for t in tasks if t["status"] == TaskStatus.BLOCKED]

    return {
        "in_progress": [t["title"] for t in in_progress],
        "completed": [t["title"] for t in done_recent[:5]],
        "blocked": [t["title"] for t in blocked],
        "wip_count": len(in_progress),
        "wip_limit": WIP_LIMIT,
    }
