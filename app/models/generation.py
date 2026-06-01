"""Time-series tables (TimescaleDB hypertables).

`generation_hourly` is the live feed ingested from EIA-930 (one row per
region/hour/fuel). `carbon_intensity_hourly` is derived from it joined to
emission factors (one row per region/hour). See app/services/carbon.py.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class GenerationHourly(Base):
    """Hourly generation by fuel type for a region, from EIA-930."""

    __tablename__ = "generation_hourly"

    region_code: Mapped[str] = mapped_column(
        ForeignKey("regions.code"), primary_key=True
    )
    period: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    fuel_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    mwh: Mapped[float] = mapped_column(Numeric(14, 2))


class CarbonIntensityHourly(Base):
    """Derived carbon intensity (gCO2/kWh) per region per hour."""

    __tablename__ = "carbon_intensity_hourly"

    region_code: Mapped[str] = mapped_column(
        ForeignKey("regions.code"), primary_key=True
    )
    period: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    gco2_per_kwh: Mapped[float] = mapped_column(Numeric(10, 2))
    total_mwh: Mapped[float] = mapped_column(Numeric(14, 2))
    renewable_share: Mapped[float] = mapped_column(Numeric(5, 4))  # 0..1
    carbon_free_share: Mapped[float] = mapped_column(Numeric(5, 4))  # 0..1
    # Fraction of generation from fuels with low-confidence factors (GEO/OTH).
    low_confidence_share: Mapped[float] = mapped_column(Numeric(5, 4))
