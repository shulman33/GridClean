"""Ingest EIA-930 generation into `generation_hourly`, then recompute intensity."""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models import GenerationHourly, Region
from app.services.carbon import recompute_region
from app.services.eia import EIAClient


async def ingest_region(
    session: AsyncSession, region_code: str, hours: int = 48, client: EIAClient | None = None
) -> int:
    """Fetch + upsert generation for one region, then recompute its intensity.

    Returns the number of generation rows upserted.
    """
    client = client or EIAClient()
    points = await client.fetch_fuel_type(region_code, hours=hours)
    if not points:
        return 0

    # Aggregate by (region, period, fuel) — EIA fuel codes outside our known
    # set collapse onto "OTH", which can yield several source rows per hour;
    # their generation must be summed, and duplicate keys in one upsert batch
    # would otherwise trip ON CONFLICT.
    agg: dict[tuple[str, object, str], float] = defaultdict(float)
    for p in points:
        agg[(p.region_code, p.period, p.fuel_code)] += p.mwh

    rows = [
        {"region_code": rc, "period": period, "fuel_code": fc, "mwh": mwh}
        for (rc, period, fc), mwh in agg.items()
    ]
    stmt = insert(GenerationHourly).values(rows)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["region_code", "period", "fuel_code"],
            set_={"mwh": stmt.excluded.mwh},
        )
    )
    await session.commit()

    await recompute_region(session, region_code)
    return len(rows)


async def ingest_all(session: AsyncSession, hours: int = 48) -> dict[str, int]:
    """Ingest every seeded region. Returns {region_code: rows_upserted}.

    Each region gets its own session so one region's failure can't poison the
    transaction for the rest.
    """
    codes = (await session.execute(select(Region.code))).scalars().all()
    client = EIAClient()
    results: dict[str, int] = {}
    for code in codes:
        try:
            async with SessionLocal() as region_session:
                results[code] = await ingest_region(
                    region_session, code, hours=hours, client=client
                )
        except Exception as exc:  # noqa: BLE001 — one bad BA shouldn't sink the batch
            results[code] = -1
            print(f"[ingest] {code} failed: {exc}")
    return results
