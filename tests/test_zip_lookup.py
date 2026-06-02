"""ZIP3-prefix fallback resolver (pure) + end-to-end via /now."""

import pytest

from app.services.zip_lookup import region_for_zip


@pytest.mark.parametrize(
    "zip_code,expected",
    [
        ("07039", "PJM"),    # Livingston, NJ — the originally-reported miss
        ("07666", "PJM"),    # Teaneck, NJ
        ("02134", "ISNE"),   # Boston, MA
        ("95014", "CISO"),   # Cupertino, CA (not curated)
        ("90001", "LDWP"),   # Los Angeles city — override
        ("79101", "SWPP"),   # Amarillo, TX Panhandle — override
        ("79901", "AZPS"),   # El Paso, TX — override (WECC)
        ("76101", "ERCO"),   # Fort Worth, TX — base Texas
        ("60601", "PJM"),    # Chicago, IL
        ("33101", "FPL"),    # Miami, FL
    ],
)
def test_prefix_maps_to_region(zip_code, expected):
    assert region_for_zip(zip_code) == expected


@pytest.mark.parametrize("zip_code", ["96801", "99501", "00000", "006xx", "", "9"])
def test_not_covered_or_invalid_returns_none(zip_code):
    # Honolulu (HI), Anchorage (AK), unassigned, malformed -> not covered.
    assert region_for_zip(zip_code) is None
