"""Pydantic response models for the public API."""

from datetime import datetime

from pydantic import BaseModel


class RegionOut(BaseModel):
    code: str
    name: str
    egrid_subregion: str | None
    mapping_confidence: str
    timezone: str | None
    notes: str | None


class FuelSlice(BaseModel):
    fuel_code: str
    fuel_name: str
    mwh: float
    share: float  # 0..1 of total (clamped) generation


class HistoryPoint(BaseModel):
    period: datetime
    gco2_per_kwh: float
    total_mwh: float
    renewable_share: float
    carbon_free_share: float
    low_confidence_share: float


class HistoryOut(BaseModel):
    region_code: str
    count: int
    next_cursor: str | None
    data: list[HistoryPoint]


class CompareItem(BaseModel):
    rank: int
    region_code: str
    region_name: str
    period: datetime
    gco2_per_kwh: float
    renewable_share: float
    carbon_free_share: float


class CompareOut(BaseModel):
    requested: list[str]
    items: list[CompareItem]  # ranked cleanest -> dirtiest
    unavailable: list[str]


class SavingsOut(BaseModel):
    region_code: str
    region_name: str
    timezone: str | None
    kwh: float
    from_hour: int
    to_hour: int
    from_intensity_gco2_per_kwh: float
    to_intensity_gco2_per_kwh: float
    from_co2_g: float
    to_co2_g: float
    savings_g: float
    savings_pct: float
    basis: str
    caveats: list[str]


class ForecastPoint(BaseModel):
    period: datetime
    mean_gco2_per_kwh: float
    lower_gco2_per_kwh: float
    upper_gco2_per_kwh: float


class BacktestMetrics(BaseModel):
    mae_gco2_per_kwh: float  # primary metric (robust to near-zero solar lows)
    mape_pct: float | None  # over hours >= 10 g/kWh; null if none qualify
    holdout_hours: int
    note: str


class ForecastOut(BaseModel):
    region_code: str
    region_name: str
    model: str
    horizon_hours: int
    interval_pct: int
    trained_through: datetime
    history_hours: int
    backtest: BacktestMetrics
    data: list[ForecastPoint]
    caveats: list[str]


class CleanHour(BaseModel):
    period_utc: datetime
    period_local: str
    gco2_per_kwh: float


class CleanestHourOut(BaseModel):
    region_code: str
    region_name: str
    timezone: str | None
    horizon_hours: int
    cleanest: CleanHour
    dirtiest: CleanHour
    potential_savings_pct: float  # dirtiest -> cleanest
    ranked: list[CleanHour]  # cleanest -> dirtiest
    caveats: list[str]


class CarbonNowOut(BaseModel):
    region_code: str
    region_name: str
    egrid_subregion: str | None
    mapping_confidence: str
    zip: str | None = None
    zip_mapping_confidence: str | None = None
    period: datetime
    gco2_per_kwh: float
    total_mwh: float
    renewable_share: float
    carbon_free_share: float
    low_confidence_share: float
    fuel_mix: list[FuelSlice]
    caveats: list[str]
