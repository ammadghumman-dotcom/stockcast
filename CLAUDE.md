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
  app/main.py        app factory + routes (only /health for now)
  app/config.py      pydantic-settings; all config via env vars
  tests/             pytest
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
```

Requirements: Docker, Node 22 + pnpm 9 (`corepack enable`), Python 3.12 + `uv`.

## Coding rules

- **Never push to `main`.** Branch, open a PR, CI must be green.
- **Tests before done.** Every route, task and planning function gets a pytest; every UI component with logic gets a vitest. Keep `make test` green.
- **No secrets in the repo.** Everything via env vars; document new ones in `.env.example`.
- **Every query is org-scoped.** From Step 2 on, all DB access filters by `org_id`; add a test proving isolation when touching data access.
- **Python:** ruff (line length 100), type hints everywhere, Pydantic models for all request/response bodies, no business logic in route handlers (put it in `app/services/`).
- **TypeScript:** strict mode, no `any`, server components by default, client components only when they need state or browser APIs.
- **Idempotent jobs.** Celery tasks must be safe to retry.
- **Small PRs.** One step of the build plan per PR; update this file when layout or rules change.

## Build plan

Follow the step-by-step plan (Stockcast — Build & Deploy Plan). Each step is a self-contained task that ends in a merged, tested PR. Current step: **1 — repo and setup (done)**. Next: **2 — core data model and database**.
