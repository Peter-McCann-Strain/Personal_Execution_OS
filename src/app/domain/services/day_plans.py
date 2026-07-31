"""Daily plan artifacts and planning-session helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import structlog

from src.app.domain.models import ArtifactRecord, DayPlanArtifact, PendingPlanningSession
from src.app.persistence.repositories.runtime_records import (
    create_artifact_record,
    list_recent_artifacts_for_user,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.app.config import Settings

_DAY_PLAN_ARTIFACT_TYPE = "day_plan"
_MORNING_SESSION_IDLE_MINUTES = 90
_EVENING_SESSION_IDLE_MINUTES = 180
logger = structlog.get_logger()


@dataclass(slots=True)
class StoredDayPlan:
    """The latest persisted day-plan artifact for a local day."""

    artifact_id: str
    created_at: datetime | None
    plan: DayPlanArtifact


def planning_owner_user_id(settings: Settings) -> str:
    """Return the canonical user id used for daily planning state."""
    allowed_user_ids = getattr(settings, "allowed_user_ids", [])
    if isinstance(allowed_user_ids, list) and allowed_user_ids:
        return str(allowed_user_ids[0])
    phone_number = getattr(settings, "user_phone_number", "")
    if isinstance(phone_number, str) and phone_number.strip():
        return phone_number.strip()
    return "owner"


def planning_source_date(settings: Settings, *, now_utc: datetime | None = None) -> str:
    """Return the current local-day key used for planning artifacts."""
    now = now_utc or datetime.now(UTC)
    tz_name = getattr(settings, "user_timezone", "Europe/London")
    if not isinstance(tz_name, str) or not tz_name.strip():
        tz_name = "Europe/London"
    return now.astimezone(ZoneInfo(tz_name)).date().isoformat()


def planning_session_is_active(
    planning_session: PendingPlanningSession | None,
    *,
    settings: Settings,
    now_utc: datetime | None = None,
) -> bool:
    """Return True when a stored planning session should still intercept replies."""
    if planning_session is None:
        return False

    now = now_utc or datetime.now(UTC)
    if planning_session.expires_at <= now:
        return False
    return planning_session.source_date == planning_source_date(settings, now_utc=now)


def build_morning_planning_session(
    *,
    settings: Settings,
    now_utc: datetime | None = None,
) -> PendingPlanningSession:
    """Return a fresh morning planning session invitation."""
    now = now_utc or datetime.now(UTC)
    return PendingPlanningSession(
        session_type="morning_plan",
        source_date=planning_source_date(settings, now_utc=now),
        stage="invited",
        expires_at=now + timedelta(minutes=_MORNING_SESSION_IDLE_MINUTES),
        last_active_at=now,
    )


def build_evening_review_session(
    *,
    settings: Settings,
    plan_artifact_id: str,
    unresolved_tasks: list[str],
    now_utc: datetime | None = None,
) -> PendingPlanningSession:
    """Return an evening closeout session for unfinished planned work."""
    now = now_utc or datetime.now(UTC)
    return PendingPlanningSession(
        session_type="evening_review",
        source_date=planning_source_date(settings, now_utc=now),
        stage="collecting",
        expires_at=now + timedelta(minutes=_EVENING_SESSION_IDLE_MINUTES),
        last_active_at=now,
        plan_artifact_id=plan_artifact_id,
        unresolved_tasks=list(unresolved_tasks),
    )


def renew_planning_session(
    planning_session: PendingPlanningSession,
    *,
    settings: Settings,
    stage: str | None = None,
    draft_plan: DayPlanArtifact | None = None,
    unresolved_tasks: list[str] | None = None,
    now_utc: datetime | None = None,
) -> PendingPlanningSession:
    """Refresh expiry and optional fields after a planning turn."""
    now = now_utc or datetime.now(UTC)
    idle_minutes = (
        _EVENING_SESSION_IDLE_MINUTES
        if planning_session.session_type == "evening_review"
        else _MORNING_SESSION_IDLE_MINUTES
    )
    return planning_session.model_copy(
        update={
            "stage": stage or planning_session.stage,
            "draft_plan": draft_plan if draft_plan is not None else planning_session.draft_plan,
            "unresolved_tasks": (
                list(unresolved_tasks)
                if unresolved_tasks is not None
                else list(planning_session.unresolved_tasks)
            ),
            "last_active_at": now,
            "expires_at": now + timedelta(minutes=idle_minutes),
            "source_date": planning_source_date(settings, now_utc=now),
        }
    )


async def load_latest_day_plan(
    session: AsyncSession,
    *,
    user_id: str,
    source_date: str,
    limit: int = 12,
) -> StoredDayPlan | None:
    """Return the latest day-plan artifact for the given local day."""
    try:
        artifacts = await list_recent_artifacts_for_user(
            session,
            user_id=user_id,
            limit=limit,
            artifact_types=[_DAY_PLAN_ARTIFACT_TYPE],
        )
    except Exception:
        logger.warning(
            "day_plan_lookup_failed",
            user_id=user_id,
            source_date=source_date,
            exc_info=True,
        )
        return None
    for artifact in artifacts:
        payload = artifact.payload if isinstance(artifact.payload, dict) else None
        if not isinstance(payload, dict):
            continue
        try:
            plan = DayPlanArtifact.model_validate(payload)
        except Exception as exc:
            logger.debug("day_plan_payload_invalid", error=str(exc))
            continue
        if plan.source_date != source_date:
            continue
        return StoredDayPlan(
            artifact_id=str(artifact.id),
            created_at=getattr(artifact, "created_at", None),
            plan=plan,
        )
    return None


async def load_carry_over_tasks(
    session: AsyncSession,
    *,
    user_id: str,
    source_date: str,
    limit: int = 20,
) -> list[str]:
    """Return unresolved tasks explicitly moved into today or backlog previously."""
    try:
        artifacts = await list_recent_artifacts_for_user(
            session,
            user_id=user_id,
            limit=limit,
            artifact_types=[_DAY_PLAN_ARTIFACT_TYPE],
        )
    except Exception:
        logger.warning(
            "day_plan_carry_over_lookup_failed",
            user_id=user_id,
            source_date=source_date,
            exc_info=True,
        )
        return []
    carry_over: list[str] = []
    seen: set[str] = set()

    for artifact in artifacts:
        payload = artifact.payload if isinstance(artifact.payload, dict) else None
        if not isinstance(payload, dict):
            continue
        try:
            plan = DayPlanArtifact.model_validate(payload)
        except Exception as exc:
            logger.debug("day_plan_carry_over_payload_invalid", error=str(exc))
            continue
        if plan.source_date == source_date:
            continue
        for task in plan.tasks:
            should_include = task.status == "moved_to_backlog" or (
                task.status == "moved_to_day" and task.rescheduled_for == source_date
            )
            if not should_include:
                continue
            key = task.title.strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            carry_over.append(task.title.strip())
    return carry_over[:6]


async def persist_day_plan_artifact(
    session: AsyncSession,
    *,
    user_id: str,
    plan: DayPlanArtifact,
    source_id: str | None = None,
    trace_id: str | None = None,
    workflow_id: str | None = None,
) -> str:
    """Persist one day-plan artifact and return its record id."""
    summary = build_day_plan_summary(plan)
    record = await create_artifact_record(
        session,
        user_id=user_id,
        artifact=ArtifactRecord(
            artifact_type=_DAY_PLAN_ARTIFACT_TYPE,
            summary=summary,
            source_id=source_id,
            trace_id=trace_id,
            workflow_id=workflow_id,
            payload=plan.model_dump(mode="json"),
        ),
    )
    return str(record.id)


def build_day_plan_summary(plan: DayPlanArtifact) -> str:
    """Return a compact single-line summary for one plan artifact."""
    task_titles = [task.title.strip() for task in plan.tasks if task.title.strip()]
    if task_titles:
        preview = "; ".join(task_titles[:3])
        if len(task_titles) > 3:
            preview += "; ..."
        return f"Daily plan for {plan.source_date}: {preview}"
    if plan.plan_summary.strip():
        return f"Daily plan for {plan.source_date}: {plan.plan_summary.strip()}"
    return f"Daily plan for {plan.source_date}"


def day_plan_completion_status(plan: DayPlanArtifact) -> tuple[list[str], list[str]]:
    """Return completed and unresolved task titles from a stored plan."""
    completed: list[str] = []
    unresolved: list[str] = []
    for task in plan.tasks:
        title = task.title.strip()
        if not title:
            continue
        if task.status == "completed":
            completed.append(title)
        elif task.status in {"moved_to_day", "moved_to_backlog", "cancelled"}:
            continue
        else:
            unresolved.append(title)
    return completed, unresolved


def build_morning_plan_prompt(
    *,
    carry_over_tasks: list[str],
) -> str:
    """Return the morning invite when no concrete plan exists yet."""
    lines = [
        "",
        "DAY PLAN:",
        "You do not have a plan locked in for today yet.",
    ]
    if carry_over_tasks:
        lines.append("Carry-over or backlog to consider: " + "; ".join(carry_over_tasks[:4]))
    lines.append(
        "Reply with what you want to get done and I will help narrow it into a concrete plan."
    )
    return "\n".join(lines)


def build_evening_closeout_message(plan: DayPlanArtifact) -> str:
    """Return the structured evening follow-up for unfinished plan items."""
    completed, unresolved = day_plan_completion_status(plan)
    lines = [
        "Close the loop on today's plan.",
    ]
    if completed:
        lines.append("Already closed: " + "; ".join(completed[:3]))
    if unresolved:
        lines.append("Still open: " + "; ".join(unresolved[:5]))
        lines.append(
            "Reply in plain English with what is done, what should move to "
            "another day, and what should go back to backlog."
        )
    else:
        lines.append(
            "Everything on today's plan looks closed. Reply if anything still needs moving."
        )
    return "\n".join(lines)


def build_day_plan_section(plan: DayPlanArtifact) -> str:
    """Render today's plan for morning briefing or fallback summaries."""
    lines = ["TODAY'S PLAN:"]
    if plan.plan_summary.strip():
        lines.append(f"  {plan.plan_summary.strip()}")
    for task in plan.tasks[:5]:
        title = task.title.strip()
        if title:
            lines.append(f"  - {title}")
    return "\n".join(lines)
