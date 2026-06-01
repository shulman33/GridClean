"""Management CLI for GridClean data operations.

Usage:
    python -m app.manage seed                 # load reference data
    python -m app.manage ingest [--hours 48]  # fetch EIA + recompute intensity
    python -m app.manage compute               # recompute intensity from stored gen
"""

import argparse
import asyncio

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Region
from app.seed.load import seed_all
from app.services.carbon import recompute_region
from app.services.ingest import ingest_all


async def _seed() -> None:
    async with SessionLocal() as session:
        counts = await seed_all(session)
    print(f"[seed] {counts}")


async def _ingest(hours: int) -> None:
    async with SessionLocal() as session:
        results = await ingest_all(session, hours=hours)
    ok = {k: v for k, v in results.items() if v >= 0}
    failed = [k for k, v in results.items() if v < 0]
    print(f"[ingest] upserted rows per region: {ok}")
    if failed:
        print(f"[ingest] FAILED regions: {failed}")


async def _compute() -> None:
    async with SessionLocal() as session:
        codes = (await session.execute(select(Region.code))).scalars().all()
        total = 0
        for code in codes:
            total += await recompute_region(session, code)
    print(f"[compute] wrote {total} intensity rows across {len(codes)} regions")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.manage")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    p_ingest = sub.add_parser("ingest")
    p_ingest.add_argument("--hours", type=int, default=48)
    sub.add_parser("compute")

    args = parser.parse_args()
    if args.cmd == "seed":
        asyncio.run(_seed())
    elif args.cmd == "ingest":
        asyncio.run(_ingest(args.hours))
    elif args.cmd == "compute":
        asyncio.run(_compute())


if __name__ == "__main__":
    main()
