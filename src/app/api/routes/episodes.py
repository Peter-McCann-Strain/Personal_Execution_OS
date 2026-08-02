"""Episode routes — paginated list, stats, single episode."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, cast, func, select, text
from sqlalchemy.dialects.postgresql import DATE
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_principal, get_db
from src.app.api.schemas import PaginatedResponse, paginate
from src.app.core.exceptions import NotFoundError
from src.app.persistence.models import Episode
from src.app.persistence.repositories.episodes import (
    get_episode_by_id as repo_get_episode_by_id,
)
from src.app.persistence.repositories.episodes import (
    get_episodes_by_date_range as repo_get_episodes_by_date_range,
)
from src.app.persistence.repositories.episodes import (
    update_episode as repo_update_episode,
)

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(get_current_principal)])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class EpisodeDTO(BaseModel):
    """Episode response matching the frontend Episode type exactly."""

    id: str
    content: str
    summary: str | None
    episode_type: str
    para_category: str | None
    mood_score: float | None
    energy_rating: float | None
    tags: list[str]
    people_mentioned: list[str]
    source: str
    created_at: str


class MoodTrendPoint(BaseModel):
    date: str
    mood: float | None
    energy: float | None
    count: int


class TagCount(BaseModel):
    tag: str
    count: int


class ParaCount(BaseModel):
    category: str
    count: int


class EpisodeStats(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_entries: int = Field(serialization_alias="totalEntries")
    average_mood: float | None = Field(serialization_alias="averageMood")
    average_energy: float | None = Field(serialization_alias="averageEnergy")
    mood_trend: list[MoodTrendPoint] = Field(serialization_alias="moodTrend")
    tag_frequency: list[TagCount] = Field(serialization_alias="tagFrequency")
    para_distribution: list[ParaCount] = Field(serialization_alias="paraDistribution")


class UpdateEpisodeBody(BaseModel):
    """Body for PATCH /episodes/{episode_id}."""

    content: str | None = None
    summary: str | None = None
    episode_type: str | None = None
    para_category: str | None = None
    mood_score: float | None = None
    energy_rating: float | None = None
    tags: list[str] | None = None
    people_mentioned: list[str] | None = None
    source: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _episode_to_dto(ep: Episode) -> EpisodeDTO:
    return EpisodeDTO(
        id=str(ep.id),
        content=ep.content,
        summary=ep.summary,
        episode_type=ep.episode_type or "diary",
        para_category=ep.para_category,
        mood_score=ep.mood_score,
        energy_rating=ep.energy_rating,
        tags=ep.tags or [],
        people_mentioned=ep.people_mentioned or [],
        source=ep.source or "api",
        created_at=ep.created_at.isoformat() if ep.created_at else "",
    )


def _ensure_aware_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/episodes", response_model=PaginatedResponse[EpisodeDTO])
async def list_episodes(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    para_category: str | None = Query(None),
    episode_type: str | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated tags"),
    people: str | None = Query(None, description="Comma-separated people"),
    mood_min: float | None = Query(None),
    mood_max: float | None = Query(None),
) -> PaginatedResponse[EpisodeDTO]:
    """Paginated episodes with dynamic filters."""
    stmt = select(Episode).where(Episode.deleted_at.is_(None))
    count_stmt = select(func.count()).select_from(Episode).where(Episode.deleted_at.is_(None))

    # --- Filters ---

    if date_from is not None:
        dt_from = _ensure_aware_utc(date_from)
        stmt = stmt.where(Episode.created_at >= dt_from)
        count_stmt = count_stmt.where(Episode.created_at >= dt_from)

    if date_to is not None:
        dt_to = _ensure_aware_utc(date_to)
        stmt = stmt.where(Episode.created_at <= dt_to)
        count_stmt = count_stmt.where(Episode.created_at <= dt_to)

    if para_category is not None:
        stmt = stmt.where(Episode.para_category == para_category)
        count_stmt = count_stmt.where(Episode.para_category == para_category)

    if episode_type is not None:
        stmt = stmt.where(Episode.episode_type == episode_type)
        count_stmt = count_stmt.where(Episode.episode_type == episode_type)

    if tags is not None:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            stmt = stmt.where(Episode.tags.overlap(tag_list))
            count_stmt = count_stmt.where(Episode.tags.overlap(tag_list))

    if people is not None:
        people_list = [p.strip() for p in people.split(",") if p.strip()]
        if people_list:
            stmt = stmt.where(Episode.people_mentioned.overlap(people_list))
            count_stmt = count_stmt.where(Episode.people_mentioned.overlap(people_list))

    if mood_min is not None:
        stmt = stmt.where(Episode.mood_score >= mood_min)
        count_stmt = count_stmt.where(Episode.mood_score >= mood_min)

    if mood_max is not None:
        stmt = stmt.where(Episode.mood_score <= mood_max)
        count_stmt = count_stmt.where(Episode.mood_score <= mood_max)

    # --- Sorting ---

    allowed_sort = {"created_at", "mood_score", "energy_rating"}
    sort_col = getattr(Episode, sort) if sort in allowed_sort else Episode.created_at
    stmt = stmt.order_by(sort_col.desc() if order == "desc" else sort_col.asc())

    # --- Count + paginate ---

    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    episodes = list(result.scalars().all())

    items = [_episode_to_dto(ep) for ep in episodes]

    logger.info("episodes_listed", total=total, returned=len(items), offset=offset)
    return paginate(items=items, total=total, offset=offset, limit=limit)


@router.get("/episodes/stats", response_model=EpisodeStats)
async def episode_stats(
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
) -> EpisodeStats:
    """Aggregated episode statistics for the last N days."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Total entries
    total_result = await db.execute(
        select(func.count())
        .select_from(Episode)
        .where(
            Episode.created_at >= cutoff,
            Episode.deleted_at.is_(None),
        )
    )
    total_entries = total_result.scalar() or 0

    # Average mood and energy
    avg_result = await db.execute(
        select(
            func.avg(Episode.mood_score),
            func.avg(Episode.energy_rating),
        ).where(Episode.created_at >= cutoff, Episode.deleted_at.is_(None))
    )
    avg_row = avg_result.one()
    avg_mood = round(float(avg_row[0]), 2) if avg_row[0] is not None else None
    avg_energy = round(float(avg_row[1]), 2) if avg_row[1] is not None else None

    # Mood trend (daily averages)
    trend_result = await db.execute(
        select(
            cast(Episode.created_at, DATE).label("date"),
            func.avg(Episode.mood_score).label("mood"),
            func.avg(Episode.energy_rating).label("energy"),
            func.count().label("entry_count"),
        )
        .where(Episode.created_at >= cutoff, Episode.deleted_at.is_(None))
        .group_by(cast(Episode.created_at, DATE))
        .order_by(cast(Episode.created_at, DATE))
    )
    mood_trend = [
        MoodTrendPoint(
            date=str(row.date),
            mood=round(float(row.mood), 2) if row.mood is not None else None,
            energy=round(float(row.energy), 2) if row.energy is not None else None,
            count=int(row.entry_count),
        )
        for row in trend_result.all()
    ]

    # Tag frequency via raw SQL (unnest the array)
    tag_result = await db.execute(
        text("""
            SELECT tag, COUNT(*) AS cnt
            FROM episodes, unnest(tags) AS tag
            WHERE created_at >= :cutoff AND deleted_at IS NULL
            GROUP BY tag
            ORDER BY cnt DESC
            LIMIT 20
        """),
        {"cutoff": cutoff},
    )
    tag_frequency = [TagCount(tag=row.tag, count=row.cnt) for row in tag_result.all()]

    # PARA distribution
    para_result = await db.execute(
        select(
            case(
                (Episode.para_category.is_(None), "unclassified"),
                else_=Episode.para_category,
            ).label("category"),
            func.count().label("entry_count"),
        )
        .where(Episode.created_at >= cutoff, Episode.deleted_at.is_(None))
        .group_by("category")
        .order_by(func.count().desc())
    )
    para_distribution = [
        ParaCount(category=row.category, count=int(row.entry_count)) for row in para_result.all()
    ]

    logger.info("episode_stats", days=days, total=total_entries)
    return EpisodeStats(
        total_entries=total_entries,
        average_mood=avg_mood,
        average_energy=avg_energy,
        mood_trend=mood_trend,
        tag_frequency=tag_frequency,
        para_distribution=para_distribution,
    )


@router.get("/episodes/date-range", response_model=list[EpisodeDTO])
async def get_episodes_by_date_range(
    db: AsyncSession = Depends(get_db),
    start: datetime = Query(..., description="ISO-8601 start datetime"),
    end: datetime = Query(..., description="ISO-8601 end datetime"),
    limit: int = Query(50, ge=1, le=200),
) -> list[EpisodeDTO]:
    """Get episodes within a date range, newest first."""
    start_dt = _ensure_aware_utc(start)
    end_dt = _ensure_aware_utc(end)
    episodes = await repo_get_episodes_by_date_range(db, start=start_dt, end=end_dt, limit=limit)
    return [_episode_to_dto(ep) for ep in episodes]


@router.get("/episodes/{episode_id}", response_model=EpisodeDTO)
async def get_episode(
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> EpisodeDTO:
    """Get a single episode by ID."""
    episode = await repo_get_episode_by_id(db, episode_id)
    if episode is None:
        raise NotFoundError(f"Episode not found: {episode_id}")
    return _episode_to_dto(episode)


@router.patch("/episodes/{episode_id}", response_model=EpisodeDTO)
async def update_episode(
    episode_id: uuid.UUID,
    body: UpdateEpisodeBody,
    db: AsyncSession = Depends(get_db),
) -> EpisodeDTO:
    """Update episode fields. Only provided fields are updated."""
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    async with db.begin():
        try:
            episode = await repo_update_episode(db, episode_id, **kwargs)
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc
    await db.refresh(episode)
    logger.info("episode_updated_via_api", episode_id=str(episode_id))
    return _episode_to_dto(episode)


@router.delete("/episodes/{episode_id}", status_code=204)
async def delete_episode(
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete an episode by ID."""
    async with db.begin():
        episode = await repo_get_episode_by_id(db, episode_id)
        if episode is None:
            raise NotFoundError(f"Episode not found: {episode_id}")
        episode.soft_delete()
    logger.info("episode_soft_deleted_via_api", episode_id=str(episode_id))
