# Stockcast runbook

Who to read this: whoever is on call or about to deploy. It covers the environments, how a
change reaches production, what to do when something breaks, and the drills we practise.

- Production: https://app.stockcast.app (web, Vercel) · https://api.stockcast.app (Railway)
- Staging: https://staging.stockcast.app · https://api-staging.stockcast.app
- Status/alerts: Sentry (api + web projects), Grafana Cloud (traces, uptime), alert webhook (Slack `#stockcast-ops`)

## 1. Topology

```
                 GitHub Actions ──deploy──▶ Railway project "stockcast"  (env: staging | production)
                                           ├── api      FastAPI / uvicorn      (infra/railway/api.json)
                                           ├── worker   Celery worker          (worker.json, 1 proc per vCPU)
                                           ├── beat     Celery beat, 1 replica (beat.json)
                                           ├── backup   cron 03:00 UTC         (backup.json) -> S3/R2
                                           ├── postgres TimescaleDB 16 (volume)
                                           └── redis    broker db1, rate limit db2
                                 ──deploy──▶ Vercel project "stockcast-web"  (preview = staging alias, production)
Clerk (auth) · Stripe (billing) · Resend (email) · Shopify / Amazon SP-API / eBay / WooCommerce (connectors)
```

Nightly schedule (UTC, `apps/api/app/worker.py`): sync 02:00 → forecast 03:30 → planning 04:30 ·
backup 03:00 · trial emails 09:00 · weekly digest Mon 07:00 · `ops.check_health` every 15 min.

## 2. How a change ships

1. Branch → PR. CI (`.github/workflows/ci.yml`) runs: ruff, **mypy**, migrations up/down/up +
   `alembic check`, pytest with **coverage ≥ 80 %** (currently ~91 %), eslint, tsc, vitest, Next
   build, then Playwright against the **docker compose production images**.
2. Merge to `main` → CI runs again on main → `Deploy` workflow (`deploy.yml`) starts:
   - **staging** job: sets `RELEASE=<sha>` on api/worker/beat, `railway up` the api (Railway runs
     `scripts/migrate.sh` as the pre-deploy command, so migrations land before the new container
     takes traffic), then worker, beat, backup; builds the web app and deploys it to Vercel with
     the staging alias; **smoke test**: `/health/ready` must report `"release":"<sha>"` with
     database + redis ok, `/openapi.json` must list `/recommendations`, the web app must serve.
   - **production** job: waits for the GitHub environment **`production`** approval (Required
     reviewers). On approval it repeats the same steps with `--environment production` and
     `vercel --prod`, then creates the Sentry release.
3. Nothing else is manual. Rollback: see §6.

`workflow_dispatch` on Deploy with *skip_production* deploys staging only.

## 3. One-time setup (checklist)

Railway
- Project `stockcast`, environments `staging` and `production`. In each: TimescaleDB template
  (`timescale/timescaledb:latest-pg16`, volume) and Redis; services `api`, `worker`, `beat`,
  `backup` from this repo with the config file paths in `infra/railway/README.md`; auto-deploy on
  push **off**. Variables as listed there (`DATABASE_URL` uses `postgresql+psycopg://`).
- Worker size: 8 vCPU / 8 GB in production (`CELERY_CONCURRENCY` defaults to `nproc`), 2 vCPU in
  staging. api: 1 vCPU, `WEB_CONCURRENCY=2`.
- Project token → GitHub secret `RAILWAY_TOKEN`.

Vercel
- Project `stockcast-web` with root `apps/web` (vercel.json carries install/build commands and
  security headers; git deployments disabled). Env vars per environment: `NEXT_PUBLIC_API_URL`,
  `API_URL`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `NEXT_PUBLIC_SENTRY_DSN`.
  Domain `staging.stockcast.app` is the *preview* alias the workflow sets.
- Token + org/project ids → GitHub secrets `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`.

GitHub
- Environments `staging` and `production` (Settings → Environments). `production`: **Required
  reviewers** = the two of you. Variables per environment: `API_URL`, `WEB_URL`, `WEB_HOST` (staging
  alias host), `SENTRY_ORG`, `SENTRY_PROJECT`. Secrets: the Railway/Vercel ones above,
  `SENTRY_AUTH_TOKEN`.
- Dependabot (`.github/dependabot.yml`) opens weekly grouped PRs for pip, npm, Actions, Docker.

Sentry — two projects (`stockcast-api`, `stockcast-web`); DSNs into Railway/Vercel env vars.

Grafana Cloud (free tier)
- *OpenTelemetry → Configure* gives the OTLP endpoint + header → `OTEL_EXPORTER_OTLP_ENDPOINT`,
  `OTEL_EXPORTER_OTLP_HEADERS` on api/worker/beat. Traces arrive in Tempo (service
  `stockcast-api`, `stockcast-worker`).
- *Synthetic Monitoring → HTTP check* on `https://api.stockcast.app/health` and
  `https://app.stockcast.app` every 1 min from 2 probes; alert after 2 failures → Slack.
- Alert rules on logs (optional; Railway → Grafana via Loki push) are not required because the
  worker raises the failure-rate / duration alerts itself (§5).

Backups — bucket `stockcast-backups` (R2 or S3), lifecycle rule 35 days as a belt-and-braces;
credentials only on the `backup` service.

## 4. Routine checks (daily, 2 minutes)

- `/health/ready` on both APIs returns `status: ok` and yesterday's `release`.
- Sentry: no new issues in the last 24 h for api/web.
- `#stockcast-ops`: no alert from `ops.check_health`.
- Railway `beat` logs show the 02:00/03:30/04:30 tasks were sent; `worker` logs show
  `forecast.run_org` success per org (grep `"forecast run"`).
- Backup object for today exists in the bucket (`stockcast-production-<date>.dump`).

## 5. Alerts and what to do

| Alert | Source | First response |
| --- | --- | --- |
| Uptime check failing on `/health` | Grafana synthetic | Railway → api → logs. If the container restarts in a loop with `refusing to start`, an env var violates the production guard (§8). Roll back if the last deploy is the cause. |
| `/health/ready` degraded (`database`/`redis` error) | smoke test or uptime | Railway status of the Postgres/Redis service; check connection limits (`max_connections`), restart the api. |
| **Channel sync failure rate above threshold** (> 5 % of syncs in 24 h) | `ops.check_health` | `SELECT channel_id, error FROM sync_runs WHERE status='failed' AND created_at > now()-interval '1 day'`. Clusters by error: `401`/`token rejected` → the merchant must reconnect (they were emailed `sync_failed`); `PlanLimit` → expected; `Shopify 5xx`/`throttled repeatedly` → upstream incident, retries continue. |
| **Forecast run exceeded time budget** (> 30 min) | `ops.check_health` | Which org (`run_id` in the alert)? SKU count vs capacity (§9). If the run is `running` and the worker is idle, the task died: `UPDATE forecast_runs SET status='failed', error='stale' WHERE id=...` and re-trigger `POST /forecast-runs`. If many orgs: scale the worker (more vCPU or a second replica) before the next night. |
| Sentry spike from api | Sentry | Open the issue; the `request_id` tag matches the `X-Request-Id` the browser received and the JSON log line. |
| Stripe webhook errors (Stripe dashboard shows 4xx/5xx) | Stripe | 400 = signature: the endpoint secret differs between Stripe and `STRIPE_WEBHOOK_SECRET`. Stripe retries for 3 days; plans update on the next successful delivery, nothing is lost. |
| Dependabot PR | GitHub | Merge when CI is green; majors get a look at the changelog first. |

## 6. Rollback

- **API/worker**: Railway → service → Deployments → *Redeploy* the previous successful deployment
  (both `api` and `worker`, keep them on the same release). Migrations are additive and
  backward-compatible by rule, so the previous code runs against the new schema. If a migration
  must be reverted: `railway run --service api -e production alembic downgrade -1`.
- **Web**: Vercel → Deployments → *Promote to Production* the previous deployment (instant).
- **Record it**: Sentry release stays; add a line to `docs/CHANGELOG.md` (what, why, follow-up).

## 7. Backups and the restore drill

- `backup` service runs `apps/api/scripts/backup.sh` daily at 03:00 UTC: `pg_dump --format=custom`
  → `s3://$BACKUP_S3_BUCKET/$BACKUP_PREFIX/stockcast-<env>-<timestamp>.dump`, then prunes objects
  older than `BACKUP_RETENTION_DAYS` (30). Railway's own volume backups are a second copy.
- **Restore drill (quarterly, ~20 min)** — proves the backups are usable, never touches production:
  1. Create a scratch database on the staging Postgres: `railway run -e staging --service api psql
     $DATABASE_URL -c "CREATE DATABASE restore_drill"`.
  2. `RESTORE_TARGET_URL=postgresql://…/restore_drill sh apps/api/scripts/restore.sh
     s3://stockcast-backups/production/<latest>.dump` (run from the `api` service shell so the
     bucket credentials and `pg_restore` are available).
  3. The script prints organizations / sales_daily counts and `alembic current`; compare with
     production (`SELECT count(*) FROM organizations`). Spot-check one org's recommendations via
     the API pointed at the scratch DB.
  4. Drop the scratch database. Note the date and timings in `docs/CHANGELOG.md` under "Restore
     drill". Target RTO 1 h, RPO 24 h (daily dump) — Railway volume snapshots narrow RPO further.

## 8. Security posture

- HTTPS only: `FORCE_HTTPS=true` makes the API 308-redirect plain http (trusting
  `X-Forwarded-Proto` from Railway's edge) and send HSTS; Vercel serves HSTS via `vercel.json`.
  `ALLOWED_HOSTS` pins the API hostnames.
- CORS allowlist from `CORS_ORIGINS` (explicit methods/headers, credentials on).
- **Production guard** (`app/security.py`): the api refuses to boot in `ENV=staging|production` with
  `AUTH_MODE=header`, the dev `CREDENTIALS_KEY`, `FORCE_HTTPS` off, http CORS origins or no Stripe
  webhook secret. Fix the variable rather than the guard.
- Webhook signatures: Shopify (`X-Shopify-Hmac-Sha256`), Stripe (`Stripe-Signature`, event ids
  deduped), Amazon (`X-Amz-Webhook-Signature` HMAC or `X-Amz-Webhook-Token`, notification ids
  deduped). Unsigned requests are 401 and never touch data.
- Secrets live only in Railway/Vercel/GitHub environments; `.env.example` documents names.
  Channel credentials are Fernet-encrypted at rest (`CREDENTIALS_KEY`); rotating it requires
  re-encrypting `channels.credentials_encrypted` (script TBD — rotate by asking merchants to
  reconnect if ever compromised).
- PII: connectors request only line items, quantities, prices and SKUs — no customer names,
  emails or addresses are fetched or stored (`tests/test_privacy.py` guards the Shopify query and
  the record models). Sentry runs with `send_default_pii=False`. User records hold name, email
  and role only.
- Dependencies: Dependabot weekly; `uv.lock`/`pnpm-lock.yaml` pinned; images rebuilt on every
  deploy from `python:3.12-slim` / `node:22-alpine` and run as non-root.

## 9. Capacity and the load test

Measured with `scripts/bench_forecast.py` on 2 vCPU (AutoETS route, 365-day histories,
covariates on): **5.8 SKU/s per worker process**. The nightly forecast window is 60 min
(03:30 → 04:30); 50 orgs × 2,000 SKUs = 100,000 SKUs needs **≥ 5 worker processes**; the
production worker runs 8 (one per vCPU) → projected **~36 min**. Orgs fan out as one Celery task
each, so a second worker replica scales linearly. Chronos (installed in the image) adds a batched
CPU pass per org; re-run the benchmark when the model mix changes.

The `Load test` workflow (`.github/workflows/loadtest.yml`, weekly + manual) seeds 5 × 2,000 into
the compose stack, runs the benchmark and fails if the projection leaves the window, then runs
`loadtest/k6/api.js` (50 VUs reading recommendations/products/forecasts; thresholds p95 < 800 ms,
error rate < 1 %). To run against staging: `make seed-load` on a staging shell, then
`make loadtest API_URL=https://api-staging.stockcast.app`.

## 10. Useful commands

```bash
railway logs -e production --service worker | grep forecast     # nightly run
railway run -e production --service api alembic current            # schema version
railway run -e production --service api python -m scripts.export_openapi  # spec
make ci-stack && make e2e                                       # what CI does, locally
make bench WORKERS=8                                            # capacity projection
```
