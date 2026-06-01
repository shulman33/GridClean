"""Carbon-intensity forecasting (statsmodels ETS, additive 24h seasonality).

Carbon intensity has a strong daily cycle (solar midday, fossil evening), so an
exponential-smoothing model with a 24-hour seasonal component captures most of
the signal. We return prediction intervals and a backtested error metric.

Metric note: MAPE is reported but is inflated for very clean grids (CISO dips
near 0 g/kWh at solar peak, so dividing by tiny actuals blows up the percentage).
MAE (absolute g/kWh) is the honest primary metric.
"""

import asyncio
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

from app.models import CarbonIntensityHourly, Region
from app.schemas import (
    BacktestMetrics,
    CleanestHourOut,
    CleanHour,
    ForecastOut,
    ForecastPoint,
)

SEASONAL_PERIODS = 24
MIN_HISTORY_HOURS = 72  # need a few days for a stable daily season
MODEL_NAME = "ETS(add, seasonal=24)"
_MAPE_FLOOR = 10.0  # ignore sub-10 g/kWh actuals when computing MAPE


async def _load_series(session: AsyncSession, region_code: str) -> pd.Series:
    rows = (
        await session.execute(
            select(CarbonIntensityHourly.period, CarbonIntensityHourly.gco2_per_kwh)
            .where(CarbonIntensityHourly.region_code == region_code)
            .order_by(CarbonIntensityHourly.period.asc())
        )
    ).all()
    if len(rows) < MIN_HISTORY_HOURS:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Insufficient history for '{region_code}' "
                f"({len(rows)}h; need {MIN_HISTORY_HOURS}h). Ingest more data."
            ),
        )
    idx = pd.DatetimeIndex([r[0] for r in rows])
    series = pd.Series([float(r[1]) for r in rows], index=idx).sort_index()
    series = series[~series.index.duplicated(keep="last")]
    # Regular hourly spacing; interpolate any gaps so ETS sees a clean cadence.
    return series.asfreq("h").interpolate()


def _fit_and_predict(series: pd.Series, horizon: int, alpha: float):
    """Blocking statsmodels work; run via asyncio.to_thread."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ETSModel(
            series, error="add", trend=None, seasonal="add",
            seasonal_periods=SEASONAL_PERIODS,
        ).fit(disp=False)
        frame = model.get_prediction(
            start=len(series), end=len(series) + horizon - 1
        ).summary_frame(alpha=alpha)
    return frame


def _backtest(series: pd.Series, horizon: int, alpha: float) -> BacktestMetrics:
    holdout = min(horizon, max(1, len(series) // 5))
    train, test = series.iloc[:-holdout], series.iloc[-holdout:]
    frame = _fit_and_predict(train, holdout, alpha)
    pred = np.clip(frame["mean"].to_numpy(), 0.0, None)
    actual = test.to_numpy()

    mae = float(np.mean(np.abs(actual - pred)))
    mask = actual >= _MAPE_FLOOR
    mape = (
        float(np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask])) * 100)
        if mask.any()
        else None
    )
    return BacktestMetrics(
        mae_gco2_per_kwh=round(mae, 1),
        mape_pct=round(mape, 1) if mape is not None else None,
        holdout_hours=int(holdout),
        note=(
            "MAE is the primary metric. MAPE is computed only over hours "
            f">= {int(_MAPE_FLOOR)} g/kWh (near-zero solar lows inflate it)."
        ),
    )


async def forecast_region(
    session: AsyncSession, region_code: str, horizon: int = 24, interval_pct: int = 80
) -> ForecastOut:
    region_row = await session.get(Region, region_code)
    if region_row is None:
        raise HTTPException(status_code=404, detail=f"Unknown region '{region_code}'.")

    series = await _load_series(session, region_code)
    alpha = 1.0 - interval_pct / 100.0

    frame, backtest = await asyncio.gather(
        asyncio.to_thread(_fit_and_predict, series, horizon, alpha),
        asyncio.to_thread(_backtest, series, horizon, alpha),
    )

    points = [
        ForecastPoint(
            period=ts.to_pydatetime(),
            mean_gco2_per_kwh=round(max(row["mean"], 0.0), 1),
            lower_gco2_per_kwh=round(max(row["pi_lower"], 0.0), 1),
            upper_gco2_per_kwh=round(max(row["pi_upper"], 0.0), 1),
        )
        for ts, row in frame.iterrows()
    ]

    return ForecastOut(
        region_code=region_code,
        region_name=region_row.name,
        model=MODEL_NAME,
        horizon_hours=horizon,
        interval_pct=interval_pct,
        trained_through=series.index[-1].to_pydatetime(),
        history_hours=len(series),
        backtest=backtest,
        data=points,
        caveats=[
            "Forecast extrapolates the recent daily cycle; weather shifts can move it.",
            "Average (not marginal) emissions.",
            (
                f"Backtest MAE {backtest.mae_gco2_per_kwh} g/kWh "
                f"over a {backtest.holdout_hours}h holdout."
            ),
        ],
    )


async def cleanest_hour(
    session: AsyncSession, region_row: Region, horizon: int = 24
) -> CleanestHourOut:
    forecast = await forecast_region(session, region_row.code, horizon=horizon)
    tz = ZoneInfo(region_row.timezone) if region_row.timezone else ZoneInfo("UTC")

    def to_clean(p: ForecastPoint) -> CleanHour:
        local: datetime = p.period.astimezone(tz)
        return CleanHour(
            period_utc=p.period,
            period_local=local.strftime("%Y-%m-%d %H:%M %Z"),
            gco2_per_kwh=p.mean_gco2_per_kwh,
        )

    ranked_points = sorted(forecast.data, key=lambda p: p.mean_gco2_per_kwh)
    cleanest = to_clean(ranked_points[0])
    dirtiest = to_clean(ranked_points[-1])
    savings = (
        round((1 - cleanest.gco2_per_kwh / dirtiest.gco2_per_kwh) * 100, 1)
        if dirtiest.gco2_per_kwh > 0
        else 0.0
    )

    return CleanestHourOut(
        region_code=region_row.code,
        region_name=region_row.name,
        timezone=region_row.timezone,
        horizon_hours=horizon,
        cleanest=cleanest,
        dirtiest=dirtiest,
        potential_savings_pct=savings,
        ranked=[to_clean(p) for p in ranked_points],
        caveats=[
            f"Based on a {horizon}h forecast ({MODEL_NAME}); see /forecast for intervals.",
            "Local times use the region's timezone.",
        ],
    )
