"""Natural-language -> SQL via Claude (forced structured tool call).

The schema description + rules + few-shot examples are a stable system prefix
(cached). The model is forced to emit SQL through the `emit_sql` tool so we get
a typed object, never prose. Validation/execution happen downstream — the model
is told the rules but is never trusted to enforce them.
"""

import anthropic

from app.config import get_settings

# Curated, documented surface the model may query. Mirrors the ai_* views.
SCHEMA_CONTEXT = """\
You translate questions about U.S. electricity-grid carbon intensity into a
single read-only PostgreSQL SELECT. You may ONLY query these views:

-- ai_carbon_intensity: hourly carbon intensity per grid region
--   region_code text         e.g. 'CISO', 'ERCO', 'PJM' (balancing authority)
--   region_name text         e.g. 'California ISO'
--   egrid_subregion text     EPA eGRID subregion, e.g. 'CAMX'
--   period timestamptz       hourly, UTC
--   gco2_per_kwh numeric     grams CO2 per kWh (the headline metric)
--   total_mwh numeric        total generation that hour
--   renewable_share numeric  0..1 (wind+solar+hydro+geothermal)
--   carbon_free_share numeric 0..1 (renewables + nuclear)

-- ai_regions: one row per region
--   code text, name text, egrid_subregion text,
--   mapping_confidence text ('exact'|'dominant'|'approximate'), timezone text

-- ai_fuel_generation: hourly generation by fuel type per region
--   region_code text, region_name text, period timestamptz,
--   fuel_code text (COL,NG,NUC,OIL,WAT,WND,SUN,GEO,OTH), fuel_name text, mwh numeric

Rules:
- Output ONE SELECT statement only. No INSERT/UPDATE/DELETE/DDL.
- Reference only the three views above. Never reference base tables or catalogs.
- Region codes are uppercase balancing-authority codes (CISO, ERCO, PJM, ...).
- Periods are UTC timestamps; use intervals like period >= now() - interval '7 days'.
- IMPORTANT: the data LAGS real time by several hours. For "now"/"current"/
  "right now"/"latest", use the most recent available row per region via
  SELECT DISTINCT ON (region_code) ... ORDER BY region_code, period DESC.
  Do NOT filter "now" to a short recent window (e.g. last 1-6 hours) — that can
  exclude the lagged data and return nothing.
- "cleanest" = lowest gco2_per_kwh; "dirtiest" = highest.
- Always include a sensible LIMIT.

Examples:
Q: What was the average carbon intensity for CISO over the last 7 days?
SQL: SELECT AVG(gco2_per_kwh) AS avg_gco2_per_kwh FROM ai_carbon_intensity
     WHERE region_code = 'CISO' AND period >= now() - interval '7 days';

Q: Which 3 regions are cleanest right now?
SQL: SELECT region_code, gco2_per_kwh FROM (
       SELECT DISTINCT ON (region_code) region_code, gco2_per_kwh, period
       FROM ai_carbon_intensity ORDER BY region_code, period DESC
     ) latest ORDER BY gco2_per_kwh ASC LIMIT 3;

Q: How much wind generation did ERCOT have yesterday?
SQL: SELECT SUM(mwh) AS wind_mwh FROM ai_fuel_generation
     WHERE region_code = 'ERCO' AND fuel_code = 'WND'
       AND period >= now() - interval '1 day';
"""

EMIT_SQL_TOOL = {
    "name": "emit_sql",
    "description": "Return a single read-only PostgreSQL SELECT answering the question.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "One read-only SELECT statement."},
            "explanation": {
                "type": "string",
                "description": "One sentence: what the query returns.",
            },
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["sql", "explanation", "confidence"],
        "additionalProperties": False,
    },
}


async def generate_sql(question: str, repair_error: str | None = None) -> dict:
    """Ask Claude for SQL. Returns {sql, explanation, confidence}."""
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    user = question
    if repair_error:
        user = (
            f"{question}\n\nYour previous SQL failed with this database error:\n"
            f"{repair_error}\nReturn corrected SQL."
        )

    message = await client.messages.create(
        model=settings.ai_model,
        max_tokens=1024,
        system=[{"type": "text", "text": SCHEMA_CONTEXT, "cache_control": {"type": "ephemeral"}}],
        tools=[EMIT_SQL_TOOL],
        tool_choice={"type": "tool", "name": "emit_sql"},
        messages=[{"role": "user", "content": user}],
    )
    for block in message.content:
        if block.type == "tool_use":
            return block.input  # validated by the tool schema
    raise RuntimeError("Model did not return SQL.")
