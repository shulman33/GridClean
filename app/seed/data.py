"""Seed reference data: regions, emission factors, ZIP crosswalk.

Kept small and curated for v1 (the ~15 largest balancing authorities by
population served, plus representative ZIPs). The full EPA Power Profiler
ZIP->subregion file (~40k ZIPs) can be loaded later via the same loader.
"""

# --- Regions: EIA balancing authority -> eGRID subregion -----------------
# mapping_confidence reflects how cleanly the BA maps to ONE eGRID subregion.
# Multi-subregion BAs (PJM, MISO, SWPP) are honestly flagged.
REGIONS = [
    # code,  name,                                  subregion, confidence,    tz,                  notes
    ("CISO", "California ISO",                       "CAMX", "exact",       "America/Los_Angeles", None),
    ("ERCO", "Electric Reliability Council of Texas","ERCT", "exact",       "America/Chicago",     None),
    ("ISNE", "ISO New England",                      "NEWE", "exact",       "America/New_York",    None),
    ("NYIS", "New York ISO",                         "NYCW", "dominant",    "America/New_York",    "NY spans NYCW/NYUP/NYLI; using downstate-dominant"),
    ("PJM",  "PJM Interconnection",                  "RFCE", "dominant",    "America/New_York",    "Spans RFCE/RFCW/SRVC; using eastern-dominant"),
    ("MISO", "Midcontinent ISO",                     "MROW", "approximate", "America/Chicago",     "Spans many subregions across the Midwest/South"),
    ("SWPP", "Southwest Power Pool",                 "SPNO", "approximate", "America/Chicago",     "Spans SPNO/SPSO"),
    ("SOCO", "Southern Company",                     "SRSO", "dominant",    "America/New_York",    None),
    ("FPL",  "Florida Power & Light",                "FRCC", "dominant",    "America/New_York",    None),
    ("DUK",  "Duke Energy Carolinas",                "SRVC", "dominant",    "America/New_York",    None),
    ("TVA",  "Tennessee Valley Authority",           "SRTV", "dominant",    "America/Chicago",     None),
    ("BPAT", "Bonneville Power Administration",       "NWPP", "dominant",    "America/Los_Angeles", None),
    ("AZPS", "Arizona Public Service",               "AZNM", "dominant",    "America/Phoenix",     None),
    ("PSCO", "Public Service Co. of Colorado",       "RMPA", "dominant",    "America/Denver",      None),
    ("LDWP", "LA Dept. of Water & Power",            "CAMX", "dominant",    "America/Los_Angeles", None),
]

# --- Emission factors: lb CO2 / MWh (output-based) -----------------------
# v1 national fuel-level rates. Fossil values from EPA/EIA published output
# emission rates; carbon-free generation is ~0 operational CO2. GEO and OTH
# are genuinely uncertain (variable/mixed) and flagged confidence='low'.
#   fuel_code, fuel_name,    lb_co2/MWh, renewable, carbon_free, confidence
EMISSION_FACTORS = [
    ("COL", "Coal",         2230.0, False, False, "high"),
    ("NG",  "Natural Gas",   900.0, False, False, "high"),
    ("OIL", "Petroleum",    1672.0, False, False, "high"),
    ("NUC", "Nuclear",         0.0, False, True,  "high"),
    ("WAT", "Hydro",           0.0, True,  True,  "high"),
    ("WND", "Wind",            0.0, True,  True,  "high"),
    ("SUN", "Solar",           0.0, True,  True,  "high"),
    ("GEO", "Geothermal",    120.0, True,  True,  "low"),   # minor variable direct CO2
    ("OTH", "Other",        1100.0, False, False, "low"),   # mixed/unspecified
]
EMISSION_FACTOR_SOURCE = (
    "EPA/EIA published fuel-level CO2 output emission rates (v1 national; "
    "subregion-specific eGRID rates are a v2 refinement)."
)

# --- ZIP -> region crosswalk (curated representative set) ----------------
# Several entries intentionally capture nuance: LA city is served by LDWP, not
# CISO; Seattle sits in the BPA footprint; these carry lower confidence.
#   zip,    region, confidence,    notes
ZIP_REGION = [
    ("10001", "NYIS", "dominant",    "Manhattan"),
    ("11201", "NYIS", "dominant",    "Brooklyn"),
    ("94103", "CISO", "exact",       "San Francisco"),
    ("90012", "LDWP", "dominant",    "Downtown LA — served by LADWP, not CISO"),
    ("90210", "CISO", "approximate", "Beverly Hills — SCE territory within CISO"),
    ("77002", "ERCO", "exact",       "Houston"),
    ("75201", "ERCO", "exact",       "Dallas"),
    ("78701", "ERCO", "dominant",    "Austin — Austin Energy within ERCOT"),
    ("60601", "PJM",  "dominant",    "Chicago — ComEd within PJM"),
    ("02108", "ISNE", "exact",       "Boston"),
    ("33101", "FPL",  "dominant",    "Miami"),
    ("30303", "SOCO", "dominant",    "Atlanta"),
    ("85001", "AZPS", "dominant",    "Phoenix"),
    ("98101", "BPAT", "approximate", "Seattle — Seattle City Light in BPA footprint"),
    ("80202", "PSCO", "dominant",    "Denver"),
    ("28202", "DUK",  "dominant",    "Charlotte"),
    ("37201", "TVA",  "dominant",    "Nashville"),
]
