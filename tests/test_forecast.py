"""Forecast tests: model math (no DB) + endpoint integration (synthetic region).

Uses a dedicated region code 'TST' that real EIA ingests never touch, so the
synthetic series can't collide with any locally-ingested data.
"""

import math
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models import CarbonIntensityHourly, Region
from app.services.forecast import _backtest, _fit_and_predict

HISTORY_HOURS = 240  # 10 days


def _daily_series(n: int) -> pd.Series:
    idx = pd.date_range("2099-01-01", periods=n, freq="h", tz="UTC")
    vals = [150 + 120 * math.cos((h % 24 - 19) / 24 * 2 * math.pi) for h in range(n)]
    return pd.Series(vals, index=idx)


# --- model math (pure, no DB) -------------------------------------------


def test_fit_predict_returns_ordered_intervals():
    frame = _fit_and_predict(_daily_series(HISTORY_HOURS), horizon=12, alpha=0.2)
    assert len(frame) == 12
    assert (frame["pi_lower"] <= frame["mean"] + 1e-6).all()
    assert (frame["mean"] <= frame["pi_upper"] + 1e-6).all()


def test_backtest_metrics_are_finite():
    bt = _backtest(_daily_series(HISTORY_HOURS), horizon=12, alpha=0.2)
    assert bt.mae_gco2_per_kwh >= 0 and math.isfinite(bt.mae_gco2_per_kwh)
    assert bt.holdout_hours == 12
    # On a clean daily sinusoid the model should track well.
    assert bt.mae_gco2_per_kwh < 30


# --- endpoint integration -----------------------------------------------


@pytest.fixture
async def fc_region():
    from app.seed.load import seed_all

    async with SessionLocal() as session:
        await seed_all(session)
        await session.merge(
            Region(
                code="TST",
                name="Test Grid",
                egrid_subregion="TEST",
                mapping_confidence="exact",
                timezone="America/Los_Angeles",
            )
        )
        await session.flush()
        base = datetime(2099, 1, 1, tzinfo=UTC)
        rows = []
        for h in range(HISTORY_HOURS):
            val = max(150 + 120 * math.cos((h % 24 - 19) / 24 * 2 * math.pi), 5.0)
            rows.append(
                CarbonIntensityHourly(
                    region_code="TST",
                    period=base + timedelta(hours=h),
                    gco2_per_kwh=round(val, 2),
                    total_mwh=10000,
                    renewable_share=0.5,
                    carbon_free_share=0.6,
                    low_confidence_share=0.1,
                )
            )
        session.add_all(rows)
        await session.commit()
    yield "TST"
    async with SessionLocal() as session:
        await session.execute(
            delete(CarbonIntensityHourly).where(CarbonIntensityHourly.region_code == "TST")
        )
        await session.execute(delete(Region).where(Region.code == "TST"))
        await session.commit()


async def test_forecast_endpoint(client, fc_region):
    resp = await client.get("/v1/carbon/forecast?region=TST&horizon=6&interval=80")
    assert resp.status_code == 200
    body = resp.json()
    assert body["horizon_hours"] == 6
    assert len(body["data"]) == 6
    assert body["interval_pct"] == 80
    assert body["backtest"]["mae_gco2_per_kwh"] >= 0
    for p in body["data"]:
        assert p["lower_gco2_per_kwh"] <= p["mean_gco2_per_kwh"] <= p["upper_gco2_per_kwh"]


async def test_cleanest_hour_endpoint(client, fc_region):
    resp = await client.get("/v1/carbon/cleanest-hour?region=TST&horizon=24")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cleanest"]["gco2_per_kwh"] <= body["dirtiest"]["gco2_per_kwh"]
    assert body["potential_savings_pct"] >= 0
    ranked = [h["gco2_per_kwh"] for h in body["ranked"]]
    assert ranked == sorted(ranked)
    assert "PST" in body["cleanest"]["period_local"] or "PDT" in body["cleanest"]["period_local"]


async def test_forecast_unknown_region_404(client, fc_region):
    assert (await client.get("/v1/carbon/forecast?region=ZZZ")).status_code == 404
