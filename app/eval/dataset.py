"""Text-to-SQL eval set: (question, reference_sql) pairs.

Scored by execution match (BIRD-style): run the model's SQL and the reference
SQL, compare result sets. Reference queries hit the curated ai_* views so they
run under the same read-only role. Add cases freely — coverage is the point.
"""

EVALS: list[tuple[str, str]] = [
    (
        "What is the average carbon intensity for CISO over the last 7 days?",
        "SELECT AVG(gco2_per_kwh) FROM ai_carbon_intensity "
        "WHERE region_code='CISO' AND period >= now() - interval '7 days'",
    ),
    (
        "How many grid regions are there?",
        "SELECT count(*) FROM ai_regions",
    ),
    (
        "Which regions have an approximate mapping confidence?",
        "SELECT code FROM ai_regions WHERE mapping_confidence='approximate'",
    ),
    (
        "What is the highest carbon intensity PJM has hit in the last 7 days?",
        "SELECT max(gco2_per_kwh) FROM ai_carbon_intensity "
        "WHERE region_code='PJM' AND period >= now() - interval '7 days'",
    ),
    (
        "What is the average renewable share for CISO over the last 24 hours?",
        "SELECT avg(renewable_share) FROM ai_carbon_intensity "
        "WHERE region_code='CISO' AND period >= now() - interval '24 hours'",
    ),
    (
        "How much total wind generation did ERCOT produce in the last 7 days?",
        "SELECT sum(mwh) FROM ai_fuel_generation "
        "WHERE region_code='ERCO' AND fuel_code='WND' AND period >= now() - interval '7 days'",
    ),
    (
        "What is the lowest carbon intensity ever recorded for BPAT?",
        "SELECT min(gco2_per_kwh) FROM ai_carbon_intensity WHERE region_code='BPAT'",
    ),
    (
        "List the distinct fuel codes reported for CISO.",
        "SELECT DISTINCT fuel_code FROM ai_fuel_generation WHERE region_code='CISO'",
    ),
    (
        "What is the average carbon intensity across all regions in the last 24 hours?",
        "SELECT avg(gco2_per_kwh) FROM ai_carbon_intensity "
        "WHERE period >= now() - interval '24 hours'",
    ),
    (
        "How many hours of data do we have for ERCOT?",
        "SELECT count(*) FROM ai_carbon_intensity WHERE region_code='ERCO'",
    ),
    (
        "What is the average total generation for MISO over the last 7 days?",
        "SELECT avg(total_mwh) FROM ai_carbon_intensity "
        "WHERE region_code='MISO' AND period >= now() - interval '7 days'",
    ),
    (
        "Which region had the single highest carbon intensity in the last 3 days?",
        "SELECT region_code FROM ai_carbon_intensity "
        "WHERE period >= now() - interval '3 days' ORDER BY gco2_per_kwh DESC LIMIT 1",
    ),
]
