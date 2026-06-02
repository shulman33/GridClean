"""Query + response-shaping helpers for the carbon endpoints.

Keeps routers thin: region resolution, the /now payload, history (keyset
pagination), region comparison, and time-shift savings all live here.
"""

from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CarbonIntensityHourly,
    EmissionFactor,
    GenerationHourly,
    Region,
    ZipRegion,
)
from app.pagination import decode_cursor, encode_cursor
from app.schemas import (
    CarbonNowOut,
    CompareItem,
    CompareOut,
    FuelSlice,
    HistoryOut,
    HistoryPoint,
    SavingsOut,
)
from app.services.zip_lookup import region_for_zip


async def resolve_region(
    session: AsyncSession, zip_code: str | None, region: str | None
) -> tuple[Region, str | None]:
    """Resolve a (region_row, zip_confidence) from exactly one of zip/region."""
    if (zip_code is None) == (region is None):
        raise HTTPException(
            status_code=400, detail="Provide exactly one of 'zip' or 'region'."
        )

    zip_confidence: str | None = None
    if zip_code is not None:
        zr = await session.get(ZipRegion, zip_code)
        if zr is not None:
            # Curated, city-accurate entry (exact/dominant/approximate).
            region_code = zr.region_code
            zip_confidence = zr.mapping_confidence
        else:
            # Fall back to the nationwide ZIP3-prefix map (see zip_lookup.py).
            region_code = region_for_zip(zip_code)
            if region_code is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"ZIP '{zip_code}' is outside GridClean's tracked grid regions "
                        "(Alaska, Hawaii, and US territories aren't covered)."
                    ),
                )
            zip_confidence = "approximate"
    else:
        region_code = region.upper()

    region_row = await session.get(Region, region_code)
    if region_row is None:
        raise HTTPException(status_code=404, detail=f"Unknown region '{region_code}'.")
    return region_row, zip_confidence


async def _latest_intensity(
    session: AsyncSession, region_code: str
) -> CarbonIntensityHourly | None:
    return (
        await session.execute(
            select(CarbonIntensityHourly)
            .where(CarbonIntensityHourly.region_code == region_code)
            .order_by(CarbonIntensityHourly.period.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def build_now(
    session: AsyncSession, region_row: Region, zip_code: str | None, zip_confidence: str | None
) -> CarbonNowOut:
    latest = await _latest_intensity(session, region_row.code)
    if latest is None:
        raise HTTPException(
            status_code=503,
            detail=f"No carbon data yet for '{region_row.code}'. Ingest may not have run.",
        )

    gen_rows = (
        await session.execute(
            select(GenerationHourly.fuel_code, GenerationHourly.mwh).where(
                GenerationHourly.region_code == region_row.code,
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
        caveats.append(f"BA->eGRID subregion mapping is '{region_row.mapping_confidence}'.")
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
        zip=zip_code,
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


async def get_history(
    session: AsyncSession,
    region_code: str,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    cursor: str | None,
) -> HistoryOut:
    region_row = await session.get(Region, region_code)
    if region_row is None:
        raise HTTPException(status_code=404, detail=f"Unknown region '{region_code}'.")

    conditions = [CarbonIntensityHourly.region_code == region_code]
    if start is not None:
        conditions.append(CarbonIntensityHourly.period >= start)
    if end is not None:
        conditions.append(CarbonIntensityHourly.period <= end)
    if cursor is not None:
        conditions.append(CarbonIntensityHourly.period < decode_cursor(cursor))

    rows = (
        await session.execute(
            select(CarbonIntensityHourly)
            .where(*conditions)
            .order_by(CarbonIntensityHourly.period.desc())
            .limit(limit + 1)  # fetch one extra to detect a next page
        )
    ).scalars().all()

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].period)

    data = [
        HistoryPoint(
            period=r.period,
            gco2_per_kwh=float(r.gco2_per_kwh),
            total_mwh=float(r.total_mwh),
            renewable_share=float(r.renewable_share),
            carbon_free_share=float(r.carbon_free_share),
            low_confidence_share=float(r.low_confidence_share),
        )
        for r in rows
    ]
    return HistoryOut(
        region_code=region_code, count=len(data), next_cursor=next_cursor, data=data
    )


async def build_compare(session: AsyncSession, region_codes: list[str]) -> CompareOut:
    items: list[CompareItem] = []
    unavailable: list[str] = []
    for code in region_codes:
        region_row = await session.get(Region, code)
        latest = await _latest_intensity(session, code) if region_row else None
        if region_row is None or latest is None:
            unavailable.append(code)
            continue
        items.append(
            CompareItem(
                rank=0,  # assigned after sort
                region_code=code,
                region_name=region_row.name,
                period=latest.period,
                gco2_per_kwh=float(latest.gco2_per_kwh),
                renewable_share=float(latest.renewable_share),
                carbon_free_share=float(latest.carbon_free_share),
            )
        )

    items.sort(key=lambda i: i.gco2_per_kwh)
    for rank, item in enumerate(items, start=1):
        item.rank = rank
    return CompareOut(requested=region_codes, items=items, unavailable=unavailable)


async def compute_savings(
    session: AsyncSession, region_row: Region, kwh: float, from_hour: int, to_hour: int
) -> SavingsOut:
    """Time-shift savings from average carbon intensity by local hour-of-day."""
    rows = (
        await session.execute(
            select(CarbonIntensityHourly.period, CarbonIntensityHourly.gco2_per_kwh).where(
                CarbonIntensityHourly.region_code == region_row.code
            )
        )
    ).all()
    if not rows:
        raise HTTPException(
            status_code=503, detail=f"No carbon data yet for '{region_row.code}'."
        )

    tz = ZoneInfo(region_row.timezone) if region_row.timezone else ZoneInfo("UTC")
    buckets: dict[int, list[float]] = defaultdict(list)
    for period, gco2 in rows:
        local_hour = period.astimezone(tz).hour
        buckets[local_hour].append(float(gco2))

    for hour in (from_hour, to_hour):
        if hour not in buckets:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"No data for local hour {hour} yet; "
                    "ingest more history or try a different hour."
                ),
            )

    from_intensity = round(sum(buckets[from_hour]) / len(buckets[from_hour]), 2)
    to_intensity = round(sum(buckets[to_hour]) / len(buckets[to_hour]), 2)
    from_co2 = round(from_intensity * kwh, 2)
    to_co2 = round(to_intensity * kwh, 2)
    savings = round(from_co2 - to_co2, 2)
    savings_pct = round((savings / from_co2) * 100, 1) if from_co2 > 0 else 0.0

    return SavingsOut(
        region_code=region_row.code,
        region_name=region_row.name,
        timezone=region_row.timezone,
        kwh=kwh,
        from_hour=from_hour,
        to_hour=to_hour,
        from_intensity_gco2_per_kwh=from_intensity,
        to_intensity_gco2_per_kwh=to_intensity,
        from_co2_g=from_co2,
        to_co2_g=to_co2,
        savings_g=savings,
        savings_pct=savings_pct,
        basis="Average carbon intensity by local hour-of-day over available history.",
        caveats=[
            "Based on historical hour-of-day averages, not a forecast (forecast lands in Phase 3).",
            "Average (not marginal) emissions.",
        ],
    )
