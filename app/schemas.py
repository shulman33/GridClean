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
