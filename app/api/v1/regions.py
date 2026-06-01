"""Region listing endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Region
from app.schemas import RegionOut

router = APIRouter(tags=["regions"])


@router.get("/regions", response_model=list[RegionOut])
async def list_regions(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Region).order_by(Region.code))).scalars().all()
    return rows


@router.get("/regions/{code}", response_model=RegionOut)
async def get_region(code: str, session: AsyncSession = Depends(get_session)):
    region = await session.get(Region, code.upper())
    if region is None:
        raise HTTPException(status_code=404, detail=f"Unknown region '{code}'")
    return region
