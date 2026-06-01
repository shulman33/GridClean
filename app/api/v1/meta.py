"""Operational metadata endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ratelimit import enforce_rate_limit
from app.db.session import get_session
from app.models import CarbonIntensityHourly

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/freshness")
async def freshness(
    session: AsyncSession = Depends(get_session),
    _=Depends(enforce_rate_limit),
):
    """Most recent data point per region — transparency on staleness."""
    rows = (
        await session.execute(
            select(
                CarbonIntensityHourly.region_code,
                func.max(CarbonIntensityHourly.period).label("latest"),
            ).group_by(CarbonIntensityHourly.region_code)
        )
    ).all()
    return {
        "regions": {code: latest.isoformat() for code, latest in rows},
        "count": len(rows),
    }
