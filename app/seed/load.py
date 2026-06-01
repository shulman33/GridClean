"""Idempotent loader for seed reference data."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmissionFactor, Region, ZipRegion
from app.seed.data import (
    EMISSION_FACTOR_SOURCE,
    EMISSION_FACTORS,
    REGIONS,
    ZIP_REGION,
)


async def seed_all(session: AsyncSession) -> dict[str, int]:
    """Upsert all reference data. Safe to run repeatedly."""
    region_rows = [
        {
            "code": code,
            "name": name,
            "egrid_subregion": subregion,
            "mapping_confidence": confidence,
            "timezone": tz,
            "notes": notes,
        }
        for (code, name, subregion, confidence, tz, notes) in REGIONS
    ]
    stmt = insert(Region).values(region_rows)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["code"],
            set_={
                "name": stmt.excluded.name,
                "egrid_subregion": stmt.excluded.egrid_subregion,
                "mapping_confidence": stmt.excluded.mapping_confidence,
                "timezone": stmt.excluded.timezone,
                "notes": stmt.excluded.notes,
            },
        )
    )

    factor_rows = [
        {
            "fuel_code": code,
            "fuel_name": fname,
            "co2_lb_per_mwh": co2,
            "is_renewable": renewable,
            "is_carbon_free": carbon_free,
            "confidence": confidence,
            "version": "v1-seed",
            "source": EMISSION_FACTOR_SOURCE,
        }
        for (code, fname, co2, renewable, carbon_free, confidence) in EMISSION_FACTORS
    ]
    fstmt = insert(EmissionFactor).values(factor_rows)
    await session.execute(
        fstmt.on_conflict_do_update(
            index_elements=["fuel_code", "version"],
            set_={
                "fuel_name": fstmt.excluded.fuel_name,
                "co2_lb_per_mwh": fstmt.excluded.co2_lb_per_mwh,
                "is_renewable": fstmt.excluded.is_renewable,
                "is_carbon_free": fstmt.excluded.is_carbon_free,
                "confidence": fstmt.excluded.confidence,
                "source": fstmt.excluded.source,
            },
        )
    )

    zip_rows = [
        {
            "zip": z,
            "region_code": region,
            "mapping_confidence": confidence,
            "notes": notes,
        }
        for (z, region, confidence, notes) in ZIP_REGION
    ]
    zstmt = insert(ZipRegion).values(zip_rows)
    await session.execute(
        zstmt.on_conflict_do_update(
            index_elements=["zip"],
            set_={
                "region_code": zstmt.excluded.region_code,
                "mapping_confidence": zstmt.excluded.mapping_confidence,
                "notes": zstmt.excluded.notes,
            },
        )
    )

    await session.commit()
    return {
        "regions": len(region_rows),
        "emission_factors": len(factor_rows),
        "zip_region": len(zip_rows),
    }
