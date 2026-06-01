"""Integration tests for the carbon endpoints + Phase 2 cross-cutting concerns.

Synthetic generation is written at a far-future day so `/now` (latest period)
and friends are deterministic regardless of any real ingested data. No live
EIA calls — CI stays hermetic.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.core.security import generate_key
from app.db.session import SessionLocal
from app.models import ApiKey, CarbonIntensityHourly, GenerationHourly
from app.services.carbon import recompute_region

DAY = datetime(2099, 1, 1, 0, 0, tzinfo=UTC)
DAY_END = DAY + timedelta(days=1)
TEST_REGION = "CISO"


@pytest.fixture
async def seeded():
    """Seed reference data + 24 hourly synthetic points (NG+WND, ~204 g/kWh)."""
    from app.seed.load import seed_all

    async with SessionLocal() as session:
        await seed_all(session)
        rows = []
        for hour in range(24):
            period = DAY + timedelta(hours=hour)
            rows.append(
                GenerationHourly(region_code=TEST_REGION, period=period, fuel_code="NG", mwh=1000)
            )
            rows.append(
                GenerationHourly(region_code=TEST_REGION, period=period, fuel_code="WND", mwh=1000)
            )
        session.add_all(rows)
        await session.commit()
        await recompute_region(session, TEST_REGION)
    yield
    async with SessionLocal() as session:
        for model in (GenerationHourly, CarbonIntensityHourly):
            await session.execute(
                delete(model).where(
                    model.region_code == TEST_REGION,
                    model.period >= DAY,
                    model.period < DAY_END,
                )
            )
        await session.commit()


# --- core data endpoints -------------------------------------------------


async def test_list_regions(client, seeded):
    resp = await client.get("/v1/regions")
    assert resp.status_code == 200
    assert {"CISO", "ERCO", "ISNE", "MISO"} <= {r["code"] for r in resp.json()}


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


async def test_history_pagination(client, seeded):
    first = await client.get(f"/v1/carbon/history?region={TEST_REGION}&limit=10")
    assert first.status_code == 200
    body = first.json()
    assert body["count"] == 10
    assert body["next_cursor"] is not None
    # Newest first.
    periods = [p["period"] for p in body["data"]]
    assert periods == sorted(periods, reverse=True)

    # Following the cursor returns strictly older rows.
    nxt = await client.get(
        f"/v1/carbon/history?region={TEST_REGION}&limit=10&cursor={body['next_cursor']}"
    )
    assert nxt.json()["data"][0]["period"] < periods[-1]


async def test_history_invalid_cursor(client, seeded):
    resp = await client.get(f"/v1/carbon/history?region={TEST_REGION}&cursor=bogus!!")
    assert resp.status_code == 400


async def test_compare_ranks_cleanest_first(client, seeded):
    resp = await client.get("/v1/carbon/compare?regions=CISO,ZZZ")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["region_code"] == "CISO"
    assert body["items"][0]["rank"] == 1
    assert "ZZZ" in body["unavailable"]  # unknown region has no data


async def test_savings_returns_fields(client, seeded):
    resp = await client.get(
        f"/v1/carbon/savings?region={TEST_REGION}&kwh=10&from_hour=0&to_hour=12"
    )
    assert resp.status_code == 200
    body = resp.json()
    # Flat synthetic mix -> equal intensities -> zero savings, but path works.
    assert body["savings_g"] == pytest.approx(
        body["from_co2_g"] - body["to_co2_g"], abs=0.01
    )
    assert body["timezone"] == "America/Los_Angeles"


# --- cross-cutting: caching, ETag, rate limiting -------------------------


async def test_etag_conditional_returns_304(client, seeded):
    resp = await client.get(f"/v1/carbon/now?region={TEST_REGION}")
    etag = resp.headers["ETag"]
    assert resp.headers["Cache-Control"].startswith("public")
    again = await client.get(
        f"/v1/carbon/now?region={TEST_REGION}", headers={"If-None-Match": etag}
    )
    assert again.status_code == 304


async def test_rate_limit_headers_present(client, seeded):
    resp = await client.get("/v1/regions")
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-RateLimit-Remaining" in resp.headers


async def test_rate_limit_429_on_exhausted_key(client, seeded):
    raw, key_hash = generate_key()
    async with SessionLocal() as session:
        session.add(
            ApiKey(name="test-tight", key_hash=key_hash, tier="test", rate_limit_per_min=1)
        )
        await session.commit()
    headers = {"X-API-Key": raw}
    first = await client.get("/v1/regions", headers=headers)
    second = await client.get("/v1/regions", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 429
    assert "Retry-After" in second.headers


async def test_invalid_api_key_401(client):
    resp = await client.get("/v1/regions", headers={"X-API-Key": "gck_bogus"})
    assert resp.status_code == 401
