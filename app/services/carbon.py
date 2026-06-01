"""Carbon-intensity computation: the EIA x emission-factor fusion.

gCO2/kWh = (Σ_fuel mwh[fuel] * lb_co2_per_mwh[fuel]) * 453.592
           / (Σ_fuel mwh[fuel] * 1000)

Negative/zero generation values (EIA reports these for net storage/rounding)
are clamped to 0 for the mix. See docs/SPEC.md §4.1.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CarbonIntensityHourly, EmissionFactor, GenerationHourly

LB_PER_MWH_TO_G_PER_KWH = 453.592 / 1000.0  # lb/MWh -> g/kWh


@dataclass(frozen=True)
class FuelFactor:
    co2_lb_per_mwh: float
    is_renewable: bool
    is_carbon_free: bool
    confidence: str


async def load_factors(session: AsyncSession, version: str = "v1-seed") -> dict[str, FuelFactor]:
    rows = (
        await session.execute(
            select(EmissionFactor).where(EmissionFactor.version == version)
        )
    ).scalars().all()
    return {
        r.fuel_code: FuelFactor(
            co2_lb_per_mwh=float(r.co2_lb_per_mwh),
            is_renewable=r.is_renewable,
            is_carbon_free=r.is_carbon_free,
            confidence=r.confidence,
        )
        for r in rows
    }


def _intensity_for_period(
    fuels: dict[str, float], factors: dict[str, FuelFactor]
) -> dict | None:
    """Compute intensity + shares for one period's {fuel: mwh} map."""
    total_mwh = 0.0
    total_emissions_lb = 0.0
    renewable_mwh = 0.0
    carbon_free_mwh = 0.0
    low_conf_mwh = 0.0

    for fuel, mwh in fuels.items():
        mwh = max(mwh, 0.0)  # clamp negatives
        if mwh == 0.0:
            continue
        factor = factors.get(fuel) or factors["OTH"]
        total_mwh += mwh
        total_emissions_lb += mwh * factor.co2_lb_per_mwh
        if factor.is_renewable:
            renewable_mwh += mwh
        if factor.is_carbon_free:
            carbon_free_mwh += mwh
        if factor.confidence == "low":
            low_conf_mwh += mwh

    if total_mwh <= 0.0:
        return None

    return {
        "gco2_per_kwh": round((total_emissions_lb / total_mwh) * LB_PER_MWH_TO_G_PER_KWH, 2),
        "total_mwh": round(total_mwh, 2),
        "renewable_share": round(renewable_mwh / total_mwh, 4),
        "carbon_free_share": round(carbon_free_mwh / total_mwh, 4),
        "low_confidence_share": round(low_conf_mwh / total_mwh, 4),
    }


async def recompute_region(session: AsyncSession, region_code: str) -> int:
    """Recompute carbon_intensity_hourly for every period of a region."""
    factors = await load_factors(session)

    gen_rows = (
        await session.execute(
            select(
                GenerationHourly.period,
                GenerationHourly.fuel_code,
                GenerationHourly.mwh,
            ).where(GenerationHourly.region_code == region_code)
        )
    ).all()

    by_period: dict[datetime, dict[str, float]] = defaultdict(dict)
    for period, fuel_code, mwh in gen_rows:
        by_period[period][fuel_code] = float(mwh)

    out_rows = []
    for period, fuels in by_period.items():
        result = _intensity_for_period(fuels, factors)
        if result is None:
            continue
        out_rows.append({"region_code": region_code, "period": period, **result})

    if not out_rows:
        return 0

    stmt = insert(CarbonIntensityHourly).values(out_rows)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["region_code", "period"],
            set_={
                "gco2_per_kwh": stmt.excluded.gco2_per_kwh,
                "total_mwh": stmt.excluded.total_mwh,
                "renewable_share": stmt.excluded.renewable_share,
                "carbon_free_share": stmt.excluded.carbon_free_share,
                "low_confidence_share": stmt.excluded.low_confidence_share,
            },
        )
    )
    await session.commit()
    return len(out_rows)
