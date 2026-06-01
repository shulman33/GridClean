"""Unit tests for EIA parsing helpers (no network)."""

from datetime import UTC

from app.services.eia import KNOWN_FUELS, _parse_period


def test_parse_period_is_utc():
    dt = _parse_period("2026-06-01T06")
    assert dt.year == 2026 and dt.month == 6 and dt.day == 1 and dt.hour == 6
    assert dt.tzinfo == UTC


def test_known_fuels_cover_observed_set():
    # The fuels we actually saw from EIA for CISO must all be recognized.
    observed = {"COL", "GEO", "NG", "NUC", "OIL", "OTH", "SUN", "WAT", "WND"}
    assert observed <= KNOWN_FUELS
