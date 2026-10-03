# Stockcast — guide for Claude / Cowork sessions

Stockcast is an AI demand-forecasting and raw-material planning SaaS for ecommerce brands selling on Shopify, Amazon, eBay, WooCommerce and custom stores. This file is the first thing to read in every session.

## Stack

| Layer | Choice |
| --- | --- |
| API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (from Step 2), managed with `uv` |
| Database | PostgreSQL 16 with TimescaleDB (`timescale/timescaledb:latest-pg16`) |
| Jobs | Celery + Redis (from Step 3) |
| Forecasting | Amazon Chronos-Bolt (zero-shot) + StatsForecast fallback (Step 4) |
| Web | Next.js 15 (app router), TypeScript, Tailwind, shadcn/ui, pnpm workspaces |
| Auth / billing | Clerk + Stripe (Step 7) |
| Infra | Docker Compose locally; GitHub Actions CI; Railway (api/workers) + Vercel (web) in prod |

## Layout

```
apps/api/            FastAPI service
  app/main.py        app factory; includes routers
  app/config.py      pydantic-settings; all config via env vars
  app/db.py          engine + get_db session dependency
  app/deps.py        OrgId dependency (X-Org-Id header until Clerk in Step 7)
  app/crypto.py      Fernet encrypt/decrypt for channel credentials
  app/models/        SQLAlchemy 2 models (core, catalog, inventory, calendar, enums)
  app/schemas/       Pydantic request/response models
  app/routers/       products, suppliers, bom_lines, locations (list/get/create/patch)
  app/services/      business logic; crud.py = generic org-scoped CRUD
  app/ingest/        ingestion layer
    base.py          BaseConnector contract (fetch_products/sales/inventory, push_inventory)
    records.py       normalized Pydantic records every connector emits
    upsert.py        idempotent org-scoped upserts (SET semantics; increment_sales for webhooks)
    csv_connector.py CSV parse with column mapping + row errors; export.py = round-trip CSV
    shopify/         GraphQL client (pagination, throttle retry), connector, oauth + webhook HMAC
    tasks.py         Celery: sync_channel (backoff retries), nightly sync_all_channels, enqueue_sync
    registry.py      ChannelType -> connector class
  app/forecast/      forecast engine
    features.py      org-level daily demand per SKU, gap fill, stockout masking (NaN = masked)
    models.py        ChronosModel (batched, CPU), StatsModel (AutoETS), CrostonModel, FallbackModel
    router.py        per-SKU routing (>=60d & non-intermittent -> chronos vs autoets backtest;
                     >50% zeros -> croston; <60d -> fallback w/ category prior), 28-day holdout
    engine.py        run_forecast: load -> covariates -> forecast_batch on de-seasonalised history ->
                     re-apply factors -> persist forecasts (factor, event) + forecast_accuracy; wape_base
    calendar.py      built-in events per region (retail windows + `holidays` pkg: Eid, Diwali, national)
    holidays_seed.py idempotent seeding of holiday_events for a region
    covariates.py    uplift learning (actual / counterfactual, leak-free before holdout, shrinkage),
                     editable category priors, promo lift measurement + ridge model, build_factors
                     (overlapping events -> max per day, never multiplied; promos multiply on top)
    simulate.py      what-if promotion -> unit delta per product + BOM-exploded raw-material impact
    tasks.py         Celery: forecast.run_org, nightly forecast.run_all_orgs (03:30 UTC)
  app/planning/      planning engine
    math.py          project_stock, reorder (s,Q: ROP = L*d + z*sigma*sqrt(L); sigma from the
                     forecast band; lost-sales model; MOQ + pack rounding), health_status
    bom.py           multi-level BOM explosion of finished-goods demand into component demand
    engine.py        run_planning: latest forecast + stock + open POs + suppliers -> recommendations
                     (action reorder|produce|none, health, reason citing forecasts.event/factor)
    po.py            draft POs grouped by supplier, CSV/PDF export (fpdf2), send via Resend, receive
    tasks.py         Celery: planning.run_org, nightly planning.run_all_orgs (04:30 UTC)
  app/worker.py      Celery app + beat schedule (sync 02:00, forecast 03:30, planning 04:30 UTC)
  app/routers/       + channels (CRUD, /sync, /sync-runs), imports (/imports, /exports), shopify,
                     forecasts (/forecast-runs, /forecasts?product_id, /forecast-accuracy,
                     POST /forecasts/simulate), calendar (/regions, /holiday-events, /category-uplifts,
                     /promotions), planning (/planning-settings, /products/{id}/planning,
                     /planning-runs, /recommendations), purchase_orders (/purchase-orders
                     from-recommendations, export.csv|pdf, send, mark-sent, receive)
  alembic/           migrations (sales_daily becomes a Timescale hypertable when available)
  scripts/seed.py    demo org: 20 SKUs, 3 raw materials, 1 BOM, 365 days of sales
  tests/             pytest against a real Postgres (TEST_DATABASE_URL), tx-rollback per test
    cassettes/       vcrpy cassettes for Shopify (synthesized by make_cassettes.py; see below)
apps/web/            Next.js app
  app/               routes (app router)
  components/ui/     shadcn-style primitives
  lib/api.ts         server-side API client
  tests/             vitest
packages/shared/     shared TS types (@stockcast/shared); generated client lands here in Step 6
docker-compose.yml   api, web, postgres (timescaledb), redis
Makefile             make dev / test / lint / fmt
.github/workflows/   CI
```

## Run

```bash
make dev        # docker compose up: api http://localhost:8000/docs, web http://localhost:3000
make install    # local toolchains: uv sync + pnpm install
make test       # pytest + vitest
make lint       # ruff + eslint + tsc
make fmt        # auto-format python
make migrate    # alembic upgrade head
make migration m="add foo"   # autogenerate a migration
make seed       # load the demo org (idempotent)
make worker     # Celery worker + beat (compose runs this as the `worker` service)
make forecast   # forecast the demo org and print the backtest summary
make plan       # plan the demo org and print recommendations
make install-chronos  # optional locally; Docker + CI always install it
```

Forecasting: Chronos-Bolt is **optional at import time** (`requirements-chronos.txt`, CPU torch from the PyTorch index — not in `pyproject` because `uv lock` cannot reach that index everywhere). `chronos_available()` gates it; without it the chronos route uses AutoETS only and `tests/test_chronos_live.py` skips. Docker and CI install it. Backtest = last 28 observed days; the seed-org WAPE is printed as `[backtest] ...` in the test log and the CI job summary.

Planning: raw materials get DERIVED demand = sum(parent forecast p50 x qty_per_unit) through the BOM (multi-level), so they are planned with the same (s,Q) logic as finished goods; products with a BOM are `produce`, others `reorder` from the preferred or cheapest supplier (supplier_products.lead_time_days > supplier.lead_time_days > org default). Bundles' sales are decomposed into component demand in `forecast/features.py` before forecasting. `tests/test_planning_engine.py` holds the candle worked example with the hand calculation in its docstring — keep it in sync with any formula change. Stockout date = first day with unmet demand (stock < 0), not the day stock reaches 0.

Covariates: history is DIVIDED by the holiday/promo factor before modelling and the base forecast MULTIPLIED back, so `forecasts.factor` + `forecasts.event` explain every uplift ("Christmas", "promo: Spring Sale"). Uplifts are learned per (category, region, event name) only from data before the backtest holdout; `tests/test_covariates_db.py` asserts adjusted WAPE beats `wape_base` by >= 15 % on a Christmas holdout and prints `[backtest-covariates] ...`. Priors live in `CATEGORY_PRIORS` (keyword match on category name) and are editable via `PATCH /category-uplifts/{id}` (editing a learned row makes it manual). Bands widen 1.5x where a factor rests on a prior.

Ingestion: `POST /imports` (multipart products/sales/inventory/bom CSVs, optional `mapping` JSON and `strict`), `GET /exports/{kind}.csv`. Shopify: `GET /shopify/install?shop=` needs `SHOPIFY_API_KEY/SECRET` and a public `APP_BASE_URL`; the callback stores the token encrypted, registers webhooks and enqueues a 2-year backfill. `POST /channels/{id}/sync` runs on demand.

Shopify tests replay vcrpy cassettes in `tests/cassettes/` that were **synthesized** from documented response shapes (no dev store in CI). To re-record for real: delete the yaml, set real credentials, run `pytest --record-mode=once`.

API tests need Postgres: with `make dev` running, `TEST_DATABASE_URL` from `.env.example` works. Call data routes with header `X-Org-Id: <org uuid>` (demo org: `00000000-0000-0000-0000-00000000d3a0`).

Requirements: Docker, Node 22 + pnpm 9 (`corepack enable`), Python 3.12 + `uv`.

## Coding rules

- **Never push to `main`.** Branch, open a PR, CI must be green.
- **Tests before done.** Every route, task and planning function gets a pytest; every UI component with logic gets a vitest. Keep `make test` green.
- **No secrets in the repo.** Everything via env vars; document new ones in `.env.example`.
- **Every query is org-scoped.** Routes take `org_id: OrgId` and go through `app/services/crud.py` (or filter `org_id` explicitly). Cross-org references (category, product in a BOM) are checked with `crud.assert_owned`. Add a case to `tests/test_org_scoping.py` for every new resource.
- **Schema changes = migration.** Edit models, run `make migration m="..."`, review the file (enums need explicit `DROP TYPE` in downgrade), and keep `upgrade head → downgrade base → upgrade head` clean. CI runs that.
- **Python:** ruff (line length 100), type hints everywhere, Pydantic models for all request/response bodies, no business logic in route handlers (put it in `app/services/`).
- **TypeScript:** strict mode, no `any`, server components by default, client components only when they need state or browser APIs.
- **Idempotent jobs.** Celery tasks must be safe to retry: every write in a sync is an upsert; webhooks dedupe on `X-Shopify-Webhook-Id` via `processed_webhooks`. New connectors subclass `BaseConnector`, register in `ingest/registry.py`, and get cassette-based tests.
- **Small PRs.** One step of the build plan per PR; update this file when layout or rules change.

## Build plan

Follow the step-by-step plan (Stockcast — Build & Deploy Plan). Each step is a self-contained task that ends in a merged, tested PR. Steps done: **1 — repo and setup**, **2 — core data model and database**, **3 — CSV import + Shopify connector**, **4 — forecast engine**, **4b — holiday seasonality + promotion impact**, **5 — planning engine**. Next: **6 — web dashboard**. Step 6 should generate the typed client from `/openapi.json` into `packages/shared` and build pages on the existing endpoints (recommendations, forecasts, purchase orders, calendar).
