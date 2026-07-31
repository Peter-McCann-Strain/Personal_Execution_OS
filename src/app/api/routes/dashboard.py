"""Dashboard routes — stats cards, briefing, trends, recent activity."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import DATE
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_principal, get_db
from src.app.api.routes.episodes import EpisodeDTO, _episode_to_dto
from src.app.config import get_settings
from src.app.core.async_utils import maybe_await
from src.app.core.exceptions import ConnectorError
from src.app.persistence.models import AgentAction, Episode, Goal, NotificationRecord, Project
from src.app.persistence.repositories.goals import list_goals

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

# Where the user is sent to repair an actionable connector failure.
_RECONNECT_URL = "/connectors/google"

# Per-category fallback copy used when the connector layer doesn't supply one.
_CONNECTOR_MESSAGES: dict[str, dict[str, str]] = {
    "gmail": {
        "token_expired": (
            "Gmail access has expired. Reconnect Google Workspace to resume unread-email stats."
        ),
        "rate_limited": (
            "Gmail is throttling requests right now. We'll retry on the next refresh."
        ),
        "backend_error": ("Gmail is currently returning errors. This is a Google-side outage."),
        "unknown": (
            "Gmail returned an unexpected error. Check the server logs for the full traceback."
        ),
    },
    "calendar": {
        "token_expired": (
            "Google Calendar access has expired. Reconnect Google Workspace to "
            "resume today's events."
        ),
        "rate_limited": (
            "Google Calendar is throttling requests right now. We'll retry on the next refresh."
        ),
        "backend_error": (
            "Google Calendar is currently returning errors. This is a Google-side outage."
        ),
        "unknown": (
            "Google Calendar returned an unexpected error. Check the server "
            "logs for the full traceback."
        ),
    },
}


def _connector_failure_payload(
    *,
    connector: str,
    exc: ConnectorError,
) -> dict[str, object]:
    """Build the structured failure payload exposed to the dashboard tile."""
    category = exc.category
    message = _CONNECTOR_MESSAGES.get(connector, {}).get(category) or str(exc)
    return {
        "status": "error",
        "category": category,
        "message": message,
        "actionable": exc.actionable,
        "action_url": _RECONNECT_URL if exc.actionable else None,
    }


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class StatCardData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    value: float | None
    label: str
    trend: float | None
    sparkline: list[float]
    sub_label: str | None = Field(serialization_alias="subLabel")
    status: Literal["available", "unavailable", "not_configured"] = "available"
    message: str | None = None
    # ── Categorised failure metadata (populated when status == "unavailable")
    error_category: Literal["token_expired", "rate_limited", "backend_error", "unknown"] | None = (
        Field(default=None, serialization_alias="errorCategory")
    )
    actionable: bool = False
    action_url: str | None = Field(default=None, serialization_alias="actionUrl")


class DashboardStats(BaseModel):
    mood: StatCardData
    projects: StatCardData
    emails: StatCardData
    events: StatCardData


class BriefingGreeting(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    greeting: str
    date_string: str = Field(serialization_alias="dateString")
    cognitive_load: int | str = Field(serialization_alias="cognitiveLoad")
    summary: str


class BriefingContent(BaseModel):
    title: str
    source: str
    url: str
    relevance: float


class BriefingNotice(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: Literal["calendar", "notifications", "content"]
    status: Literal["available", "unavailable", "not_configured"]
    message: str
    error_category: Literal["token_expired", "rate_limited", "backend_error", "unknown"] | None = (
        Field(default=None, serialization_alias="errorCategory")
    )
    actionable: bool = False
    action_url: str | None = Field(default=None, serialization_alias="actionUrl")


class MorningBriefing(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    greeting: BriefingGreeting
    schedule: list[dict]
    notifications: list[dict]
    content: list[BriefingContent]
    status: Literal["ready", "partial", "not_configured"]
    notices: list[BriefingNotice] = Field(default_factory=list)


class MoodEnergyPoint(BaseModel):
    date: str
    mood: float | None
    energy: float | None


class GoalDTO(BaseModel):
    id: str
    title: str
    goal_type: str | None
    parent_id: str | None
    priority: int
    status: str
    progress: float
    deadline: str | None
    evidence: list[str]
    created_at: str
    updated_at: str


class AgentActionDTO(BaseModel):
    id: str
    agent_name: str
    action_type: str | None
    model_used: str | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    duration_ms: int | None
    input_summary: str | None
    output_summary: str | None
    trace_id: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _goal_to_dto(g: Goal) -> GoalDTO:
    return GoalDTO(
        id=str(g.id),
        title=g.title,
        goal_type=g.goal_type,
        parent_id=str(g.parent_id) if g.parent_id else None,
        priority=g.priority,
        status=g.status,
        progress=g.progress,
        deadline=g.deadline.isoformat() if g.deadline else None,
        evidence=g.evidence or [],
        created_at=g.created_at.isoformat() if g.created_at else "",
        updated_at=g.updated_at.isoformat() if g.updated_at else "",
    )


def _action_to_dto(a: AgentAction) -> AgentActionDTO:
    return AgentActionDTO(
        id=str(a.id),
        agent_name=a.agent_name,
        action_type=a.action_type,
        model_used=a.model_used,
        tokens_in=a.tokens_in,
        tokens_out=a.tokens_out,
        cost_usd=a.cost_usd,
        duration_ms=a.duration_ms,
        input_summary=a.input_summary,
        output_summary=a.output_summary,
        trace_id=a.trace_id,
        created_at=a.created_at.isoformat() if a.created_at else "",
    )


def _calendar_event_to_dict(event) -> dict:
    """Convert a calendar-domain event into a frontend-friendly dict."""
    start = event.start
    end = event.end
    return {
        "id": event.id,
        "summary": event.summary,
        "start": start.isoformat() if hasattr(start, "isoformat") else str(start),
        "end": end.isoformat() if hasattr(end, "isoformat") else str(end),
        "location": event.location,
        "description": event.description,
        "attendees": event.attendees,
    }


def _notification_to_dict(notification: NotificationRecord) -> dict:
    """Convert a stored notification into the dashboard shape."""
    return {
        "id": str(notification.id),
        "message": notification.message,
        "priority": notification.priority,
        "category": notification.category,
        "created_at": notification.created_at.isoformat() if notification.created_at else "",
        "dismissed": notification.status == "dismissed",
    }


def _make_calendar_service():
    from src.app.agents.tools.calendar import CalendarService

    settings = get_settings()
    return CalendarService(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        refresh_token=settings.google_refresh_token.get_secret_value(),
    )


def _make_gmail_service():
    from src.app.agents.tools.email import GmailService

    settings = get_settings()
    return GmailService(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        refresh_token=settings.google_refresh_token.get_secret_value(),
    )


async def _get_todays_calendar_events(settings) -> list[dict]:
    """Load today's primary-calendar events in the user's timezone.

    Translates any underlying exception into a categorised
    :class:`ConnectorError` so the route handler can produce an actionable
    response instead of swallowing the failure.
    """
    from src.app.agents.tools.google_auth import translate_google_error

    timezone = ZoneInfo(settings.user_timezone)
    day_start_local = datetime.now(timezone).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_local = day_start_local + timedelta(days=1)

    service = _make_calendar_service()
    try:
        try:
            events = await service.list_events_between(
                day_start_local.astimezone(UTC),
                day_end_local.astimezone(UTC),
                max_results=50,
            )
        except Exception as exc:
            raise translate_google_error(exc, connector="calendar") from exc
    finally:
        await service.close()

    return [_calendar_event_to_dict(event) for event in events]


async def _get_unread_email_count() -> int:
    """Return the current unread Gmail count, capped by the API fetch limit.

    Translates any underlying exception into a categorised
    :class:`ConnectorError`.
    """
    from src.app.agents.tools.google_auth import translate_google_error

    service = _make_gmail_service()
    try:
        try:
            unread = await service.get_unread_emails(max_results=100)
        except Exception as exc:
            raise translate_google_error(exc, connector="gmail") from exc
    finally:
        await service.close()

    return len(unread)


async def _get_priority_notifications(
    db: AsyncSession,
    *,
    limit: int = 5,
) -> list[dict]:
    """Load the most important unread notifications for the dashboard briefing."""
    result = await db.execute(
        select(NotificationRecord).where(NotificationRecord.status == "unread")
    )
    scalars = await maybe_await(result.scalars())
    rows = await maybe_await(scalars.all())
    notifications = list(rows)
    notifications.sort(
        key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    notifications.sort(key=lambda item: _PRIORITY_ORDER.get(item.priority, 99))
    return [_notification_to_dict(item) for item in notifications[:limit]]


def _parse_curated_digest(digest: str) -> list[BriefingContent]:
    """Convert the stored digest text into structured content items."""
    items: list[BriefingContent] = []
    current: dict | None = None

    for raw_line in digest.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("CURATED CONTENT"):
            continue

        title_match = re.match(r"^\d+\.\s+(.*)$", line)
        if title_match:
            if current and current.get("url"):
                items.append(BriefingContent.model_validate(current))

            title_block = title_match.group(1)
            source = "Curated"
            source_match = re.match(r"^(.*?)(?:\s+\[([^\]]+)\])?$", title_block)
            if source_match is not None:
                title = source_match.group(1).strip()
                if source_match.group(2):
                    source = source_match.group(2).strip()
            else:
                title = title_block

            current = {
                "title": title,
                "source": source,
                "url": "",
                "relevance": 0.0,
            }
            continue

        if current is None:
            continue

        if line.startswith(("http://", "https://")):
            current["url"] = line
            continue

        relevance_match = re.match(r"^Relevance:\s+(\d+)%$", line, flags=re.IGNORECASE)
        if relevance_match:
            current["relevance"] = min(1.0, max(0.0, int(relevance_match.group(1)) / 100))

    if current and current.get("url"):
        items.append(BriefingContent.model_validate(current))

    return items[:5]


async def _get_curated_content(settings) -> list[BriefingContent]:
    """Load the latest curated digest from Redis and parse it into structured items."""
    from src.app.workers.curation import get_latest_digest

    digest = await get_latest_digest({"settings": settings})
    if not digest:
        return []
    return _parse_curated_digest(digest)


def _compute_cognitive_load(
    *,
    schedule_count: int,
    notification_count: int,
    content_count: int,
) -> int:
    """Estimate a simple cognitive load score for the morning briefing."""
    raw_score = schedule_count + (notification_count * 2) + min(content_count, 2)
    return max(1, min(10, raw_score))


def _build_briefing_summary(
    *,
    schedule_count: int,
    notification_count: int,
    content_count: int,
) -> str:
    """Summarize the morning briefing payload in one sentence."""
    parts: list[str] = []
    if schedule_count:
        parts.append(f"{schedule_count} event{'s' if schedule_count != 1 else ''}")
    if notification_count:
        parts.append(
            f"{notification_count} priority notification{'s' if notification_count != 1 else ''}"
        )
    if content_count:
        parts.append(f"{content_count} curated item{'s' if content_count != 1 else ''}")

    if not parts:
        return "Your briefing is ready."

    return "Today includes " + ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/dashboard/stats", response_model=DashboardStats)
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
) -> DashboardStats:
    """Return 4 stat cards for the dashboard."""
    try:
        settings = get_settings()
    except Exception:
        settings = None

    google_configured = bool(settings and settings.google_configured)
    seven_days_ago = datetime.now(UTC) - timedelta(days=7)

    # Average mood over last 7 days
    mood_result = await db.execute(
        select(func.avg(Episode.mood_score)).where(
            Episode.created_at >= seven_days_ago,
            Episode.mood_score.is_not(None),
        )
    )
    avg_mood_raw = mood_result.scalar()
    avg_mood = round(float(avg_mood_raw), 1) if avg_mood_raw is not None else None

    # Active project count
    project_result = await db.execute(
        select(func.count())
        .select_from(Project)
        .where(Project.status.in_(["planning", "in-progress"]))
    )
    active_projects = project_result.scalar() or 0

    logger.info("dashboard_stats", avg_mood=avg_mood, active_projects=active_projects)

    emails_card = StatCardData(
        value=None,
        label="Unread Emails",
        trend=None,
        sparkline=[],
        sub_label="Google Workspace",
        status="not_configured",
        message="Connect Google Workspace to surface unread-email stats.",
    )
    events_card = StatCardData(
        value=None,
        label="Today's Events",
        trend=None,
        sparkline=[],
        sub_label="Google Calendar",
        status="not_configured",
        message="Connect Google Workspace to surface today's calendar events.",
    )

    if google_configured and settings is not None:
        try:
            unread_count = await _get_unread_email_count()
            emails_card = StatCardData(
                value=float(unread_count),
                label="Unread Emails",
                trend=None,
                sparkline=[],
                sub_label="Live inbox",
                status="available",
                message=None,
            )
        except ConnectorError as exc:
            payload = _connector_failure_payload(connector="gmail", exc=exc)
            logger.warning(
                "dashboard_email_stats_failed",
                connector="gmail",
                category=exc.category,
                actionable=exc.actionable,
                error=str(exc),
                exc_info=True,
            )
            emails_card = StatCardData(
                value=None,
                label="Unread Emails",
                trend=None,
                sparkline=[],
                sub_label="Google Workspace",
                status="unavailable",
                message=payload["message"],
                error_category=payload["category"],
                actionable=payload["actionable"],
                action_url=payload["action_url"],
            )

        try:
            today_events = await _get_todays_calendar_events(settings)
            events_card = StatCardData(
                value=float(len(today_events)),
                label="Today's Events",
                trend=None,
                sparkline=[],
                sub_label="Google Calendar",
                status="available",
                message=None,
            )
        except ConnectorError as exc:
            payload = _connector_failure_payload(connector="calendar", exc=exc)
            logger.warning(
                "dashboard_calendar_stats_failed",
                connector="calendar",
                category=exc.category,
                actionable=exc.actionable,
                error=str(exc),
                exc_info=True,
            )
            events_card = StatCardData(
                value=None,
                label="Today's Events",
                trend=None,
                sparkline=[],
                sub_label="Google Calendar",
                status="unavailable",
                message=payload["message"],
                error_category=payload["category"],
                actionable=payload["actionable"],
                action_url=payload["action_url"],
            )

    return DashboardStats(
        mood=StatCardData(
            value=avg_mood,
            label="Average Mood",
            trend=None,
            sparkline=[],
            sub_label="Last 7 days",
        ),
        projects=StatCardData(
            value=float(active_projects),
            label="Active Projects",
            trend=None,
            sparkline=[],
            sub_label=None,
        ),
        emails=emails_card,
        events=events_card,
    )


@router.get("/dashboard/briefing", response_model=MorningBriefing)
async def morning_briefing(
    db: AsyncSession = Depends(get_db),
) -> MorningBriefing:
    """Morning briefing with explicit availability notices."""
    try:
        settings = get_settings()
    except Exception:
        settings = None

    google_configured = bool(settings and settings.google_configured)
    tavily_configured = bool(settings and settings.tavily_configured)
    now = datetime.now(UTC)
    hour = now.hour

    if hour < 12:
        greeting_text = "Good morning"
    elif hour < 17:
        greeting_text = "Good afternoon"
    else:
        greeting_text = "Good evening"

    schedule: list[dict] = []
    notifications: list[dict] = []
    content: list[BriefingContent] = []
    notices: list[BriefingNotice] = []

    if google_configured and settings is not None:
        try:
            schedule = await _get_todays_calendar_events(settings)
        except ConnectorError as exc:
            payload = _connector_failure_payload(connector="calendar", exc=exc)
            logger.warning(
                "dashboard_briefing_calendar_failed",
                connector="calendar",
                category=exc.category,
                actionable=exc.actionable,
                error=str(exc),
                exc_info=True,
            )
            notices.append(
                BriefingNotice(
                    source="calendar",
                    status="unavailable",
                    message=payload["message"],
                    error_category=payload["category"],
                    actionable=payload["actionable"],
                    action_url=payload["action_url"],
                )
            )
    else:
        notices.append(
            BriefingNotice(
                source="calendar",
                status="not_configured",
                message=(
                    "Connect Google Workspace to include your schedule in the morning briefing."
                ),
            )
        )

    try:
        notifications = await _get_priority_notifications(db)
    except Exception as exc:
        logger.warning("dashboard_briefing_notifications_failed", error=str(exc), exc_info=True)
        notices.append(
            BriefingNotice(
                source="notifications",
                status="unavailable",
                message="Priority notifications could not be loaded for the briefing.",
            )
        )

    if tavily_configured and settings is not None:
        try:
            content = await _get_curated_content(settings)
            if not content:
                notices.append(
                    BriefingNotice(
                        source="content",
                        status="unavailable",
                        message=(
                            "Research sources are configured, but no curated digest is "
                            "available yet."
                        ),
                    )
                )
        except Exception as exc:
            logger.warning("dashboard_briefing_content_failed", error=str(exc), exc_info=True)
            notices.append(
                BriefingNotice(
                    source="content",
                    status="unavailable",
                    message="Curated briefing content could not be loaded.",
                )
            )
    else:
        notices.append(
            BriefingNotice(
                source="content",
                status="not_configured",
                message="Configure Tavily to surface curated external content in the briefing.",
            )
        )

    summary = _build_briefing_summary(
        schedule_count=len(schedule),
        notification_count=len(notifications),
        content_count=len(content),
    )
    cognitive_load = _compute_cognitive_load(
        schedule_count=len(schedule),
        notification_count=len(notifications),
        content_count=len(content),
    )

    if not notices:
        status: Literal["ready", "partial", "not_configured"] = "ready"
    elif (
        all(notice.status == "not_configured" for notice in notices)
        and not schedule
        and not notifications
        and not content
    ):
        status = "not_configured"
    else:
        status = "partial"

    return MorningBriefing(
        greeting=BriefingGreeting(
            greeting=greeting_text,
            date_string=now.strftime("%A, %B %d, %Y"),
            cognitive_load=cognitive_load,
            summary=summary,
        ),
        schedule=schedule,
        notifications=notifications,
        content=content,
        status=status,
        notices=notices,
    )


@router.get("/dashboard/trends/mood-energy", response_model=list[MoodEnergyPoint])
async def mood_energy_trends(
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
) -> list[MoodEnergyPoint]:
    """Mood and energy time series grouped by date."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    result = await db.execute(
        select(
            cast(Episode.created_at, DATE).label("date"),
            func.avg(Episode.mood_score).label("mood"),
            func.avg(Episode.energy_rating).label("energy"),
        )
        .where(Episode.created_at >= cutoff)
        .group_by(cast(Episode.created_at, DATE))
        .order_by(cast(Episode.created_at, DATE))
    )

    points = [
        MoodEnergyPoint(
            date=str(row.date),
            mood=round(float(row.mood), 2) if row.mood is not None else None,
            energy=round(float(row.energy), 2) if row.energy is not None else None,
        )
        for row in result.all()
    ]

    logger.info("mood_energy_trends", days=days, points=len(points))
    return points


@router.get("/dashboard/diary/recent", response_model=list[EpisodeDTO])
async def recent_diary_entries(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(3, ge=1, le=20),
) -> list[EpisodeDTO]:
    """Recent diary entries for the dashboard."""
    stmt = (
        select(Episode)
        .where(Episode.episode_type == "diary")
        .order_by(Episode.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    episodes = list(result.scalars().all())

    return [_episode_to_dto(ep) for ep in episodes]


@router.get("/dashboard/goals", response_model=list[GoalDTO])
async def active_goals(
    db: AsyncSession = Depends(get_db),
    status: str = Query("active"),
    limit: int = Query(5, ge=1, le=50),
) -> list[GoalDTO]:
    """Active goals for the dashboard."""
    goals = await list_goals(db, status=status, limit=limit)
    return [_goal_to_dto(g) for g in goals]


@router.get("/dashboard/activity/recent", response_model=list[AgentActionDTO])
async def recent_agent_activity(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(5, ge=1, le=50),
) -> list[AgentActionDTO]:
    """Recent agent actions for the activity feed."""
    stmt = select(AgentAction).order_by(AgentAction.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    actions = list(result.scalars().all())

    return [_action_to_dto(a) for a in actions]
