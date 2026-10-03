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
