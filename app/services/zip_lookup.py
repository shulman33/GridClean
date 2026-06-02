"""Nationwide ZIP -> balancing-authority fallback via 3-digit prefix.

The curated `zip_region` table holds a handful of city-accurate ZIPs (confidence
`exact`/`dominant`). For every *other* US ZIP we fall back to its 3-digit prefix
(the "ZIP3" / sectional-center), which is geographic and maps cleanly to a single
state — states own contiguous prefix ranges. We then map each state to the
balancing authority (one of our 15 tracked BAs) that dominantly serves it.

Because the ranges below blanket the assigned ZIP3 space, *every* real US ZIP
resolves to a region — except Alaska, Hawaii, US territories, and military
prefixes, which no tracked BA serves and which return None ("not covered").

Accuracy: this is a state-level approximation with a few ZIP3 overrides for
well-known intra-state splits (LA city -> LADWP, the Texas Panhandle -> SPP,
El Paso -> WECC). Every prefix-derived match is surfaced as `approximate`
confidence in the response, consistent with the app's mapping-confidence ethos.
A state-level pick is necessarily coarse for BAs that span many states (PJM,
MISO, SWPP) — the goal is a reasonable, honestly-flagged region, not a precise
service-territory lookup.
"""

# Checked BEFORE the base ranges; (lo, hi, region) inclusive on the ZIP3 int.
_OVERRIDES: list[tuple[int, int, str]] = [
    (900, 901, "LDWP"),  # City of Los Angeles — LADWP, not CISO
    (790, 794, "SWPP"),  # Texas Panhandle / Lubbock — SPP, not ERCOT
    (798, 799, "AZPS"),  # El Paso — WECC; nearest tracked BA (AZNM footprint)
]

# Base state ranges over the ZIP3 space (000-999). region=None => not covered.
# Ordered low->high; lookup returns the first containing range.
_PREFIX_RANGES: list[tuple[int, int, str | None]] = [
    (5, 5, "NYIS"),      # 005 Holtsville, NY
    (6, 9, None),        # 006-009 Puerto Rico / US Virgin Islands
    (10, 27, "ISNE"),    # Massachusetts
    (28, 29, "ISNE"),    # Rhode Island
    (30, 38, "ISNE"),    # New Hampshire
    (39, 49, "ISNE"),    # Maine
    (50, 59, "ISNE"),    # Vermont
    (60, 69, "ISNE"),    # Connecticut
    (70, 89, "PJM"),     # New Jersey
    (90, 99, None),      # 090-098 military (AE/AA)
    (100, 149, "NYIS"),  # New York
    (150, 196, "PJM"),   # Pennsylvania
    (197, 199, "PJM"),   # Delaware
    (200, 205, "PJM"),   # Washington, DC
    (206, 219, "PJM"),   # Maryland
    (220, 246, "PJM"),   # Virginia
    (247, 268, "PJM"),   # West Virginia
    (270, 289, "DUK"),   # North Carolina
    (290, 299, "DUK"),   # South Carolina
    (300, 319, "SOCO"),  # Georgia
    (320, 349, "FPL"),   # Florida
    (350, 369, "SOCO"),  # Alabama
    (370, 385, "TVA"),   # Tennessee
    (386, 397, "MISO"),  # Mississippi (Entergy MS)
    (398, 399, "SOCO"),  # Georgia (Savannah area)
    (400, 427, "TVA"),   # Kentucky (split; TVA-adjacent approximation)
    (430, 459, "PJM"),   # Ohio
    (460, 479, "MISO"),  # Indiana
    (480, 499, "MISO"),  # Michigan
    (500, 528, "MISO"),  # Iowa
    (530, 549, "MISO"),  # Wisconsin
    (550, 567, "MISO"),  # Minnesota
    (570, 577, "SWPP"),  # South Dakota
    (580, 588, "SWPP"),  # North Dakota
    (590, 599, "BPAT"),  # Montana
    (600, 629, "PJM"),   # Illinois (ComEd / Chicago)
    (630, 658, "MISO"),  # Missouri (Ameren)
    (660, 679, "SWPP"),  # Kansas
    (680, 693, "SWPP"),  # Nebraska
    (700, 714, "MISO"),  # Louisiana (Entergy)
    (716, 729, "MISO"),  # Arkansas (Entergy)
    (730, 749, "SWPP"),  # Oklahoma
    (750, 799, "ERCO"),  # Texas (overrides carve out Panhandle/El Paso)
    (800, 816, "PSCO"),  # Colorado
    (820, 831, "PSCO"),  # Wyoming (approximation)
    (832, 838, "BPAT"),  # Idaho
    (840, 847, "PSCO"),  # Utah (approximation)
    (850, 865, "AZPS"),  # Arizona
    (870, 885, "AZPS"),  # New Mexico (+ El Paso 885; AZNM footprint)
    (889, 898, "CISO"),  # Nevada (approximation)
    (900, 961, "CISO"),  # California
    (962, 966, None),    # 962-966 military (AP)
    (967, 968, None),    # Hawaii
    (969, 969, None),    # Guam / Pacific territories
    (970, 979, "BPAT"),  # Oregon
    (980, 994, "BPAT"),  # Washington
    (995, 999, None),    # Alaska
]


def region_for_zip(zip_code: str) -> str | None:
    """Map a US ZIP to a tracked balancing-authority region via its ZIP3 prefix.

    Returns a region code, or None if the ZIP is outside the tracked grids
    (Alaska, Hawaii, US territories, military, or an unassigned prefix).
    """
    if not zip_code or len(zip_code) < 3 or not zip_code[:3].isdigit():
        return None
    p = int(zip_code[:3])
    for lo, hi, region in _OVERRIDES:
        if lo <= p <= hi:
            return region
    for lo, hi, region in _PREFIX_RANGES:
        if lo <= p <= hi:
            return region
    return None
