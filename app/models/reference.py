"""Static reference tables: grid regions, emission factors, ZIP crosswalk.

These are seeded (see app/seed/) rather than ingested live. The geography
reconciliation story (EIA balancing authority <-> eGRID subregion) lives here
in `Region.egrid_subregion` + `mapping_confidence`. See docs/SPEC.md §4.3.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# Allowed confidence levels for any geographic mapping.
CONFIDENCE_VALUES = ("exact", "dominant", "approximate")


class Region(Base):
    """A grid region keyed by its EIA balancing-authority (BA) code."""

    __tablename__ = "regions"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)  # e.g. CISO
    name: Mapped[str] = mapped_column(String(128))
    # eGRID subregion this BA maps to (e.g. CAMX). The fusion's geographic join.
    egrid_subregion: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # How well the BA aligns to that single subregion. Surfaced in responses.
    mapping_confidence: Mapped[str] = mapped_column(String(16), default="dominant")
    timezone: Mapped[str | None] = mapped_column(String(48), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(256), nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"mapping_confidence IN {CONFIDENCE_VALUES}",
            name="ck_region_confidence",
        ),
    )


class EmissionFactor(Base):
    """CO2 output emission rate (lb CO2 / MWh) for a fuel type.

    v1 uses national EPA/eGRID-derived fuel-level rates (one row per fuel per
    version). Subregion-specific rates are a v2 refinement (see SPEC §4.3).
    `confidence='low'` flags fuels whose factor is uncertain (GEO, OTH).
    """

    __tablename__ = "emission_factors"

    id: Mapped[int] = mapped_column(primary_key=True)
    fuel_code: Mapped[str] = mapped_column(String(8))  # COL, NG, NUC, ...
    fuel_name: Mapped[str] = mapped_column(String(64))
    co2_lb_per_mwh: Mapped[float] = mapped_column(Numeric(10, 2))
    is_renewable: Mapped[bool] = mapped_column(default=False)
    is_carbon_free: Mapped[bool] = mapped_column(default=False)
    confidence: Mapped[str] = mapped_column(String(8), default="high")  # high | low
    version: Mapped[str] = mapped_column(String(32), default="v1-seed")
    source: Mapped[str | None] = mapped_column(String(256), nullable=True)

    __table_args__ = (
        UniqueConstraint("fuel_code", "version", name="uq_emission_fuel_version"),
        CheckConstraint("confidence IN ('high','low')", name="ck_factor_confidence"),
    )


class ZipRegion(Base):
    """ZIP code -> grid region (BA) crosswalk for user-facing `?zip=` lookups."""

    __tablename__ = "zip_region"

    zip: Mapped[str] = mapped_column(String(5), primary_key=True)
    region_code: Mapped[str] = mapped_column(ForeignKey("regions.code"))
    mapping_confidence: Mapped[str] = mapped_column(String(16), default="dominant")
    notes: Mapped[str | None] = mapped_column(String(256), nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"mapping_confidence IN {CONFIDENCE_VALUES}",
            name="ck_zip_confidence",
        ),
    )
