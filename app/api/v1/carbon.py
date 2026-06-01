"""Carbon-intensity endpoints. Phase 1: /carbon/now."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import (
    CarbonIntensityHourly,
    EmissionFactor,
    GenerationHourly,
    Region,
    ZipRegion,
)
from app.schemas import CarbonNowOut, FuelSlice

router = APIRouter(prefix="/carbon", tags=["carbon"])


@router.get("/now", response_model=CarbonNowOut)
async def carbon_now(
    zip: str | None = Query(default=None, min_length=5, max_length=5, pattern=r"^\d{5}$"),
    region: str | None = Query(default=None, min_length=2, max_length=8),
    session: AsyncSession = Depends(get_session),
):
    """Most recent carbon intensity for a ZIP's grid region (or a region code)."""
    if (zip is None) == (region is None):
        raise HTTPException(
            status_code=400, detail="Provide exactly one of 'zip' or 'region'."
        )

    zip_confidence: str | None = None
    if zip is not None:
        zr = await session.get(ZipRegion, zip)
        if zr is None:
            raise HTTPException(status_code=404, detail=f"ZIP '{zip}' not in crosswalk.")
        region_code = zr.region_code
        zip_confidence = zr.mapping_confidence
    else:
        region_code = region.upper()

    region_row = await session.get(Region, region_code)
    if region_row is None:
        raise HTTPException(status_code=404, detail=f"Unknown region '{region_code}'.")

    latest = (
        await session.execute(
            select(CarbonIntensityHourly)
            .where(CarbonIntensityHourly.region_code == region_code)
            .order_by(CarbonIntensityHourly.period.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None:
        raise HTTPException(
            status_code=503,
            detail=f"No carbon data yet for '{region_code}'. Ingest may not have run.",
        )

    # Fuel breakdown for that period.
    gen_rows = (
        await session.execute(
            select(GenerationHourly.fuel_code, GenerationHourly.mwh).where(
                GenerationHourly.region_code == region_code,
                GenerationHourly.period == latest.period,
            )
        )
    ).all()
    names = dict(
        (
            await session.execute(
                select(EmissionFactor.fuel_code, EmissionFactor.fuel_name).where(
                    EmissionFactor.version == "v1-seed"
                )
            )
        ).all()
    )

    total = float(latest.total_mwh) or 1.0
    fuel_mix = [
        FuelSlice(
            fuel_code=fc,
            fuel_name=names.get(fc, fc),
            mwh=round(max(float(mwh), 0.0), 2),
            share=round(max(float(mwh), 0.0) / total, 4),
        )
        for fc, mwh in gen_rows
        if max(float(mwh), 0.0) > 0
    ]
    fuel_mix.sort(key=lambda s: s.mwh, reverse=True)

    caveats = [
        "Average (not marginal) emissions, computed from the reported fuel mix.",
        "Hourly data from EIA-930; values trail real time by a few hours.",
    ]
    if region_row.mapping_confidence != "exact":
        caveats.append(
            f"BA->eGRID subregion mapping is '{region_row.mapping_confidence}'."
        )
    if zip_confidence and zip_confidence != "exact":
        caveats.append(f"ZIP->region mapping is '{zip_confidence}'.")
    if float(latest.low_confidence_share) > 0.05:
        caveats.append(
            f"{round(float(latest.low_confidence_share) * 100)}% of generation "
            "uses low-confidence emission factors (GEO/OTH)."
        )

    return CarbonNowOut(
        region_code=region_row.code,
        region_name=region_row.name,
        egrid_subregion=region_row.egrid_subregion,
        mapping_confidence=region_row.mapping_confidence,
        zip=zip,
        zip_mapping_confidence=zip_confidence,
        period=latest.period,
        gco2_per_kwh=float(latest.gco2_per_kwh),
        total_mwh=float(latest.total_mwh),
        renewable_share=float(latest.renewable_share),
        carbon_free_share=float(latest.carbon_free_share),
        low_confidence_share=float(latest.low_confidence_share),
        fuel_mix=fuel_mix,
        caveats=caveats,
    )
