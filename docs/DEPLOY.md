# Deploying GridClean

A runbook for putting GridClean online. The app is **deploy-portable**: the
Phase-1 migration uses TimescaleDB hypertables where the extension is available
and falls back to plain indexed tables where it isn't — automatically, no app
changes needed. **Neon supports `timescaledb`** (Apache-2 features; compression
excluded, which we don't use), so on Neon you get real hypertables. The btree
fallback only applies to hosts without the extension (e.g. Railway Postgres, RDS).

You'll provision four things:

| Piece | What | Options |
|---|---|---|
| **Web service** | the FastAPI app | Render / Railway / Fly.io |
| **Postgres** | data + the read-only AI role | Neon (recommended), Railway PG, RDS |
| **Redis** | rate-limit + cache | Render Key Value, Railway Redis, Upstash |
| **Cron** | hourly EIA ingest | Render Cron / Railway Cron |

> ⚠️ These steps require **your** cloud accounts and interactive logins, so they
> are yours to run — this repo is prepped to make them fast. Nothing here
> deploys automatically.

---

## 0. Prerequisites

- A free **EIA API key** — https://www.eia.gov/opendata/register.php
- An **Anthropic API key** for the AI layer — https://console.anthropic.com
- A Git remote (push this repo to GitHub; Render/Railway deploy from it)

---

## 1. Postgres (Neon)

1. Create a Neon project → copy the connection string. It looks like:
   `postgresql://user:pass@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require`
2. **Convert it for this app** — asyncpg needs a different driver + SSL param:
   ```
   postgresql+asyncpg://user:pass@ep-xxx.../neondb?ssl=require
   ```
   Changes: `postgresql` → `postgresql+asyncpg`, and `?sslmode=require` → `?ssl=require`
   (asyncpg rejects `sslmode`). This is `DATABASE_URL`.
3. Neon **supports `timescaledb`**, so the migration enables it
   (`CREATE EXTENSION IF NOT EXISTS timescaledb`, which it does automatically when
   the extension is available) and creates hypertables — no manual step needed.

> The migration also creates a **read-only role** (`gridclean_ro`) with SELECT on
> the `ai_*` views only. It's created with the password from `AI_DB_PASSWORD`, so
> **set that env var before the release migration runs.** The AI layer connects
> as this role by swapping the credentials in `DATABASE_URL` (same host/db).

---

## 2. Redis

Provision a Redis (Render Key Value, Railway Redis, or Upstash). Copy its URL as
`REDIS_URL` (e.g. `redis://default:pass@host:6379` or `rediss://…` for TLS).

---

## 3. Environment variables

Set these on the web service **and** the cron job:

| Var | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |
| `DATABASE_URL` | the `postgresql+asyncpg://…?ssl=require` string from step 1 |
| `REDIS_URL` | from step 2 |
| `EIA_API_KEY` | your EIA key |
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `AI_DB_PASSWORD` | a strong secret (the read-only role's password) |
| `AI_MODEL` | `claude-opus-4-8`, or `claude-sonnet-4-6` to cut cost |

---

## 4. Deploy the web service

The repo includes a `Procfile`:
```
web:     uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
release: alembic upgrade head
```

### Render
- New **Web Service** → connect the repo → runtime **Python**.
- Build command: `pip install .`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2`
- **Pre-Deploy command**: `alembic upgrade head` (runs migrations each deploy).
- Add the env vars from step 3.

### Railway
- New project from the repo. Railway reads the `Procfile` (`release` runs
  migrations, `web` serves). Set the env vars. Add Postgres + Redis plugins, or
  point `DATABASE_URL`/`REDIS_URL` at Neon/Upstash.

---

## 5. One-time data load

After the first successful deploy + migration, run **once** (Render Shell, a
Railway one-off, or a temporary job):

```bash
python -m app.manage seed
python -m app.manage ingest --hours 504    # ~21 days; enough for the forecaster
```

---

## 6. Scheduled ingest (keep data fresh)

EIA publishes hourly (lagging a few hours). Add a **cron job** with the same env
vars and image:

```
schedule:     20 * * * *      # hourly, at :20
command:      python -m app.manage ingest --hours 6
```

`ingest` upserts, so a small overlapping window is safe and self-healing.

---

## 7. Verify

```bash
curl https://YOUR_HOST/v1/health                      # {"status":"ok"}
curl "https://YOUR_HOST/v1/carbon/now?region=CISO"    # live intensity
```
- Demo UI → `https://YOUR_HOST/app/`
- API docs → `https://YOUR_HOST/scalar`

---

## 8. Production gotchas

- **`?ssl=require`, not `?sslmode=require`** — asyncpg rejects `sslmode`.
- **`$PORT`** — managed hosts inject it; the start command must bind it.
- **Cost control** — `/v1/ai/*` calls the Anthropic API (real money). Options:
  set `AI_MODEL=claude-sonnet-4-6`, lower `ANONYMOUS_RATE_LIMIT_PER_MIN`, or
  gate the AI routes behind an API key. The DB read-only role + statement
  timeout already bound query cost.
- **Workers** — `--workers 2+` is safe; all shared state is in Redis/Postgres,
  nothing in-process.
- **Rate limits** — anonymous is per-IP; behind a proxy, ensure the real client
  IP reaches the app (most platforms set it on the connection).
- **Custom domain** — add it in the platform dashboard; TLS is automatic.
