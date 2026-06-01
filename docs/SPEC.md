# GridClean — Technical Specification

> Live carbon intensity of electricity, by location. A data-fusion API with a guardrailed AI layer.

**Status:** Draft v1 — pre-implementation
**Owner:** Sam Shulman
**Last updated:** 2026-06-01

---

## 1. Elevator pitch

GridClean answers a question neither of its data sources can answer alone:

> *"How many grams of CO₂ does one kilowatt-hour of electricity emit right now, where I live — and when today is the cleanest time to run a big load?"*

The U.S. EIA publishes the **live fuel mix** of each regional grid (how many MWh are coming from coal vs. gas vs. wind vs. solar, updated hourly) but says nothing about emissions. The EPA's eGRID dataset publishes **emission factors per fuel type** (lb CO₂ per MWh) but contains no live data. GridClean joins them on fuel type and geography to compute **live grams-CO₂-per-kWh** for the actual grid serving a given ZIP code — the exact metric a company like WattTime sells commercially.

On top of that data API sits a deliberately small, well-engineered **AI layer**: a guardrailed natural-language query endpoint, LLM-narrated insights over computed statistics, and a time-series forecast of the next 24 hours of carbon intensity.

---

## 2. Goals & non-goals

### Goals
- Demonstrate **data-engineering judgment**: a real ETL join across a live feed (EIA), a static reference table (eGRID), and a geographic crosswalk (ZIP → grid region), reconciling mismatched geographies.
- Demonstrate **production API maturity**: cursor pagination, rate limiting with metrics, caching with intent, migrations, observability, tests, CI/CD, a live deployment.
- Demonstrate **AI-engineering maturity**: not a ChatGPT wrapper — schema-grounded text-to-SQL behind hard DB-level guardrails, compute-then-narrate insights, and a forecast with honest confidence intervals, all backed by an **eval suite**.
- Be **explainable in one interview sentence** and defensible under follow-up questions.

### Non-goals
- Not a real-time (sub-hourly) system. EIA-930 is hourly; that's our floor.
- Not marginal-emissions modeling (what WattTime's premium product does). We compute **average** emission intensity from the reported fuel mix. We will state this limitation explicitly.
- Not nationwide sub-ZIP precision. Grid regions are large; we map ZIP → balancing authority / eGRID subregion, not ZIP → power plant.
- Not a commercial product. Free/open data only, with attribution.

---

## 3. Data sources

| Source | What it provides | Access | License |
|---|---|---|---|
| **EIA-930** (Hourly Electric Grid Monitor) | Hourly electricity generation by fuel type, per balancing authority (BA). Demand, interchange too. | REST API at `api.eia.gov`, **free API key** | U.S. Gov, public (attribute EIA) |
| **EPA eGRID** | Emission rates (lb CO₂, CH₄, N₂O, NOx, SO₂ per MWh) by fuel type and by subregion. Annual. | Bulk download (Excel/CSV) | U.S. Gov, public domain |
| **ZIP → grid region crosswalk** | Maps a ZIP code to its eGRID subregion / balancing authority. | EPA Power Profiler ZIP mapping + Census ZCTA data; bulk | Public |

### 3.1 EIA-930 detail
- Endpoint family: `https://api.eia.gov/v2/electricity/rto/fuel-type-data/`
- Returns hourly MWh of generation, broken into fuel-type buckets. EIA's reported fuel-type categories (the `fueltype` dimension): **COL** (coal), **NG** (natural gas), **NUC** (nuclear), **OIL** (petroleum), **WAT** (hydro), **WND** (wind), **SUN** (solar), **OTH** (other).
- Keyed by **`respondent`** = balancing authority code (e.g., `CISO`, `ERCO`, `PJM`, `MISO`, `ISNE`, `NYIS`).
- Pagination via `offset`/`length`; data lags real time by a few hours.
- Free key, generous limits; we still cache aggressively and poll on a schedule rather than per-request.

### 3.2 eGRID detail
- Emission factors we need: **fuel-specific output emission rates** (lb CO₂ per MWh by fuel category) so we can multiply against EIA's per-fuel MWh.
- eGRID's native geography is the **eGRID subregion** (e.g., `CAMX`, `ERCT`, `RFCE`, `NEWE`, `NYUP`). This does **not** line up 1:1 with EIA balancing authorities — see §4.3.
- Static: we snapshot the latest eGRID release into our DB as a versioned reference table. Updated roughly annually; a yearly manual refresh is acceptable.

### 3.3 Crosswalk detail
- We need two mappings:
  1. **ZIP → eGRID subregion** (for the user-facing `?zip=` lookups). EPA's Power Profiler provides a ZIP-to-subregion file.
  2. **EIA balancing authority → eGRID subregion** (to attach eGRID emission factors to EIA's live BA-level fuel mix). This is the genuinely tricky reconciliation (§4.3).

---

## 4. Core computation

### 4.1 The carbon-intensity formula

For a given grid region and hour:

```
total_emissions_lb = Σ_fuel ( generation_MWh[fuel] × emission_factor_lb_per_MWh[fuel] )
total_generation_MWh = Σ_fuel ( generation_MWh[fuel] )

carbon_intensity_gCO2_per_kWh =
    ( total_emissions_lb × 453.592 g/lb )      # lb → grams
    / ( total_generation_MWh × 1000 kWh/MWh )  # MWh → kWh
```

Worked sanity check: a region running 50% gas (~900 lb CO₂/MWh) and 50% wind (~0 lb/MWh) lands around 450 lb/MWh ≈ **204 gCO₂/kWh**, which is in the right ballpark for a moderately clean grid. (Coal-heavy grids ~900+ gCO₂/kWh; nuclear/hydro-heavy ~50 gCO₂/kWh.)

### 4.2 Derived metrics
- **Cleanest hour today / next 24h**: rank hourly intensities, return the minimum and a ranked list. (Uses the forecast for future hours; see §6.3.)
- **Time-shift savings**: `(intensity[from_hour] − intensity[to_hour]) × kWh` → grams CO₂ saved by moving a load.
- **Region comparison**: side-by-side current intensity + fuel-mix breakdown for N regions.

### 4.3 The hard part: geography reconciliation (document this prominently)

EIA reports by **balancing authority**; eGRID emits by **subregion**. They overlap imperfectly — one BA can span multiple subregions and vice versa. Our approach, in increasing order of fidelity:

- **v1 (ship first):** a hand-curated BA→subregion lookup for the ~15 largest BAs covering most of the U.S. population. Where a BA spans multiple subregions, pick the dominant one and **flag the record with a `mapping_confidence` field** (`exact` | `dominant` | `approximate`). Honesty about this is a feature, not a bug — it's exactly the nuance an interviewer probes.
- **v2 (later):** area- or generation-weighted blending of subregion factors for multi-subregion BAs.

This reconciliation, and the decision to surface confidence rather than hide it, is the centerpiece data-engineering story of the project.

---

## 5. Data API (non-AI endpoints)

All responses are JSON, versioned under `/v1`. Consistent error envelope, proper status codes, input validation (Pydantic), cursor-based pagination on any list endpoint, ETag/`Cache-Control` on read-heavy endpoints.

| Method | Path | Returns |
|---|---|---|
| `GET` | `/v1/carbon/now?zip=10001` | Current gCO₂/kWh for that ZIP's grid region + fuel-mix breakdown + `mapping_confidence` + data timestamp |
| `GET` | `/v1/carbon/now?region=CISO` | Same, addressed by region code instead of ZIP |
| `GET` | `/v1/carbon/history?region=&start=&end=&cursor=` | Hourly intensity time series (cursor-paginated) |
| `GET` | `/v1/carbon/cleanest-hour?zip=&horizon=24` | Lowest-intensity upcoming hour(s) + ranked list (uses forecast) |
| `GET` | `/v1/carbon/compare?regions=CISO,ERCO,PJM` | Side-by-side current intensity + mix, ranked cleanest→dirtiest |
| `GET` | `/v1/carbon/savings?zip=&kwh=&from_hour=&to_hour=` | CO₂ saved by time-shifting a load |
| `GET` | `/v1/regions` | List of supported regions/BAs with metadata + coverage notes |
| `GET` | `/v1/regions/{code}` | Region detail: name, subregion mapping, confidence, fuel-mix profile |
| `GET` | `/v1/health` | Liveness/readiness + freshness of last EIA ingest |
| `GET` | `/v1/meta/freshness` | Per-region timestamp of most recent data point (transparency) |

### Cross-cutting API requirements
- **Pagination:** opaque cursor (base64 of `(timestamp, id)`), never offset.
- **Rate limiting:** token bucket per API key + per IP; expose `X-RateLimit-*` headers and emit metrics on who hits limits and where.
- **Caching:** `/now` and `/compare` cached in Redis (TTL ~ until next expected EIA update); ETag support so clients can revalidate cheaply.
- **Auth:** simple API-key scheme with key lifecycle (issue/revoke); public demo key with tight limits.
- **Errors:** `{ "error": { "code", "message", "details" } }`, correct 4xx/5xx.

---

## 6. AI layer

Deliberately scoped. The differentiator is the **engineering around** each feature — guardrails, evals, compute-then-narrate — not the features themselves.

### 6.1 Text-to-SQL (`POST /v1/ai/ask`)
Natural-language question → SQL against a read-only view of the carbon data → results + the generated SQL (always shown).

**Guardrails (defense in depth, never prompt-only):**
1. LLM emits SQL via **structured output** (a typed tool call), not free prose.
2. Parse with **`sqlglot`**: must be a single read-only `SELECT`, hitting only an allowlist of views/columns, with an enforced `LIMIT`.
3. Execute against a dedicated **`SELECT`-only Postgres role** on a curated schema, with a `statement_timeout`.
4. One **repair retry**: on DB error, feed the error back to the model once.
5. Always return the SQL alongside results for auditability; flag low-confidence answers rather than guessing.

Model: a cheaper Claude tier (Sonnet/Haiku) is fine for SQL. Schema context = curated table/column descriptions + representative values + a handful of few-shot NL→SQL examples (the single biggest accuracy lever).

### 6.2 Insight narration (`GET /v1/ai/insights?region=&window=`)
**Compute-then-narrate.** Statistics computed deterministically in Python (`pandas`/`scipy`): trend slope, period-over-period delta, outlier hours (z-score / IQR), correlation of intensity with renewable share. The LLM receives only the **computed numbers** and writes the narrative. Post-validate that every number in the prose appears in the computed set — the model narrates, it does not calculate. Cache narration keyed on the result hash.

### 6.3 Forecast (`GET /v1/carbon/forecast?region=&horizon=24`)
Next-24h carbon-intensity forecast.
- Model: start with **Prophet/NeuralProphet** on the historical hourly series (strong daily + weekly seasonality from solar/wind/demand cycles). Optionally evaluate a foundation model (Chronos-2 / TimesFM) as a comparison and mention it.
- Always return **prediction intervals**; the `cleanest-hour` endpoint consumes this.
- Backtest with MAPE; report the number in the README.
- Optional LLM explanation of the forecast that is *passed* the real intervals and instructed to hedge.

### 6.4 Eval suite (the real engineer signal)
- 30–50 hand-written `(question, expected)` pairs for text-to-SQL, scored by **execution match** (compare result sets, BIRD-style).
- A small gold set for insight narration (does the prose only cite computed numbers?).
- Backtest metrics for the forecast.
- A `make eval` target + a results table in the README. Almost no portfolio project has this; it's a primary differentiator.

### 6.5 AI cost & safety
- Tier models (cheap for SQL/classification, frontier only for synthesis).
- **Prompt caching** on the stable schema/few-shot prefix.
- Per-key token budgets + hard monthly cap so the public demo can't run away.
- Redis exact-match response cache; optional pgvector semantic cache for paraphrased questions.
- Treat all NL input as hostile — the DB-level read-only role is the real protection, not the prompt.

---

## 7. Architecture

```
                          ┌─────────────────────────┐
        Scheduled ETL  →  │  EIA-930 ingester (cron) │
                          └────────────┬─────────────┘
                                       │ hourly poll, upsert
   eGRID bulk (annual) ───────────────▶│
   ZIP/BA crosswalk (static) ─────────▶│
                                       ▼
   ┌──────────┐   read-only role  ┌──────────────────────────┐
   │  Client  │ ◀──── REST ─────▶ │  FastAPI app             │
   │ (demo UI │                   │  ├─ /v1/carbon/* (data)  │
   │  + docs) │                   │  ├─ /v1/ai/*  (AI layer) │
   └──────────┘                   │  └─ guardrails, auth, RL │
                                  └───────┬──────────┬───────┘
                                          │          │
                                   ┌──────▼───┐  ┌───▼────┐
                                   │ Postgres │  │ Redis  │
                                   │ + Timescale (hypertable on hourly series)
                                   │ + pgvector (semantic cache / schema embeds)
                                   └──────────┘  └────────┘
                                          ▲
                                   Claude API (text-to-SQL, narration)
```

### Data model (initial sketch)
- `regions` — BA code, name, eGRID subregion mapping, `mapping_confidence`, coverage notes.
- `emission_factors` — eGRID version, fuel code, lb CO₂/MWh (+ other pollutants). Versioned.
- `zip_region` — ZIP → BA/subregion crosswalk.
- `generation_hourly` — **Timescale hypertable**: (region, hour, fuel_code, mwh). The live feed.
- `carbon_intensity_hourly` — materialized/derived: (region, hour, gco2_per_kwh, total_mwh, renewable_share). Computed from the two above.
- `api_keys`, `rate_limit_events` — auth + RL metrics.
- AI-layer-curated **read-only views** exposed to text-to-SQL (clean, documented, allowlisted).

---

## 8. Tech stack

| Layer | Choice | Why |
|---|---|---|
| API framework | **FastAPI** (Python) | OpenAPI/Swagger for free; de-facto data-API standard; Pydantic validation; same ecosystem as pandas/Prophet |
| Database | **Postgres** + **TimescaleDB** + **pgvector** | Consolidate on Postgres; Timescale for the hourly hypertable; pgvector for semantic cache / schema embeddings |
| Cache / RL | **Redis** | Response cache, rate-limit token buckets |
| LLM | **Anthropic Claude** (tool use / structured output) | Text-to-SQL, narration; tiered models + prompt caching |
| Forecasting | **Prophet / NeuralProphet** | Interpretable, strong on seasonal series; foundation-model comparison optional |
| SQL guardrail | **sqlglot** | AST validation of generated SQL |
| Docs | **Scalar** (or Redoc) over the OpenAPI spec | Modern interactive "try it" docs |
| Demo UI | Minimal **Tailwind v4** + semantic HTML SPA | Map + chart + "best hour to charge" widget; doubles as frontend practice |
| Deploy | **Render or Railway** (API) + **Neon** (Postgres) | Cheap, professional; Dockerized; GitHub Actions CI/CD |
| Tests | **pytest** + integration tests against the API | Plus the AI eval suite (§6.4) |

---

## 9. Engineering hygiene checklist (the "not a tutorial" signals)
- [ ] Live deployed URL + custom domain
- [ ] README: pitch → live links → architecture diagram (Mermaid) → design decisions/trade-offs → run-locally → screenshots
- [ ] Cursor-based pagination (not offset)
- [ ] DB migrations (Alembic), real indexes, constraints — no auto-create
- [ ] Rate limiting with exposed metrics
- [ ] ETag / Cache-Control + Redis caching
- [ ] Structured logging + p50/p95/p99 latency metrics
- [ ] Integration tests + green GitHub Actions CI
- [ ] AI eval suite with a results table
- [ ] `.env.example`, no secrets in repo, input validation everywhere
- [ ] Stated performance numbers (concurrency, p95 latency) in README

---

## 10. Build phases

**Phase 0 — Foundations**
- Repo scaffold, FastAPI skeleton, Docker, Postgres+Timescale local via docker-compose, Alembic, CI, `.env.example`.

**Phase 1 — Data fusion core (the heart)**
- Load eGRID emission factors + ZIP/BA crosswalk as seed data.
- EIA-930 ingester (scheduled poll → `generation_hourly`).
- Compute `carbon_intensity_hourly`. Implement `/v1/carbon/now`, `/regions`, `/health`, `/meta/freshness`.
- Geography reconciliation with `mapping_confidence`.

**Phase 2 — Full data API**
- `/history` (cursor pagination), `/compare`, `/savings`. Rate limiting, caching, ETags, API keys, structured logging/metrics. Integration tests + CI.

**Phase 3 — Forecast**
- Prophet/NeuralProphet on the hourly series; `/forecast` with intervals; wire `/cleanest-hour` to it; backtest + MAPE.

**Phase 4 — AI layer**
- Text-to-SQL with full guardrails (`/ai/ask`); insight narration (`/ai/insights`); eval suite; cost controls + caching.

**Phase 5 — Presentation**
- Scalar docs, Mermaid architecture diagram, Tailwind demo UI, README polish, deploy to Render/Railway + Neon, custom domain, performance numbers.

---

## 11. Open questions / decisions to revisit
- Exact list of v1 supported regions (start with the ~10–15 largest BAs by population coverage).
- Which eGRID release year to snapshot (latest available).
- Whether to precompute `carbon_intensity_hourly` on ingest vs. on read (lean precompute for cache-friendliness).
- Forecast model final choice (Prophet vs. NeuralProphet vs. foundation model) — decide after seeing data quality in Phase 3.

---

## 12. Honest limitations (state these in the README)
- **Average, not marginal, emissions** — we don't model which plant ramps up for the next kWh.
- **Geography is approximate** — BA↔subregion mismatch, surfaced via `mapping_confidence`.
- **Hourly, lagged** — EIA-930 is not real-time; data trails by a few hours.
- **Text-to-SQL ceiling** — complex NL queries hit a ~80% accuracy ceiling industry-wide; we always show the SQL and degrade gracefully.

---

## 13. Attribution
- Electricity generation data: U.S. Energy Information Administration (EIA-930).
- Emission factors: U.S. EPA Emissions & Generation Resource Integrated Database (eGRID).
- ZIP/region mapping: U.S. EPA Power Profiler / U.S. Census.
