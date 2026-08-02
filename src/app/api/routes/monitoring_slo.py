"""Service-level objective monitoring routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_db

from .monitoring_models import SLOReportDTO, SLOValueDTO

router = APIRouter()


@router.get("/monitoring/slo", response_model=SLOReportDTO)
@router.get("/ops/slo", response_model=SLOReportDTO)
async def slo_report(
    session: AsyncSession = Depends(get_db),
    window_hours: int = Query(24, ge=1, le=168),
) -> SLOReportDTO:
    """Return current SLO values, targets and burn rates.

    Covers the five SLOs defined in :mod:`src.app.core.slo`:
    latency, error, quality (7-day rolling p10 of auto-judge scores),
    goodput (combined latency + quality), and cost (daily spend in GBP).
    """
    from src.app.api.routes import monitoring as monitoring_facade

    settings = monitoring_facade.get_settings()
    report = await monitoring_facade.collect_slo_report(
        session, settings, window_hours=window_hours
    )
    return SLOReportDTO(
        window_hours=report.window_hours,
        generated_at=report.generated_at.isoformat(),
        slos=[SLOValueDTO(**slo.as_dict()) for slo in report.slos],
    )
