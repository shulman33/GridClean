"""Integration tests for /v1/regions and /v1/carbon/now.

Uses synthetic generation at a far-future period so `/now` (which returns the
latest period) is deterministic regardless of any real ingested data. No live
EIA calls — CI stays hermetic.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models import CarbonIntensityHourly, GenerationHourly
from app.seed.load import seed_all
from app.services.carbon import recompute_region

TEST_PERIOD = datetime(2099, 1, 1, 0, 0, tzinfo=UTC)
TEST_REGION = "CISO"


@pytest.fixture
async def seeded():
    async with SessionLocal() as session:
        await seed_all(session)
        # Half gas, half wind -> ~204 gCO2/kWh, 50% renewable.
        session.add_all(
            [
                GenerationHourly(
                    region_code=TEST_REGION, period=TEST_PERIOD, fuel_code="NG", mwh=1000
                ),
                GenerationHourly(
                    region_code=TEST_REGION, period=TEST_PERIOD, fuel_code="WND", mwh=1000
                ),
            ]
        )
        await session.commit()
        await recompute_region(session, TEST_REGION)
    yield
    # Cleanup synthetic rows.
    async with SessionLocal() as session:
        for model in (GenerationHourly, CarbonIntensityHourly):
            await session.execute(
                delete(model).where(
                    model.region_code == TEST_REGION, model.period == TEST_PERIOD
                )
            )
        await session.commit()


async def test_list_regions(client, seeded):
    resp = await client.get("/v1/regions")
    assert resp.status_code == 200
    codes = {r["code"] for r in resp.json()}
    assert {"CISO", "ERCO", "ISNE", "MISO"} <= codes


async def test_carbon_now_by_region(client, seeded):
    resp = await client.get(f"/v1/carbon/now?region={TEST_REGION}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["period"].startswith("2099-01-01")
    assert body["gco2_per_kwh"] == pytest.approx(204.12, abs=0.1)
    assert body["renewable_share"] == pytest.approx(0.5)
    assert {s["fuel_code"] for s in body["fuel_mix"]} == {"NG", "WND"}


async def test_carbon_now_requires_exactly_one_param(client):
    assert (await client.get("/v1/carbon/now")).status_code == 400
    assert (await client.get("/v1/carbon/now?zip=10001&region=CISO")).status_code == 400


async def test_carbon_now_unknown_zip(client, seeded):
    assert (await client.get("/v1/carbon/now?zip=00000")).status_code == 404
