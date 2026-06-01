# GridClean API Playground

A copy-paste tour of every endpoint with notes on what to look for in each
response. Commands pipe JSON through `python3 -m json.tool` for readability
(swap in `jq` if you prefer). Header-inspection commands use `curl -i`/`-D -`.

## 0. Prerequisites

```bash
# From the repo root, with containers up and the API running:
make up            # Postgres (host :5433) + Redis
source .venv/bin/activate
make migrate       # if you haven't already
make seed          # reference data (regions, factors, ZIP crosswalk)
make ingest        # pull ~24h of EIA-930 data + compute intensity (needs EIA_API_KEY in .env)
make dev           # serve on http://localhost:8000
```

Set a base URL for the commands below:

```bash
export BASE=http://localhost:8000
```

> If `/carbon/*` returns `503 No carbon data yet`, run `make ingest` first.
> The interactive docs are also at <http://localhost:8000/docs>.

---

## 1. Health & metadata

```bash
# Liveness + DB readiness
curl -s $BASE/v1/health | python3 -m json.tool
```
Look for: `{"status":"ok","checks":{"database":"ok"}}`.

```bash
# Service root
curl -s $BASE/ | python3 -m json.tool

# Data freshness — most recent hour per region (transparency on staleness)
curl -s $BASE/v1/meta/freshness | python3 -m json.tool
```

---

## 2. Regions

```bash
# All supported balancing authorities + their eGRID subregion mapping
curl -s $BASE/v1/regions | python3 -m json.tool

# One region — note egrid_subregion and mapping_confidence
curl -s $BASE/v1/regions/CISO | python3 -m json.tool

# Unknown region -> 404
curl -s -o /dev/null -w "HTTP %{http_code}\n" $BASE/v1/regions/NOPE
```
Look for: `mapping_confidence` is `exact` for clean 1:1 BAs (CISO, ERCO, ISNE)
and `dominant`/`approximate` for multi-subregion BAs (PJM, MISO, SWPP).

---

## 3. Carbon intensity — now

```bash
# By ZIP (San Francisco -> CISO)
curl -s "$BASE/v1/carbon/now?zip=94103" | python3 -m json.tool

# By region code
curl -s "$BASE/v1/carbon/now?region=CISO" | python3 -m json.tool
```
Look for: `gco2_per_kwh`, the ranked `fuel_mix`, and the `caveats` array
(average-not-marginal, data lag, mapping confidence, low-confidence fuel share).

```bash
# The geography nuance: downtown LA is served by LADWP, NOT CISO.
# Same city, different (dirtier) grid + lower-confidence caveats.
curl -s "$BASE/v1/carbon/now?zip=90012" | python3 -m json.tool
```
Look for: `region_code` is `LDWP`, and a caveat noting the ZIP→region mapping
is `dominant`.

```bash
# Validation: exactly one of zip/region required
curl -s -o /dev/null -w "both params  -> HTTP %{http_code}\n" "$BASE/v1/carbon/now?zip=10001&region=CISO"
curl -s -o /dev/null -w "no params    -> HTTP %{http_code}\n" "$BASE/v1/carbon/now"
curl -s -o /dev/null -w "unknown zip  -> HTTP %{http_code}\n" "$BASE/v1/carbon/now?zip=99999"
```
Look for: `400`, `400`, `404`.

---

## 4. History (cursor pagination)

```bash
# Newest-first hourly series; grab the first page
curl -s "$BASE/v1/carbon/history?region=CISO&limit=5" | python3 -m json.tool
```
Look for: `data` sorted newest-first, plus a `next_cursor` (opaque base64).

```bash
# Follow the cursor to the next page in one shot
CURSOR=$(curl -s "$BASE/v1/carbon/history?region=CISO&limit=5" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['next_cursor'])")
curl -s "$BASE/v1/carbon/history?region=CISO&limit=5&cursor=$CURSOR" | python3 -m json.tool
```
Look for: the second page starts at an hour strictly older than page 1's last row.

```bash
# Optional time window (ISO timestamps, URL-encoded)
curl -s "$BASE/v1/carbon/history?region=CISO&start=2026-06-01T00:00:00Z&limit=100" | python3 -m json.tool

# Bad cursor -> 400
curl -s -o /dev/null -w "bad cursor -> HTTP %{http_code}\n" "$BASE/v1/carbon/history?region=CISO&cursor=not-real"
```

---

## 5. Compare regions

```bash
# Ranked cleanest -> dirtiest, with any unavailable codes reported
curl -s "$BASE/v1/carbon/compare?regions=CISO,ISNE,ERCO,PJM,MISO,SOCO" | python3 -m json.tool
```
Look for: `items` sorted ascending by `gco2_per_kwh` with `rank` 1..N. Expect
CISO/ISNE near the top (clean) and MISO/SOCO near the bottom (coal-heavy).

---

## 6. Time-shift savings

```bash
# How much CO2 do you save running 10 kWh at 11am instead of 8pm? (local hours)
curl -s "$BASE/v1/carbon/savings?region=CISO&kwh=10&from_hour=20&to_hour=11" | python3 -m json.tool
```
Look for: `from_intensity` > `to_intensity` for California (midday solar is
clean), a positive `savings_g`/`savings_pct`, and `timezone` =
`America/Los_Angeles`. The `basis`/`caveats` note it's a historical hour-of-day
average, not a forecast.

> Note: if a requested local hour has no data yet (e.g. you've only ingested a
> few hours), the endpoint returns `422` asking you to ingest more history.
> With a full ~24h ingest, all hours 0–23 are covered.

---

## 7. Caching & ETags

```bash
# First call is a cache MISS; second is a HIT (watch the X-Cache header)
curl -s -D - -o /dev/null "$BASE/v1/carbon/now?region=ERCO" | grep -iE "x-cache|etag|cache-control"
curl -s -D - -o /dev/null "$BASE/v1/carbon/now?region=ERCO" | grep -i  "x-cache"
```
Look for: `X-Cache: MISS` then `X-Cache: HIT`, an `ETag`, and
`Cache-Control: public, max-age=300`.

```bash
# Conditional request: send the ETag back and get a 304 with no body
ETAG=$(curl -s -D - -o /dev/null "$BASE/v1/carbon/now?region=ERCO" \
  | grep -i etag | sed 's/[Ee][Tt][Aa][Gg]: //' | tr -d '\r')
echo "ETag: $ETAG"
curl -s -o /dev/null -w "If-None-Match -> HTTP %{http_code}\n" \
  -H "If-None-Match: $ETAG" "$BASE/v1/carbon/now?region=ERCO"
```
Look for: `HTTP 304`.

---

## 8. Rate limiting

```bash
# Every response carries rate-limit headers
curl -s -D - -o /dev/null "$BASE/v1/regions" | grep -i "x-ratelimit"
```
Look for: `X-RateLimit-Limit` (30 for anonymous), `-Remaining`, `-Reset`.

```bash
# Trip the limit: hammer the endpoint anonymously (limit is 30/min per IP)
for i in $(seq 1 35); do
  curl -s -o /dev/null -w "%{http_code} " "$BASE/v1/regions"
done; echo
```
Look for: a run of `200`s, then `429`s once you cross 30 in the same minute.
(Wait ~60s for the window to reset.)

---

## 9. API keys

```bash
# Mint a key (the raw key is printed ONCE — copy it)
python -m app.manage apikey "My Playground" --limit 240
```

```bash
# Use it: limit jumps from 30 to 240
export KEY=gck_PASTE_YOUR_KEY_HERE
curl -s -D - -o /dev/null -H "X-API-Key: $KEY" "$BASE/v1/regions" | grep -i "x-ratelimit-limit"

# Invalid key -> 401
curl -s -o /dev/null -w "bad key -> HTTP %{http_code}\n" -H "X-API-Key: gck_bogus" "$BASE/v1/regions"
```
Look for: `X-RateLimit-Limit: 240` with a valid key; `401` with a bad one.

---

## 10. Observability

Every response includes a request ID and server timing:

```bash
curl -s -D - -o /dev/null "$BASE/v1/carbon/now?region=CISO" | grep -iE "x-request-id|x-response-time"
```
And the server logs one structured JSON line per request (visible in the
`make dev` terminal) with `method`, `path`, `status`, and `duration_ms`.
