.PHONY: dev down logs install test lint fmt test-api test-web lint-api lint-web migrate migration seed worker cassettes forecast plan install-chronos openapi e2e

## Run everything in Docker (api :8000, web :3000, postgres :5432, redis :6379)
dev:
	@test -f .env || cp .env.example .env
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

## Install local toolchains (for running tests/lint outside Docker)
install:
	cd apps/api && uv sync
	pnpm install

test: test-api test-web

test-api:
	cd apps/api && uv run pytest -q

## Database (run against the compose postgres, or set DATABASE_URL)
migrate:
	cd apps/api && uv run alembic upgrade head

migration:  ## make migration m="add foo"
	cd apps/api && uv run alembic revision --autogenerate -m "$(m)"

seed:
	cd apps/api && uv run python -m scripts.seed

worker:  ## run Celery worker + beat locally (needs redis)
	cd apps/api && uv run celery -A app.worker worker -B -l info

forecast:  ## run a forecast for the demo org (needs seed)
	cd apps/api && uv run python -m scripts.forecast_demo

plan:  ## run planning for the demo org (needs forecast) and print recommendations
	cd apps/api && uv run python -m scripts.plan_demo

install-chronos:  ## optional: CPU torch + chronos for the zero-shot model
	cd apps/api && uv pip install -r requirements-chronos.txt --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple

e2e:  ## Playwright: needs API on :8000 (CELERY_TASK_ALWAYS_EAGER=true) and web on :3000
	cd apps/web && pnpm exec playwright test

typecheck:  ## mypy (api) + tsc (web)
	cd apps/api && uv run mypy
	pnpm -r typecheck

coverage:  ## pytest with the CI coverage gate (>= 80 %)
	cd apps/api && uv run pytest -q --cov=app --cov-report=term-missing:skip-covered --cov-fail-under=80

seed-load:  ## load-test dataset: ORGS x SKUS (defaults 5 x 2000)
	cd apps/api && uv run python -m scripts.seed_load --orgs $(or $(ORGS),5) --skus $(or $(SKUS),2000) --out ../../loadtest/orgs.txt

bench:  ## forecast throughput + projection for 50 orgs x 2,000 SKUs
	cd apps/api && uv run python -m scripts.bench_forecast --workers $(or $(WORKERS),8)

loadtest:  ## k6 against API_URL (default localhost:8000) using loadtest/orgs.txt
	k6 run -e API_URL=$(or $(API_URL),http://localhost:8000) -e ORG_IDS="$$(paste -sd, loadtest/orgs.txt)" loadtest/k6/api.js

ci-stack:  ## production images via docker compose (what CI's e2e + load test run against)
	cp -n .env.example .env || true
	docker compose -f docker-compose.yml -f docker-compose.ci.yml up -d --build --wait postgres redis api web

backup:  ## logical backup to S3 (needs BACKUP_* env); restore: apps/api/scripts/restore.sh
	cd apps/api && sh scripts/backup.sh

openapi:  ## export the OpenAPI spec and regenerate the typed TS client in packages/shared
	cd apps/api && uv run python -m scripts.export_openapi
	pnpm --filter @stockcast/shared gen

cassettes:  ## regenerate synthesized Shopify VCR cassettes
	cd apps/api && uv run python -m tests.cassettes.make_cassettes

test-web:
	pnpm -r --if-present test

lint: lint-api lint-web

lint-api:
	cd apps/api && uv run ruff check . && uv run ruff format --check .

lint-web:
	pnpm -r lint && pnpm -r typecheck

fmt:
	cd apps/api && uv run ruff format . && uv run ruff check --fix .
