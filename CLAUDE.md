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
  app/deps.py        auth: get_auth -> AuthContext(org_id, user_id, role); Ctx / OrgId dependencies.
                     AUTH_MODE=clerk verifies Clerk JWTs (JWKS, RS256) and provisions org+user on
                     first sight; AUTH_MODE=header trusts X-Org-Id (+X-Role) for dev/e2e only.
                     Viewers are read-only: non-GET from a viewer is 403 here, centrally.
  app/ratelimit.py   slowapi Limiter keyed by org (token claim / X-Org-Id) else IP; `heavy` decorator
  app/emails.py      Resend transactional mail (welcome, trial_ending, sync_failed, weekly digest),
                     idempotent via email_log (org, kind, dedupe_key); _http_client() seam for tests
  app/emails_tasks.py Celery: emails.trial_ending (daily 09:00), emails.weekly_digest (Mon 07:00)
  app/billing/       plans.py (PLANS, effective_plan, assert_can_add_channel/skus -> 402),
                     stripe_service.py (Checkout, Portal, webhook parse + idempotent handle_event)
  app/services/audit.py  audit.record(db, ctx, action=, entity=, before=, after=) -> audit_log
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
                     from-recommendations, export.csv|pdf, send, mark-sent, receive),
                     billing (GET /billing, POST /billing/checkout|portal, POST /webhooks/stripe)
  alembic/           migrations (sales_daily becomes a Timescale hypertable when available)
  scripts/seed.py    demo org: 20 SKUs, 3 raw materials, 1 BOM, 365 days of sales
  tests/             pytest against a real Postgres (TEST_DATABASE_URL), tx-rollback per test
    cassettes/       vcrpy cassettes for Shopify (synthesized by make_cassettes.py; see below)
apps/web/            Next.js 15 app (client components + TanStack Query)
  app/onboarding     create workspace, connect Shopify or upload CSVs (sync progress), run pipeline
  app/(app)/         Shell (sidebar nav, mobile menu): dashboard, products(+[id]: forecast chart
                     p10/p50/p90 + history, inventory, BOM), raw-materials, recommendations
                     (filters, multi-select -> create PO), purchase-orders(+[id]: CSV/PDF, send,
                     mark-sent, receive), settings (planning, suppliers, channels+regions,
                     categories, team, billing), calendar (events, promotions + simulate, uplifts)
  app/sign-in, sign-up  Clerk pages; middleware.ts protects everything else when Clerk is enabled
  components/ui/     shadcn-style primitives (button, input, table, dialog, tabs, badge, skeleton, empty)
  components/        shell (org/viewer banners), account (Clerk switcher), billing (plans, usage,
                     checkout/portal), products-table, charts/forecast-chart (Recharts)
  lib/api.ts         typed client factory (openapi-fetch) + unwrap(); clientFor(orgId, getToken)
  lib/auth.ts        clerkEnabled (NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY set?)
  lib/org.tsx        OrgProvider: Clerk mode (Bearer JWT, role from org_role) or header mode
                     (X-Org-Id cookie); useOrg().authHeaders() for raw fetches; lib/hooks.ts
  tests/             vitest (utils, badges); e2e/ Playwright (onboarding -> dashboard -> create PO)
packages/shared/     openapi.json (exported by `make openapi`) -> src/api.d.ts (GENERATED) + makeClient()
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
make openapi    # export OpenAPI + regenerate packages/shared/src/api.d.ts (run after API changes)
make e2e        # Playwright against API :8000 (CELERY_TASK_ALWAYS_EAGER=true) + web :3000
```

Web: every page is a client component using `useOrgQuery`/`useAction` from `lib/hooks.ts`; the org comes from the `stockcast_org` cookie (default: demo org) until Clerk (Step 7). After changing any API schema run `make openapi` and commit `packages/shared/openapi.json` + `src/api.d.ts`; the generated types make missing fields a typecheck error. `data-testid` attributes are the e2e contract — keep them when restyling. CI runs the e2e job against a seeded API on a TimescaleDB service.

Forecasting: Chronos-Bolt is **optional at import time** (`requirements-chronos.txt`, CPU torch from the PyTorch index — not in `pyproject` because `uv lock` cannot reach that index everywhere). `chronos_available()` gates it; without it the chronos route uses AutoETS only and `tests/test_chronos_live.py` skips. Docker and CI install it. Backtest = last 28 observed days; the seed-org WAPE is printed as `[backtest] ...` in the test log and the CI job summary.

Planning: raw materials get DERIVED demand = sum(parent forecast p50 x qty_per_unit) through the BOM (multi-level), so they are planned with the same (s,Q) logic as finished goods; products with a BOM are `produce`, others `reorder` from the preferred or cheapest supplier (supplier_products.lead_time_days > supplier.lead_time_days > org default). Bundles' sales are decomposed into component demand in `forecast/features.py` before forecasting. `tests/test_planning_engine.py` holds the candle worked example with the hand calculation in its docstring — keep it in sync with any formula change. Stockout date = first day with unmet demand (stock < 0), not the day stock reaches 0.

Covariates: history is DIVIDED by the holiday/promo factor before modelling and the base forecast MULTIPLIED back, so `forecasts.factor` + `forecasts.event` explain every uplift ("Christmas", "promo: Spring Sale"). Uplifts are learned per (category, region, event name) only from data before the backtest holdout; `tests/test_covariates_db.py` asserts adjusted WAPE beats `wape_base` by >= 15 % on a Christmas holdout and prints `[backtest-covariates] ...`. Priors live in `CATEGORY_PRIORS` (keyword match on category name) and are editable via `PATCH /category-uplifts/{id}` (editing a learned row makes it manual). Bands widen 1.5x where a factor rests on a prior.

Ingestion: `POST /imports` (multipart products/sales/inventory/bom CSVs, optional `mapping` JSON and `strict`), `GET /exports/{kind}.csv`. Shopify: `GET /shopify/install?shop=` needs `SHOPIFY_API_KEY/SECRET` and a public `APP_BASE_URL`; the callback stores the token encrypted, registers webhooks and enqueues a 2-year backfill. `POST /channels/{id}/sync` runs on demand.

Shopify tests replay vcrpy cassettes in `tests/cassettes/` that were **synthesized** from documented response shapes (no dev store in CI). To re-record for real: delete the yaml, set real credentials, run `pytest --record-mode=once`.

API tests need Postgres: with `make dev` running, `TEST_DATABASE_URL` from `.env.example` works. In header mode call data routes with `X-Org-Id: <org uuid>` (demo org: `00000000-0000-0000-0000-00000000d3a0`), optionally `X-Role: viewer|admin|owner`.

Auth & billing (Step 7): the web app switches to Clerk when `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` is set (`lib/auth.ts`, `middleware.ts`, `lib/org.tsx` sends the session JWT as Bearer); the API must then run `AUTH_MODE=clerk`. Clerk org -> `organizations.clerk_org_id`, Clerk user -> `users.external_auth_id`, roles org:owner|admin|member -> owner|admin|viewer. Plans: trial (14 d, Growth limits) / starter / growth / scale; `effective_plan()` returns LOCKED (nothing new can be added, reads still work) when the trial expired or the subscription is canceled/unpaid. Limits are enforced at channel create, Shopify install/callback, product create, CSV import and channel sync (402 with a human message). Stripe webhooks are the only thing that changes `org.plan`; each event id is inserted into `stripe_events` first so replays are no-ops. `tests/test_auth.py::test_every_route_is_org_scoped_or_allowlisted` walks every route and fails if one lacks `OrgId`/`Ctx` — extend `PUBLIC` only for routes signed another way.

Requirements: Docker, Node 22 + pnpm 9 (`corepack enable`), Python 3.12 + `uv`.

## Coding rules

- **Never push to `main`.** Branch, open a PR, CI must be green.
- **Tests before done.** Every route, task and planning function gets a pytest; every UI component with logic gets a vitest. Keep `make test` green.
- **No secrets in the repo.** Everything via env vars; document new ones in `.env.example`.
- **Every query is org-scoped.** Routes take `org_id: OrgId` and go through `app/services/crud.py` (or filter `org_id` explicitly). Cross-org references (category, product in a BOM) are checked with `crud.assert_owned`. Add a case to `tests/test_org_scoping.py` for every new resource.
- **Schema changes = migration.** Edit models, run `make migration m="..."`, review the file (enums need explicit `DROP TYPE` in downgrade; name every unique/FK constraint explicitly so downgrade can drop it), and keep `upgrade head → downgrade base → upgrade head` clean. CI runs that.
- **Audit what matters.** PO create/send/mark-sent/receive, planning settings, product planning overrides and billing changes call `services.audit.record` with before/after snapshots.
- **Mutations use `Ctx`.** A route that writes takes `ctx: Ctx` (role, user) and `ctx.require("admin")` where only admins may act; reads can keep `org_id: OrgId`.
- **Python:** ruff (line length 100), type hints everywhere, Pydantic models for all request/response bodies, no business logic in route handlers (put it in `app/services/`).
- **TypeScript:** strict mode, no `any`, server components by default, client components only when they need state or browser APIs.
- **Idempotent jobs.** Celery tasks must be safe to retry: every write in a sync is an upsert; webhooks dedupe on `X-Shopify-Webhook-Id` via `processed_webhooks`. New connectors subclass `BaseConnector`, register in `ingest/registry.py`, and get cassette-based tests.
- **Small PRs.** One step of the build plan per PR; update this file when layout or rules change.

## Build plan

Follow the step-by-step plan (Stockcast — Build & Deploy Plan). Each step is a self-contained task that ends in a merged, tested PR. Steps done: **1 — repo and setup**, **2 — core data model and database**, **3 — CSV import + Shopify connector**, **4 — forecast engine**, **4b — holiday seasonality + promotion impact**, **5 — planning engine**, **6 — web dashboard**, **7 — auth, multi-tenancy, billing** (Clerk, slowapi, audit log, Stripe, Resend). Next: **8 — more connectors** (Amazon SP-API, WooCommerce, eBay) on the `BaseConnector` contract with cassette tests and plan-limit checks.
