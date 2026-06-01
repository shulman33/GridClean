"""Unit tests for the carbon-intensity formula (pure, no DB/network)."""

import pytest

from app.services.carbon import FuelFactor, _intensity_for_period

FACTORS = {
    "NG": FuelFactor(900.0, is_renewable=False, is_carbon_free=False, confidence="high"),
    "COL": FuelFactor(2230.0, is_renewable=False, is_carbon_free=False, confidence="high"),
    "WND": FuelFactor(0.0, is_renewable=True, is_carbon_free=True, confidence="high"),
    "NUC": FuelFactor(0.0, is_renewable=False, is_carbon_free=True, confidence="high"),
    "SUN": FuelFactor(0.0, is_renewable=True, is_carbon_free=True, confidence="high"),
    "OTH": FuelFactor(1100.0, is_renewable=False, is_carbon_free=False, confidence="low"),
}


def test_half_gas_half_wind():
    # 1000 MWh gas (900 lb/MWh) + 1000 MWh wind (0) -> 450 lb/MWh -> ~204 g/kWh
    out = _intensity_for_period({"NG": 1000, "WND": 1000}, FACTORS)
    assert out["gco2_per_kwh"] == pytest.approx(204.12, abs=0.05)
    assert out["total_mwh"] == 2000.0
    assert out["renewable_share"] == pytest.approx(0.5)
    assert out["carbon_free_share"] == pytest.approx(0.5)
    assert out["low_confidence_share"] == 0.0


def test_negatives_are_clamped():
    # SUN -50 clamps to 0 and contributes nothing; only the 100 MWh gas counts.
    out = _intensity_for_period({"SUN": -50, "NG": 100}, FACTORS)
    assert out["total_mwh"] == 100.0
    assert out["gco2_per_kwh"] == pytest.approx(408.23, abs=0.05)
    assert out["renewable_share"] == 0.0


def test_carbon_free_includes_nuclear_not_renewable():
    out = _intensity_for_period({"NUC": 1000, "WND": 1000}, FACTORS)
    assert out["gco2_per_kwh"] == 0.0
    assert out["renewable_share"] == pytest.approx(0.5)  # wind only
    assert out["carbon_free_share"] == pytest.approx(1.0)  # wind + nuclear


def test_low_confidence_share_tracks_oth():
    out = _intensity_for_period({"OTH": 500, "NG": 500}, FACTORS)
    assert out["low_confidence_share"] == pytest.approx(0.5)


def test_all_zero_returns_none():
    assert _intensity_for_period({"SUN": -5, "WND": 0}, FACTORS) is None


def test_unknown_fuel_falls_back_to_oth():
    # A fuel code not in FACTORS should use the OTH factor (1100 lb/MWh).
    out = _intensity_for_period({"MYSTERY": 1000}, FACTORS)
    assert out["gco2_per_kwh"] == pytest.approx(498.95, abs=0.05)
    assert out["low_confidence_share"] == pytest.approx(1.0)
